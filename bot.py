import os
import re
import sys
import datetime
from datetime import timedelta

import requests
import holidays
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

ADVISORIES_URL = "https://www.ateneo.edu/advisories"
FACEBOOK_URL = "https://www.facebook.com/ateneodemanila/"

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

FACEBOOK_LOOKBACK_DAYS = 14


# ============================================================
# GENERIC HELPERS
# ============================================================

def fetch(url, timeout=30, headers=None):
    r = requests.get(
        url,
        headers=headers or {"User-Agent": UA},
        timeout=timeout
    )
    r.raise_for_status()
    return r


def format_date(date):
    return date.strftime("%B ") + str(date.day)


def parse_date_from_text(text):
    """
    Finds dates like:
      August 12, 2026
      August 12 2026
      12 August 2026
    """

    patterns = [
        r"\b"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(\d{4})"
        r"\b",

        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+(\d{4})"
        r"\b",
    ]

    dates = []

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE
        ):
            parts = match.groups()

            try:
                if parts[0].isdigit():
                    day, month, year = parts

                    dates.append(
                        datetime.datetime.strptime(
                            f"{day} {month} {year}",
                            "%d %B %Y"
                        ).date()
                    )

                else:
                    month, day, year = parts

                    dates.append(
                        datetime.datetime.strptime(
                            f"{month} {day} {year}",
                            "%B %d %Y"
                        ).date()
                    )

            except ValueError:
                pass

    return dates


# ============================================================
# PHILIPPINE HOLIDAYS / WEEKENDS
# ============================================================

def check_ph_calendar(target_date):
    """
    Automatically treats:
      - Saturday
      - Sunday
      - Philippine national holidays

    as no-class days.

    Returns:
        (True, reason)  -> No classes
        (False, None)   -> Normal school day
    """

    # Saturday = 5
    # Sunday   = 6
    if target_date.weekday() >= 5:
        return (
            True,
            "Weekend"
        )

    ph_holidays = holidays.country_holidays(
        "PH",
        years=target_date.year
    )

    if target_date in ph_holidays:
        holiday_name = ph_holidays.get(
            target_date
        )

        return (
            True,
            f"Philippine holiday: {holiday_name}"
        )

    return (
        False,
        None
    )


# ============================================================
# ATENEO
# ============================================================

def fetch_advisories():
    r = fetch(ADVISORIES_URL)

    soup = BeautifulSoup(
        r.text,
        "html.parser"
    )

    article = soup.select_one(
        "article.node--type-page"
    )

    if not article:
        raise RuntimeError(
            "Could not find the Ateneo advisories article."
        )

    return article


