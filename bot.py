import os
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup


ADVISORIES_URL = "https://www.ateneo.edu/advisories"

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


def fetch_advisories():
    response = requests.get(
        ADVISORIES_URL,
        timeout=30,
        headers={"User-Agent": UA},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    article = soup.select_one("article.node--type-page")

    if not article:
        raise RuntimeError(
            "Could not find the Ateneo advisories article."
        )

    return article


def find_advisory_date(article):
    text = article.get_text(" ", strip=True)

    pattern = (
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+(\d{4})\b"
    )

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        raise RuntimeError("Could not find an advisory date.")

    dates = []

    for day, month, year in matches:
        try:
            dates.append(
                datetime.strptime(
                    f"{day} {month} {year}",
                    "%d %B %Y",
                ).date()
            )
        except ValueError:
            pass

    if not dates:
        raise RuntimeError("Could not parse advisory dates.")

    return max(dates)


ALIASES = {
    "AGS": [
        "AGS",
        "Ateneo Grade School",
        "Ateneo Grade School (AGS)",
    ],
    "JHS": [
        "AJHS",
        "Ateneo Junior High School",
        "Ateneo Junior High School (AJHS)",
    ],
    "SHS": [
        "ASHS",
        "Ateneo Senior High School",
        "Ateneo Senior High School (ASHS)",
    ],
}


def get_school_section(text, school):
    aliases = ALIASES[school]

    start_match = None

    for alias in aliases:
        match = re.search(
            rf"\b{re.escape(alias)}\b",
            text,
            re.IGNORECASE,
        )

        if match:
            if (
                start_match is None
                or match.start() < start_match.start()
            ):
                start_match = match

    if not start_match:
        return ""

    start = start_match.start()
    search_start = start + len(start_match.group())

    positions = []

    for other_school, other_aliases in ALIASES.items():
        if other_school == school:
            continue

        for alias in other_aliases:
            match = re.search(
                rf"\b{re.escape(alias)}\b",
                text[search_start:],
                re.IGNORECASE,
            )

            if match:
                positions.append(
                    search_start + match.start()
                )

    end = min(positions) if positions else len(text)

    return text[start:end].strip()


def classify(text):
    text = text.lower()

    conditional_patterns = [
        r"if .*?declares? .*?class suspension.*?(?:\.|$)",
        r"if .*?declare .*?class suspension.*?(?:\.|$)",
        r"if .*?government .*?class suspension.*?(?:\.|$)",
        r"in case .*?class suspension.*?(?:\.|$)",
    ]

    for pattern in conditional_patterns:
        text = re.sub(
            pattern,
            " ",
            text,
            flags=re.IGNORECASE,
        )

    synchronous_patterns = [
        r"\bonline synchronous\b",
        r"\bsynchronous online\b",
        r"\bsynchronous classes?\b",
        r"\bsynchronous session\b",
        r"\bsynchronous instruction\b",
        r"\bsynchronous modality\b",
        r"\bsynchronous learning\b",
        r"\bonline.*synchronous\b",
        r"\bsynchronous.*online\b",
    ]

    asynchronous_patterns = [
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
        r"\bcontinue.*asynchronous\b",
    ]

    has_sync = any(
        re.search(pattern, text)
        for pattern in synchronous_patterns
    )

    has_async = any(
        re.search(pattern, text)
        for pattern in asynchronous_patterns
    )

    if has_sync and has_async:
        return "Mixed Online"

    if has_sync:
        return "Synchronous Online"

    if has_async:
        return "Asynchronous Online"

    suspension_patterns = [
        r"\bclasses are suspended\b",
        r"\bclasses have been suspended\b",
        r"\bclasses remain suspended\b",
        r"\bclass suspension is in effect\b",
        r"\bclasses suspended effective\b",
        r"\bclasses are cancelled\b",
        r"\bclasses are canceled\b",
        r"\bno classes will be held\b",
        r"\ball classes are suspended\b",
    ]

    if any(
        re.search(pattern, text)
        for pattern in suspension_patterns
    ):
        return "Suspension"

    online_patterns = [
        r"\bonline classes\b",
        r"\bonline class\b",
        r"\bonline modality\b",
        r"\bonline instruction\b",
        r"\bvirtual classes\b",
        r"\bvirtual instruction\b",
    ]

    if any(
        re.search(pattern, text)
        for pattern in online_patterns
    ):
        return "Online"

    onsite_patterns = [
        r"\bonsite classes\b",
        r"\bon-site classes\b",
        r"\bface-to-face classes\b",
        r"\bface to face classes\b",
        r"\bf2f classes\b",
        r"\bonsite instruction\b",
        r"\bclasses.*resume.*onsite\b",
        r"\bresume.*onsite classes\b",
    ]

    if any(
        re.search(pattern, text)
        for pattern in onsite_patterns
    ):
        return "Onsite"

    return "Unknown"


def get_statuses(article):
    text = article.get_text(" ", strip=True)

    statuses = {}

    for school in ("AGS", "JHS", "SHS"):
        section = get_school_section(
            text,
            school,
        )

        statuses[school] = classify(section)

        print(
            f"{school}: {statuses[school]}"
        )

    return statuses


def status_icon(status):
    return {
        "Synchronous Online": "🟢",
        "Asynchronous Online": "🟢",
        "Mixed Online": "🟢",
        "Online": "🟢",
        "Suspension": "🔴",
        "Onsite": "🔵",
        "Unknown": "🟡",
    }.get(status, "🟡")


def format_date(date):
    return date.strftime("%B %-d")


def create_message(advisory_date, statuses):
    next_date = advisory_date + timedelta(days=1)

    date1 = format_date(advisory_date)
    date2 = format_date(next_date)

    return "\n".join([
        "Yall heres the school status :D",
        f"this is for: *{date1}* and *{date2}* if they released that or somthing",
        "",
        f"*School* | *{date1}* | *{date2}*",
        "--------------------------------",
        f"*AGS* | {status_icon(statuses['AGS'])} {statuses['AGS']} | 🟡 Unknown",
        f"*JHS* | {status_icon(statuses['JHS'])} {statuses['JHS']} | 🟡 Unknown",
        f"*SHS* | {status_icon(statuses['SHS'])} {statuses['SHS']} | 🟡 Unknown",
        "",
        f"🔗 {ADVISORIES_URL}",
    ])


def send_to_google_chat(message):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "GOOGLE_CHAT_WEBHOOK secret is not set."
        )

    response = requests.post(
        WEBHOOK_URL,
        json={"text": message},
        timeout=30,
    )

    response.raise_for_status()


def main():
    print("Checking Ateneo advisories...")

    article = fetch_advisories()
    advisory_date = find_advisory_date(article)
    statuses = get_statuses(article)

    message = create_message(
        advisory_date,
        statuses,
    )

    print()
    print(message)
    print()

    send_to_google_chat(message)

    print("Sent update to Google Chat.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}")
        raise
