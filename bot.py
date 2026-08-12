import os
import re
import sys
import datetime
from datetime import timedelta
import lxml
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

ADVISORIES_URL = "https://www.ateneo.edu/advisories"

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ============================================================
# ATENEO
# ============================================================

def fetch_advisories():
    r = requests.get(
        ADVISORIES_URL,
        headers={"User-Agent": UA},
        timeout=30
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    article = soup.select_one("article.node--type-page")

    if not article:
        raise RuntimeError("Could not find the Ateneo advisories article.")

    return article


def find_advisory_date(article):
    text = article.get_text(" ", strip=True)

    pattern = (
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{4})\b"
    )

    dates = []

    for day, month, year in re.findall(
        pattern, text, re.IGNORECASE
    ):
        try:
            dates.append(
                datetime.datetime.strptime(
                    f"{day} {month} {year}",
                    "%d %B %Y"
                ).date()
            )
        except ValueError:
            pass

    if not dates:
        raise RuntimeError("Could not find an advisory date.")

    return max(dates)


ALIASES = {
    "AGS": [
        "AGS",
        "Ateneo Grade School",
        "Ateneo Grade School (AGS)"
    ],
    "JHS": [
        "AJHS",
        "Ateneo Junior High School",
        "Ateneo Junior High School (AJHS)"
    ],
    "SHS": [
        "ASHS",
        "Ateneo Senior High School",
        "Ateneo Senior High School (ASHS)"
    ]
}


def get_school_section(text, school):
    start = None
    start_len = 0

    for alias in ALIASES[school]:
        m = re.search(
            rf"\b{re.escape(alias)}\b",
            text,
            re.IGNORECASE
        )

        if m and (start is None or m.start() < start):
            start = m.start()
            start_len = len(m.group())

    if start is None:
        return ""

    section_start = start + start_len
    ends = []

    for other in ALIASES:
        if other == school:
            continue

        for alias in ALIASES[other]:
            m = re.search(
                rf"\b{re.escape(alias)}\b",
                text[section_start:],
                re.IGNORECASE
            )

            if m:
                ends.append(section_start + m.start())

    end = min(ends) if ends else len(text)

    return text[start:end].strip()


def classify(text):
    text = text.lower()

    synchronous = [
        r"\bonline synchronous\b",
        r"\bsynchronous online\b",
        r"\bsynchronous classes?\b",
        r"\bsynchronous session\b",
        r"\bsynchronous instruction\b",
        r"\bsynchronous modality\b",
        r"\bsynchronous learning\b"
    ]

    asynchronous = [
        r"\basynchronous modality\b",
        r"\basynchronous classes?\b",
        r"\bonline asynchronous\b",
        r"\basynchronous online\b",
        r"\basynchronous period\b",
        r"\basynchronous tasks\b",
        r"\basynchronous instruction\b",
        r"\basynchronous work\b",
        r"\basynchronous learning\b",
        r"\basynchronous activities\b"
    ]

    has_sync = any(re.search(x, text) for x in synchronous)
    has_async = any(re.search(x, text) for x in asynchronous)

    if has_sync and has_async:
        return "Mixed Online"

    if has_sync:
        return "Synchronous Online"

    if has_async:
        return "Asynchronous Online"

    suspension = [
        r"\bclasses are suspended\b",
        r"\bclasses have been suspended\b",
        r"\bclasses remain suspended\b",
        r"\bclass suspension is in effect\b",
        r"\bclasses suspended effective\b",
        r"\bclasses are cancelled\b",
        r"\bclasses are canceled\b",
        r"\bno classes will be held\b",
        r"\ball classes are suspended\b"
    ]

    if any(re.search(x, text) for x in suspension):
        return "Suspension"

    online = [
        r"\bonline classes\b",
        r"\bonline class\b",
        r"\bonline modality\b",
        r"\bonline instruction\b",
        r"\bvirtual classes\b",
        r"\bvirtual instruction\b"
    ]

    if any(re.search(x, text) for x in online):
        return "Online"

    onsite = [
        r"\bonsite classes\b",
        r"\bon-site classes\b",
        r"\bface-to-face classes\b",
        r"\bface to face classes\b",
        r"\bf2f classes\b",
        r"\bonsite instruction\b",
        r"\bclasses.*resume.*onsite\b",
        r"\bresume.*onsite classes\b"
    ]

    if any(re.search(x, text) for x in onsite):
        return "Onsite"

    return "Unknown"