def find_advisory_date(article):
    text = article.get_text(
        " ",
        strip=True
    )

    pattern = (
        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{4})\b"
    )

    dates = []

    for day, month, year in re.findall(
        pattern,
        text,
        re.IGNORECASE
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
        raise RuntimeError(
            "Could not find an Ateneo advisory date."
        )

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

        if m and (
            start is None
            or m.start() < start
        ):
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
                ends.append(
                    section_start + m.start()
                )

    end = min(ends) if ends else len(text)

    return text[start:end].strip()


# ============================================================
# ATENEO CLASSIFIER
# ============================================================

def classify(text):
    text = text.lower()

    # Ignore conditional suspension wording.
    text = re.sub(
        r"if .*?(?:declares?|declare).*?"
        r"(?:class suspension|suspension).*?(?:\.|$)",
        " ",
        text,
        flags=re.IGNORECASE
    )

    synchronous = [
        r"\bonline synchronous\b",
        r"\bsynchronous online\b",
        r"\bsynchronous classes?\b",
        r"\bsynchronous session\b",
        r"\bsynchronous instruction\b",
        r"\bsynchronous modality\b",
        r"\bsynchronous learning\b",
        r"\bonline.*synchronous\b",
        r"\bsynchronous.*online\b"
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
        r"\basynchronous activities\b",
        r"\bcontinue.*asynchronous\b"
    ]

    has_sync = any(
        re.search(x, text)
        for x in synchronous
    )

    has_async = any(
        re.search(x, text)
        for x in asynchronous
    )

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

    if any(
        re.search(x, text)
        for x in suspension
    ):
        return "Suspension"

    online = [
        r"\bonline classes\b",
        r"\bonline class\b",
        r"\bonline modality\b",
        r"\bonline instruction\b",
        r"\bvirtual classes\b",
        r"\bvirtual instruction\b"
    ]

    if any(
        re.search(x, text)
        for x in online
    ):
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

    if any(
        re.search(x, text)
        for x in onsite
    ):
        return "Onsite"

    return "Onsite"


def get_statuses(article):
    text = article.get_text(
        " ",
        strip=True
    )

    statuses = {}

    for school in (
        "AGS",
        "JHS",
        "SHS"
    ):
        section = get_school_section(
            text,
            school
        )

        statuses[school] = classify(section)

        print(
            f"[DEBUG] {school}: "
            f"{statuses[school]}"
        )

    return statuses


# ============================================================
# QC GOVERNMENT
# ============================================================

def check_qc_government_feed(target_date):
    rss_url = "https://quezoncity.gov.ph/feed/"
    fallback_url = "https://quezoncity.gov.ph/news/"

    headers = {
        "User-Agent": UA
    }

    date_strings = {
        f"{target_date.strftime('%B')} "
        f"{target_date.day} "
        f"{target_date.year}".lower(),

        f"{target_date.strftime('%B')} "
        f"{target_date.day}".lower(),

        target_date.strftime(
            "%B-%d-%Y"
        ).lower(),

        f"{target_date.strftime('%B')}-"
        f"{target_date.day}-"
        f"{target_date.year}".lower(),
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
        "pribadong paaralan"
    ]

    def inspect(text, title=""):
        combined = (
            title + " " + text
        ).lower()

        if not any(
            x in combined
            for x in date_strings
        ):
            return None

        if not any(
            x in combined
            for x in suspension_words
        ):
            return None

        # Public-only announcements do NOT count.
        if not any(
            x in combined
            for x in private_words
        ):
            return None

        return (
            True,
            f"Private-school suspension: "
            f"{title}".strip()
        )

    # ---------------- RSS ----------------

    try:
        r = fetch(
            rss_url,
            timeout=10,
            headers=headers
        )

        soup = BeautifulSoup(
            r.text,
            "xml"
        )

        for item in soup.find_all("item"):
            title = (
                item.title.text
                if item.title
                else ""
            )

            content = (
                item.description.text
                if item.description
                else ""
            )

            result = inspect(
                content,
                title
            )

            if result:
                return result

    except Exception as e:
        print(
            f"QC RSS check failed: {e}",
            file=sys.stderr
        )

    # ---------------- FALLBACK ----------------

    try:
        r = fetch(
            fallback_url,
            timeout=10,
            headers=headers
        )

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        for link in soup.find_all("a"):
            href = link.get(
                "href",
                ""
            )

            text = link.get_text(
                " ",
                strip=True
            )

            result = inspect(
                text + " " + href,
                text
            )

            if result:
                return result

    except Exception as e:
        print(
            f"QC fallback failed: {e}",
            file=sys.stderr
        )

    return (
        False,
        "No matching private-school suspension."
    )


# ============================================================
# PAGASA
# ============================================================

def check_pagasa_bulletin(target_date):
    url = (
        "https://bagong.pagasa.dost.gov.ph/weather"
    )

    try:
        r = fetch(
            url,
            timeout=10
        )

        html = r.text.lower()

        if (
            "metro manila" not in html
            and "quezon city" not in html
        ):
            return (
                False,
                "No NCR PAGASA trigger."
            )

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

    return (
        False,
        "No relevant PAGASA trigger."
    )


# ============================================================
# FACEBOOK
# ============================================================

def check_facebook(target_date):
    cutoff = (
        target_date -
        timedelta(days=FACEBOOK_LOOKBACK_DAYS)
    )

    headers = {
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(
            FACEBOOK_URL,
            headers=headers,
            timeout=20
        )

        if r.status_code != 200:
            print(
                f"Facebook returned HTTP {r.status_code}"
            )
            return None

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        raw_text = soup.get_text(
            " ",
            strip=True
        )

        lower = raw_text.lower()

        # Facebook login/block pages are not useful.
        if (
            "log in" in lower
            and len(raw_text) < 5000
        ):
            print(
                "Facebook: login page returned."
            )
            return None

        # Remove scripts/styles.
        for tag in soup([
            "script",
            "style",
            "noscript"
        ]):
            tag.decompose()

        pieces = []

        for tag in soup.find_all([
            "article",
            "div",
            "p",
            "span"
        ]):
            text = tag.get_text(
                " ",
                strip=True
            )

            if (
                text
                and len(text) >= 20
                and text not in pieces
            ):
                pieces.append(text)

        content = "\n".join(
            pieces[:1000]
        )

        content_lower = content.lower()

        # ----------------------------------------------------
        # Explicit private-school suspension terms
        # ----------------------------------------------------

        suspension_words = [
            "private schools",
            "private school",
            "pribadong paaralan"
        ]

        suspension_action = [
            "suspended",
            "suspension",
            "suspendido",
            "walang pasok",
            "no classes"
        ]

        if not any(
            x in content_lower
            for x in suspension_words
        ):
            return None

        if not any(
            x in content_lower
            for x in suspension_action
        ):
            return None

        # ----------------------------------------------------
        # Collect dates visible on page
        # ----------------------------------------------------

        dates = parse_date_from_text(
            content
        )

        recent_dates = [
            d for d in dates
            if cutoff <= d <= target_date
        ]

        if not recent_dates:
            return None

        newest = max(recent_dates)

        return {
            "private_suspended": True,
            "date": newest,
            "reason": (
                "Facebook private-school "
                "suspension detected."
            ),
        }

    except Exception as e:
        print(
            f"Facebook check failed: {e}",
            file=sys.stderr
        )

    return None


# ============================================================
# STATUS ICONS
# ============================================================

def status_icon(status):
    return {
        "Synchronous Online": "🟢",
        "Asynchronous Online": "🟢",
        "Mixed Online": "🟢",
        "Online": "🟢",
        "Suspension": "🔴",
        "No School": "❌",
        "Onsite": "🔵",
        "Unknown": "🟡"
    }.get(
        status,
        "🟡"
    )


# ============================================================
# GOOGLE CHAT MESSAGE
# ============================================================

def create_message(
    date,
    statuses,
    reason=None,
    reason_type=None
):
    next_date = (
        date +
        timedelta(days=1)
    )

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
            f"{statuses['AGS']} | "
            f"🟡 Unknown"
        ),
        (
            f"*JHS* | "
            f"{status_icon(statuses['JHS'])} "
            f"{statuses['JHS']} | "
            f"🟡 Unknown"
        ),
        (
            f"*SHS* | "
            f"{status_icon(statuses['SHS'])} "
            f"{statuses['SHS']} | "
            f"🟡 Unknown"
        ),
    ]

    if reason:
        lines += [
            "",
        ]

        if reason_type == "calendar":
            lines += [
                "🚨 *NO CLASSES.*",
                reason,
            ]

        else:
            lines += [
                "🚨 *Private schools are suspended.*",
                reason,
            ]

    lines += [
        "",
        f"🔗 {ADVISORIES_URL}",
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

    print(
        "=========================================="
    )

    print(
        "Ateneo School Status Bot"
    )

    print(
        f"Today's date: {format_date(today)}"
    )

    print(
        f"Advisories: {ADVISORIES_URL}"
    )

    print(
        f"Facebook lookback: "
        f"{FACEBOOK_LOOKBACK_DAYS} days"
    )

    print(
        "=========================================="
    )

    # --------------------------------------------------------
    # PHILIPPINE CALENDAR
    # --------------------------------------------------------

    calendar_no_classes, calendar_reason = (
        check_ph_calendar(today)
    )

    print(
        "Philippine calendar: "
        f"{calendar_reason if calendar_no_classes else 'Normal school day'}"
    )

    # --------------------------------------------------------
    # WEEKEND / HOLIDAY OVERRIDE
    # --------------------------------------------------------
    #
    # This has the highest priority.
    #
    # Saturday/Sunday/PH holiday:
    #     ❌ No School
    #
    # No need to check Ateneo, QC, PAGASA, or Facebook.
    # --------------------------------------------------------

    if calendar_no_classes:

        print(
            f">>> NO CLASSES: {calendar_reason}"
        )

        statuses = {
            "AGS": "No School",
            "JHS": "No School",
            "SHS": "No School"
        }

        message = create_message(
            today,
            statuses,
            reason=calendar_reason,
            reason_type="calendar"
        )

        print("")
        print(message)
        print("")

        send_to_google_chat(
            message
        )

        print(
            "Sent update to Google Chat."
        )

        return

    # --------------------------------------------------------
    # ATENEO
    # --------------------------------------------------------

    article = fetch_advisories()

    advisory_date = find_advisory_date(
        article
    )

    print(
        f"Ateneo page advisory date: "
        f"{format_date(advisory_date)}"
    )

    if advisory_date == today:

        print(
            "Ateneo advisory matches today: True"
        )

        statuses = get_statuses(
            article
        )

        aten_status_valid = True

    else:

        print(
            "Ateneo advisory matches today: False"
        )

        print(
            ">> Ignoring Ateneo statuses because "
            "the advisory is for another date."
        )

        statuses = {
            "AGS": "Onsite",
            "JHS": "Onsite",
            "SHS": "Onsite"
        }

        aten_status_valid = False

    # --------------------------------------------------------
    # QC
    # --------------------------------------------------------

    qc_private, qc_reason = (
        check_qc_government_feed(
            today
        )
    )

    print(
        f"Private-school suspension (QC): "
        f"{qc_private}"
    )

    print(
        f"QC: {qc_reason}"
    )

    # --------------------------------------------------------
    # PAGASA
    # --------------------------------------------------------

    _, pagasa_reason = (
        check_pagasa_bulletin(
            today
        )
    )

    print(
        f"PAGASA: {pagasa_reason}"
    )

    # --------------------------------------------------------
    # FACEBOOK
    # --------------------------------------------------------

    facebook_result = check_facebook(
        today
    )

    if facebook_result:

        facebook_private = True

        print(
            "Facebook: private-school "
            "suspension found."
        )

        print(
            f"Facebook date: "
            f"{format_date(facebook_result['date'])}"
        )

    else:

        facebook_private = False

        print(
            "Facebook: no usable private-school "
            "suspension found."
        )

    # --------------------------------------------------------
    # PRIVATE SCHOOL OVERRIDE
    # --------------------------------------------------------

    private_suspended = (
        qc_private
        or facebook_private
    )

    if private_suspended:

        print(
            ">>> PRIVATE SCHOOL SUSPENSION "
            "DETECTED."
        )

        if qc_private:
            reason = qc_reason
        else:
            reason = facebook_result[
                "reason"
            ]

        statuses = {
            "AGS": "No School",
            "JHS": "No School",
            "SHS": "No School"
        }

        suspension_reason = reason
        reason_type = "suspension"

    else:

        suspension_reason = None
        reason_type = None

        if aten_status_valid:

            print(
                ">>> Using today's Ateneo "
                "advisory."
            )

        else:

            print(
                ">>> No current Ateneo advisory. "
                "Defaulting to Face-to-Face."
            )

    # --------------------------------------------------------
    # SEND EVERY RUN
    # --------------------------------------------------------

    message = create_message(
        today,
        statuses,
        reason=suspension_reason,
        reason_type=reason_type
    )

    print("")
    print(message)
    print("")

    send_to_google_chat(
        message
    )

    print(
        "Sent update to Google Chat."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        check_once()

    except Exception as e:
        print(
            f"ERROR: {e}",
            file=sys.stderr
        )

        sys.exit(1)