def get_statuses(article):
    text = article.get_text(" ", strip=True)
    statuses = {}

    for school in ("AGS", "JHS", "SHS"):
        section = get_school_section(text, school)
        statuses[school] = classify(section)

        print(f"[DEBUG] {school}: {statuses[school]}")

    return statuses


# ============================================================
# QC GOVERNMENT CHECK
# ============================================================

def check_qc_government_feed(target_date):
    rss_url = "https://quezoncity.gov.ph/feed/"
    fallback_url = "https://quezoncity.gov.ph/news/"

    headers = {"User-Agent": UA}

    day = str(target_date.day)

    date_strings = {
        f"{target_date.strftime('%B')} {day} {target_date.year}".lower(),
        f"{target_date.strftime('%B')} {day}".lower(),
        target_date.strftime("%B-%d-%Y").lower(),
        f"{target_date.strftime('%B')}-{day}-{target_date.year}".lower()
    }

    suspension_words = [
        "suspendido",
        "walang pasok",
        "suspended",
        "suspension"
    ]

    private_words = [
        "private schools",
        "private school",
        "pribadong paaralan",
        "pribadong paaralan."
    ]

    def inspect(text, title=""):
        combined = f"{title} {text}".lower()

        if not any(x in combined for x in date_strings):
            return None

        if not any(x in combined for x in suspension_words):
            return None

        # PUBLIC-ONLY announcements do NOT count.
        if not any(x in combined for x in private_words):
            return None

        return (
            True,
            f"Private-school suspension: {title}".strip()
        )

    # ---------------- RSS ----------------

    try:
        r = requests.get(
            rss_url,
            headers=headers,
            timeout=10
        )

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "xml")

            for item in soup.find_all("item"):
                title = item.title.text if item.title else ""
                content = (
                    item.description.text
                    if item.description
                    else ""
                )

                result = inspect(content, title)

                if result:
                    return result

    except Exception as e:
        print(f"QC RSS check failed: {e}", file=sys.stderr)

    # ---------------- FALLBACK ----------------

    try:
        r = requests.get(
            fallback_url,
            headers=headers,
            timeout=10
        )

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")

            for link in soup.find_all("a"):
                href = link.get("href", "")
                text = link.get_text(" ", strip=True)

                result = inspect(
                    text + " " + href,
                    text
                )

                if result:
                    return result

    except Exception as e:
        print(f"QC fallback failed: {e}", file=sys.stderr)

    return False, "No matching private-school suspension."


# ============================================================
# PAGASA
# ============================================================

def check_pagasa_bulletin(target_date):
    url = "https://bagong.pagasa.dost.gov.ph/weather"

    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA},
            timeout=10
        )

        if r.status_code != 200:
            return False, "PAGASA unavailable."

        html = r.text.lower()

        if (
            "metro manila" not in html
            and "quezon city" not in html
        ):
            return False, "No NCR PAGASA trigger."

        signal_3 = any(
            f"signal no. {i}" in html
            for i in range(3, 6)
        )

        signal_1_2 = any(
            f"signal no. {i}" in html
            for i in range(1, 3)
        )

        rainfall = (
            "red rainfall" in html
            or "orange rainfall" in html
        )

        if signal_3:
            return (
                False,
                "PAGASA Signal No. 3+ detected; "
                "public-only trigger ignored."
            )

        if signal_1_2:
            return (
                False,
                "PAGASA Signal No. 1/2 detected; "
                "public-only trigger ignored."
            )

        if rainfall:
            return (
                False,
                "PAGASA rainfall warning detected; "
                "public-only trigger ignored."
            )

    except Exception as e:
        print(
            f"PAGASA check failed: {e}",
            file=sys.stderr
        )

    return False, "No relevant PAGASA trigger."


# ============================================================
# ICONS
# ============================================================

def status_icon(status):
    return {
        "Synchronous Online": "🟢",
        "Asynchronous Online": "🟢",
        "Mixed Online": "🟢",
        "Online": "🟢",
        "Suspension": "🔴",
        "No School": "🔴",
        "Onsite": "🔵",
        "Unknown": "🟡"
    }.get(status, "🟡")


def format_date(date):
    return date.strftime("%B ") + str(date.day)


# ============================================================
# MESSAGE
# ============================================================

def create_message(date, statuses, suspension_reason=None):
    next_date = date + timedelta(days=1)

    date1 = format_date(date)
    date2 = format_date(next_date)

    lines = [
        "Yall heres the school status :D",
        "",
        f"this is for: *{date1}* and *{date2}*",
        "",
        f"*School* | *{date1}* | *{date2}*",
        "--------------------------------",
        (
            f"*AGS* | "
            f"{status_icon(statuses['AGS'])} "
            f"{statuses['AGS']} | 🟡 Unknown"
        ),
        (
            f"*JHS* | "
            f"{status_icon(statuses['JHS'])} "
            f"{statuses['JHS']} | 🟡 Unknown"
        ),
        (
            f"*SHS* | "
            f"{status_icon(statuses['SHS'])} "
            f"{statuses['SHS']} | 🟡 Unknown"
        )
    ]

    if suspension_reason:
        lines += [
            "",
            "🚨 *Private schools are suspended.*",
            suspension_reason
        ]

    lines += [
        "",
        f"🔗 {ADVISORIES_URL}",
        f"🔗 https://bagong.pagasa.dost.gov.ph/weather",
        f"🔗 https://quezoncity.gov.ph/feed/"
    ]

    return "\n".join(lines)


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_to_google_chat(message):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "GOOGLE_CHAT_WEBHOOK secret is not set."
        )

    r = requests.post(
        WEBHOOK_URL,
        json={"text": message},
        timeout=30
    )

    r.raise_for_status()


# ============================================================
# MAIN
# ============================================================

def check_once():
    today = datetime.date.today()

    print("==========================================")
    print("Ateneo School Status Bot")
    print(f"Today's date: {today}")
    print(f"Advisories: {ADVISORIES_URL}")
    print("==========================================")

    # --------------------------------------------------------
    # ATENEO
    # --------------------------------------------------------

    article = fetch_advisories()

    advisory_date = find_advisory_date(article)

    print(
        f"Ateneo page advisory date: "
        f"{format_date(advisory_date)}"
    )

    # CRITICAL:
    # Only use Ateneo statuses when the advisory
    # is actually dated TODAY.
    if advisory_date == today:
        print("Ateneo advisory matches today: True")

        statuses = get_statuses(article)
        aten_status_valid = True

    else:
        print("Ateneo advisory matches today: False")
        print(
            ">> Ateneo statuses ignored because "
            "the advisory is for another date."
        )
        print(
            ">> Defaulting today's status to Face-to-Face."
        )

        statuses = {
            "AGS": "Onsite",
            "JHS": "Onsite",
            "SHS": "Onsite"
        }

        aten_status_valid = False

    # --------------------------------------------------------
    # IF ATENEO IS NOT TODAY:
    # CHECK QC + PAGASA
    # --------------------------------------------------------

    private_suspended, qc_reason = (
        check_qc_government_feed(today)
    )

    pagasa_suspended, pagasa_reason = (
        check_pagasa_bulletin(today)
    )

    print(
        f"Private-school suspension: "
        f"{private_suspended}"
    )

    print(f"QC: {qc_reason}")
    print(f"PAGASA: {pagasa_reason}")

    # --------------------------------------------------------
    # GENERAL NO-SCHOOL OVERRIDE
    #
    # ONLY PRIVATE SCHOOL SUSPENSION COUNTS.
    # Public-school suspension does NOT.
    # --------------------------------------------------------

    if not aten_status_valid and private_suspended:
        print(
            ">> No School override: "
            "private schools are suspended."
        )

        statuses = {
            "AGS": "No School",
            "JHS": "No School",
            "SHS": "No School"
        }

        suspension_reason = qc_reason

    elif not aten_status_valid:
        print(
            ">> No School override skipped: "
            "no private-school suspension."
        )

        suspension_reason = None

    else:
        # Today's Ateneo advisory wins.
        suspension_reason = None

    # --------------------------------------------------------
    # SEND EVERY TIME
    # --------------------------------------------------------

    message = create_message(
        today,
        statuses,
        suspension_reason
    )

    print("")
    print(message)
    print("")

    send_to_google_chat(message)

    print("Sent update to Google Chat.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        check_once()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
