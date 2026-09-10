import os
import re
import sys
import datetime
from datetime import timedelta
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
import holidays
import feedparser

from bs4 import BeautifulSoup


ADVISORIES_URL = "https://www.ateneo.edu/advisories"
FACEBOOK_URL = "https://www.facebook.com/ateneodemanila/"
QC_FEED_URL = "https://quezoncity.gov.ph/feed/"
QC_NEWS_URL = "https://quezoncity.gov.ph/news/"
PAGASA_NCR_URL = "https://bagong.pagasa.dost.gov.ph/regional-forecast/ncrprsd"

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

FACEBOOK_LOOKBACK_DAYS = 14
ADVISORY_LOOKBACK_DAYS = 7
QC_LOOKBACK_DAYS = 3

PH_TIMEZONE = ZoneInfo("Asia/Manila")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    }
)

MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)

SCHOOL_ALIASES = {
    "AGS": [
        "Ateneo Grade School",
        "Ateneo Grade School (AGS)",
        "AGS",
    ],
    "JHS": [
        "Ateneo Junior High School",
        "Ateneo Junior High School (AJHS)",
        "AJHS",
        "JHS",
    ],
    "SHS": [
        "Ateneo Senior High School",
        "Ateneo Senior High School (ASHS)",
        "ASHS",
        "SHS",
    ],
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch(url, timeout=30, **kwargs):
    response = SESSION.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# DATE HELPERS
# ---------------------------------------------------------------------------

def get_ph_date():
    return datetime.datetime.now(PH_TIMEZONE).date()


def format_date(value):
    return value.strftime("%B ") + str(value.day)


def normalize_month(value):
    return {
        "jan": "Jan",
        "january": "January",
        "feb": "Feb",
        "february": "February",
        "mar": "Mar",
        "march": "March",
        "apr": "Apr",
        "april": "April",
        "may": "May",
        "jun": "Jun",
        "june": "June",
        "jul": "Jul",
        "july": "July",
        "aug": "Aug",
        "august": "August",
        "sep": "Sep",
        "sept": "Sep",
        "september": "September",
        "oct": "Oct",
        "october": "October",
        "nov": "Nov",
        "november": "November",
        "dec": "Dec",
        "december": "December",
    }.get(value.lower().strip())


def parse_single_date(day, month, year):
    month = normalize_month(month)

    if not month:
        return None

    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.datetime.strptime(
                f"{day} {month} {year}",
                fmt,
            ).date()
        except ValueError:
            pass

    return None


def parse_date_from_text(text):
    patterns = (
        rf"\b({MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})\b",
    )

    dates = []

    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, re.I):
            a, b, c = match.groups()

            if index == 0:
                value = parse_single_date(b, a, c)
            else:
                value = parse_single_date(a, b, c)

            if value:
                dates.append(value)

    return dates


def dates_in_window(text, start_date, end_date):
    return [
        value
        for value in parse_date_from_text(text)
        if start_date <= value <= end_date
    ]


# ---------------------------------------------------------------------------
# PHILIPPINE CALENDAR
# ---------------------------------------------------------------------------

def check_ph_calendar(value):
    if value.weekday() >= 5:
        return True, "Weekend"

    fixed_special_days = {
        (8, 21): "Ninoy Aquino Day",
        (11, 1): "All Saints' Day",
        (12, 8): "Feast of the Immaculate Conception",
        (12, 24): "Christmas Eve",
        (12, 31): "Last Day of the Year",
    }

    if (value.month, value.day) in fixed_special_days:
        return (
            True,
            "Philippine special non-working day: "
            + fixed_special_days[(value.month, value.day)],
        )

    holidays_for_year = holidays.country_holidays(
        "PH",
        years=value.year,
    )

    if value in holidays_for_year:
        return (
            True,
            f"Philippine holiday: {holidays_for_year.get(value)}",
        )

    return False, None


# ---------------------------------------------------------------------------
# GENERIC HTML
# ---------------------------------------------------------------------------

def get_page_text(soup):
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    return soup.get_text("\n", strip=True)


# ---------------------------------------------------------------------------
# ATENEO
# ---------------------------------------------------------------------------

def fetch_advisories():
    return BeautifulSoup(
        fetch(ADVISORIES_URL).text,
        "html.parser",
    )


def find_class_arrangements_date(soup):
    text = get_page_text(soup)

    # First try to specifically associate "Class Arrangements"
    # with its Last Updated date.
    match = re.search(
        r"Class Arrangements.{0,1500}?"
        r"Last Updated on.{0,150}?"
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",
        text,
        re.I | re.S,
    )

    if match:
        value = parse_single_date(*match.groups())

        if value:
            return value

    # Fallback: find all Last Updated dates.
    values = [
        parse_single_date(*groups)
        for groups in re.findall(
            r"Last Updated on.{0,150}?"
            rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",
            text,
            re.I | re.S,
        )
    ]

    values = [value for value in values if value]

    if values:
        print(
            "[WARNING] Could not specifically identify "
            "Class Arrangements update date."
        )
        print(
            "[WARNING] Using newest 'Last Updated' date."
        )

        return max(values)

    raise RuntimeError(
        "Could not find an Ateneo Class Arrangements update date."
    )


def is_recent_advisory_date(advisory_date, today):
    """
    Ateneo occasionally has an advisory whose internal/update date
    does not exactly equal today.

    Accept today OR anything within the previous N days.
    """
    minimum = today - timedelta(days=ADVISORY_LOOKBACK_DAYS)

    return minimum <= advisory_date <= today


def find_school_position(text, school):
    positions = []

    for alias in SCHOOL_ALIASES[school]:
        match = re.search(
            rf"\b{re.escape(alias)}\b",
            text,
            re.I,
        )

        if match:
            positions.append(
                (
                    match.start(),
                    match.end(),
                    alias,
                )
            )

    return min(positions, key=lambda item: item[0]) if positions else None


def get_school_section(text, school):
    position = find_school_position(text, school)

    if not position:
        print(
            f"[WARNING] Could not find {school} section."
        )
        return ""

    start, end, alias = position
    boundaries = []

    for other_school in SCHOOL_ALIASES:
        if other_school == school:
            continue

        other_position = find_school_position(
            text[end:],
            other_school,
        )

        if other_position:
            boundaries.append(
                end + other_position[0]
            )

    for boundary in (
        "University Operations",
        "Higher Education",
    ):
        match = re.search(
            re.escape(boundary),
            text[end:],
            re.I,
        )

        if match:
            boundaries.append(
                end + match.start()
            )

    section_end = min(
        boundaries or [len(text)]
    )

    section = text[start:section_end].strip()

    print(
        f"[DEBUG] {school} matched alias: {alias}"
    )

    return section


# ---------------------------------------------------------------------------
# ATENEO STATUS CLASSIFICATION
# ---------------------------------------------------------------------------

def classify(text):
    if not text:
        return "Unknown"

    text = text.lower()

    asynchronous_patterns = (
        r"\basynchronous online\b",
        r"\bonline asynchronous\b",
        r"\basynchronous modality\b",
        r"\basynchronous classes?\b",
        r"\basynchronous period\b",
        r"\basynchronous instruction\b",
        r"\basynchronous learning\b",
        r"\basynchronous activities\b",
        r"\bshift(?:ing)? to asynchronous\b",
        r"\basync(?:hronous)? online\b",
    )

    synchronous_patterns = (
        r"\bsynchronous online\b",
        r"\bonline synchronous\b",
        r"\bsynchronous classes?\b",
        r"\bsynchronous session\b",
        r"\bsynchronous instruction\b",
        r"\bsynchronous modality\b",
        r"\bsynchronous learning\b",
        r"\bshift(?:ing)? to synchronous\b",
        r"\bsync(?:hronous)? online\b",
    )

    async_hits = [
        match
        for pattern in asynchronous_patterns
        if (match := re.search(pattern, text))
    ]

    sync_hits = [
        match
        for pattern in synchronous_patterns
        if (match := re.search(pattern, text))
    ]

    if async_hits and sync_hits:
        first_async = min(
            async_hits,
            key=lambda match: match.start(),
        )

        first_sync = min(
            sync_hits,
            key=lambda match: match.start(),
        )

        return (
            "Asynchronous Online"
            if first_async.start() < first_sync.start()
            else "Synchronous Online"
        )

    if async_hits:
        return "Asynchronous Online"

    if sync_hits:
        return "Synchronous Online"

    online_patterns = (
        r"\bonline classes\b",
        r"\bonline class\b",
        r"\bonline modality\b",
        r"\bonline instruction\b",
        r"\bvirtual classes\b",
        r"\bvirtual instruction\b",
        r"\bremote learning\b",
        r"\bremote classes\b",
        r"\bclasses will be conducted online\b",
        r"\bclasses remain online\b",
        r"\bshifting to online\b",
        r"\bshift to online\b",
    )

    if any(
        re.search(pattern, text)
        for pattern in online_patterns
    ):
        return "Online"

    suspension_patterns = (
        r"\bclasses are suspended\b",
        r"\bclasses have been suspended\b",
        r"\bclasses remain suspended\b",
        r"\bclass suspension is in effect\b",
        r"\ball classes are suspended\b",
        r"\bclasses are cancelled\b",
        r"\bclasses are canceled\b",
        r"\bno classes will be held\b",
        r"\bno classes today\b",
        r"\bwalang pasok\b",
    )

    if any(
        re.search(pattern, text)
        for pattern in suspension_patterns
    ):
        return "Suspension"

    onsite_patterns = (
        r"\bonsite classes\b",
        r"\bon-site classes\b",
        r"\bface-to-face classes\b",
        r"\bface to face classes\b",
        r"\bf2f classes\b",
        r"\bonsite instruction\b",
        r"\bclasses.*resume.*onsite\b",
        r"\bresume.*onsite classes\b",
    )

    if any(
        re.search(pattern, text)
        for pattern in onsite_patterns
    ):
        return "Onsite"

    return "Unknown"


def get_statuses(soup):
    text = get_page_text(soup)
    statuses = {}

    for school in ("AGS", "JHS", "SHS"):
        section = get_school_section(
            text,
            school,
        )

        statuses[school] = classify(section)

        print(
            f"[DEBUG] {school}: "
            f"{statuses[school]}"
        )

        print(
            f"[DEBUG] {school} section:"
        )

        print(section[:500])
        print("-" * 40)

    return statuses


def advisory_has_school_arrangements(soup):
    text = get_page_text(soup).lower()

    keywords = (
        "class arrangements",
        "classes",
        "onsite",
        "on-site",
        "face-to-face",
        "synchronous",
        "asynchronous",
        "online",
        "suspended",
        "no classes",
    )

    return any(
        keyword in text
        for keyword in keywords
    )


def get_recent_ateneo_advisory(today):
    """
    Returns the current Ateneo advisory soup and date if it looks
    relevant and is within the configured lookback window.
    """

    soup = fetch_advisories()

    advisory_date = find_class_arrangements_date(
        soup
    )

    print(
        f"[DEBUG] Ateneo advisory date: "
        f"{advisory_date}"
    )

    if not is_recent_advisory_date(
        advisory_date,
        today,
    ):
        print(
            "[DEBUG] Ateneo advisory is older than "
            f"{ADVISORY_LOOKBACK_DAYS} days."
        )

        return None, advisory_date

    if not advisory_has_school_arrangements(soup):
        print(
            "[WARNING] Ateneo advisory does not appear "
            "to contain class-arrangement information."
        )

        return None, advisory_date

    return soup, advisory_date


# ---------------------------------------------------------------------------
# QC FEED DISCOVERY
# ---------------------------------------------------------------------------

def same_official_domain(url):
    try:
        hostname = urlparse(url).hostname

        if not hostname:
            return False

        hostname = hostname.lower()

        return (
            hostname == "quezoncity.gov.ph"
            or hostname.endswith(".quezoncity.gov.ph")
        )

    except Exception:
        return False


def discover_qc_feed_urls():
    """
    Do not blindly trust the hard-coded feed.

    Start from the official QC pages, inspect <link rel="alternate">
    and <a> RSS/Atom links, and return only official QC feed URLs.
    """

    candidates = set()

    starting_urls = (
        QC_FEED_URL,
        QC_NEWS_URL,
        "https://quezoncity.gov.ph/",
    )

    for starting_url in starting_urls:
        try:
            soup = BeautifulSoup(
                fetch(starting_url, timeout=15).text,
                "html.parser",
            )

            for link in soup.find_all(
                "link",
                href=True,
            ):
                rel = " ".join(
                    link.get("rel", [])
                ).lower()

                link_type = (
                    link.get("type", "")
                    .lower()
                )

                href = urljoin(
                    starting_url,
                    link["href"],
                )

                if (
                    "alternate" in rel
                    and (
                        "rss" in link_type
                        or "atom" in link_type
                        or "feed" in href.lower()
                        or "rss" in href.lower()
                    )
                    and same_official_domain(href)
                ):
                    candidates.add(href)

            for anchor in soup.find_all(
                "a",
                href=True,
            ):
                text = anchor.get_text(
                    " ",
                    strip=True,
                ).lower()

                href = urljoin(
                    starting_url,
                    anchor["href"],
                )

                if (
                    same_official_domain(href)
                    and (
                        "rss" in text
                        or "feed" in text
                        or "atom" in text
                        or "rss" in href.lower()
                        or "feed" in href.lower()
                    )
                ):
                    candidates.add(href)

        except Exception as error:
            print(
                f"[WARNING] Could not inspect "
                f"QC feed source {starting_url}: {error}",
                file=sys.stderr,
            )

    # Keep the known official feed as a fallback,
    # but it is now verified rather than blindly trusted.
    candidates.add(QC_FEED_URL)

    print("[DEBUG] Discovered QC feed URLs:")

    for url in sorted(candidates):
        print(f"  {url}")

    return sorted(candidates)


# ---------------------------------------------------------------------------
# QC ANNOUNCEMENTS
# ---------------------------------------------------------------------------

def looks_like_qc_class_announcement(title, text):
    combined = (
        title + " " + text
    ).lower()

    return (
        (
            "walang pasok" in combined
            or "class suspension" in combined
            or "classes suspended" in combined
            or "face-to-face classes" in combined
        )
        and (
            "school" in combined
            or "classes" in combined
            or "paaralan" in combined
        )
    )


def analyze_qc_announcement(url, target_date):
    """
    Follow the actual announcement URL and inspect its body.

    This is important because the RSS item title alone can be
    misleading or omit the private-school wording.
    """

    if not same_official_domain(url):
        print(
            f"[DEBUG] Ignoring non-QC URL: {url}"
        )
        return None

    try:
        response = fetch(
            url,
            timeout=15,
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        text = get_page_text(soup)

        title = (
            soup.title.get_text(
                " ",
                strip=True,
            )
            if soup.title
            else ""
        )

        combined = (
            title + "\n" + text
        ).lower()

        announcement_dates = dates_in_window(
            combined,
            target_date - timedelta(
                days=QC_LOOKBACK_DAYS
            ),
            target_date + timedelta(days=1),
        )

        if not announcement_dates:
            return None

        private_school = any(
            phrase in combined
            for phrase in (
                "private schools",
                "private school",
                "pribadong paaralan",
                "pribadong school",
                "public and private schools",
                "pampubliko at pribadong paaralan",
            )
        )

        suspended = any(
            phrase in combined
            for phrase in (
                "suspended",
                "suspension",
                "suspendido",
                "walang pasok",
                "no classes",
                "classes suspended",
            )
        )

        alternative_delivery = any(
            phrase in combined
            for phrase in (
                "alternative delivery modes",
                "alternative delivery mode",
                "synchronous / asynchronous",
                "synchronous/asynchronous",
                "synchronous or asynchronous",
                "asynchronous / synchronous",
            )
        )

        if not looks_like_qc_class_announcement(
            title,
            text,
        ):
            return None

        return {
            "url": url,
            "title": title,
            "date": max(announcement_dates),
            "private_school": private_school,
            "suspended": suspended,
            "alternative_delivery": alternative_delivery,
            "text": text,
        }

    except Exception as error:
        print(
            f"[WARNING] QC announcement check failed "
            f"for {url}: {error}",
            file=sys.stderr,
        )

        return None


def check_qc_government_feed(target_date):
    """
    Discover the RSS/Atom feed, parse its entries, THEN follow
    the actual official QC announcement URL.

    We do not trust the feed entry by itself.
    """

    feed_urls = discover_qc_feed_urls()

    announcements = []

    for feed_url in feed_urls:
        try:
            response = fetch(
                feed_url,
                timeout=15,
            )

            parsed = feedparser.parse(
                response.content
            )

            if not parsed.entries:
                print(
                    f"[DEBUG] No entries in QC feed: "
                    f"{feed_url}"
                )
                continue

            print(
                f"[DEBUG] Checking {len(parsed.entries)} "
                f"entries from {feed_url}"
            )

            for entry in parsed.entries:
                title = entry.get(
                    "title",
                    "",
                )

                summary = entry.get(
                    "summary",
                    "",
                )

                link = entry.get(
                    "link",
                    "",
                )

                if not link:
                    continue

                link = urljoin(
                    feed_url,
                    link,
                )

                if not same_official_domain(link):
                    continue

                quick_text = (
                    title + " " + summary
                ).lower()

                if not any(
                    phrase in quick_text
                    for phrase in (
                        "walang pasok",
                        "class suspension",
                        "classes suspended",
                        "face-to-face classes",
                        "school",
                    )
                ):
                    continue

                result = analyze_qc_announcement(
                    link,
                    target_date,
                )

                if result:
                    announcements.append(result)

        except Exception as error:
            print(
                f"[WARNING] QC feed failed "
                f"{feed_url}: {error}",
                file=sys.stderr,
            )

    if not announcements:
        return {
            "private_suspended": False,
            "alternative_delivery": False,
            "reason": "No recent matching QC announcement.",
            "announcement": None,
        }

    # Newest announcement wins.
    announcements.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    newest = announcements[0]

    print(
        "[DEBUG] Newest QC announcement:"
    )
    print(
        f"  {newest['date']} "
        f"{newest['title']}"
    )
    print(
        f"  private={newest['private_school']}"
    )
    print(
        f"  suspended={newest['suspended']}"
    )
    print(
        f"  alternative_delivery="
        f"{newest['alternative_delivery']}"
    )
    print(
        f"  URL={newest['url']}"
    )

    return {
        "private_suspended": (
            newest["private_school"]
            and newest["suspended"]
        ),
        "alternative_delivery": (
            newest["alternative_delivery"]
        ),
        "reason": (
            "QC private-school suspension: "
            + newest["title"]
        ),
        "announcement": newest,
    }


# ---------------------------------------------------------------------------
# PAGASA
# ---------------------------------------------------------------------------

def check_pagasa_bulletin(target_date):
    """
    Check PAGASA's NCR-specific warning page.

    The old implementation searched the generic /weather page for
    the words "orange" or "red". That can produce false positives
    because the page can contain historical/UI text.

    This instead looks for an actual current NCR rainfall warning
    and verifies that Metro Manila / NCR is named.
    """

    try:
        response = fetch(
            PAGASA_NCR_URL,
            timeout=15,
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        text = get_page_text(soup)

        lower = text.lower()

        if not any(
            phrase in lower
            for phrase in (
                "heavy rainfall warning",
                "rainfall warning",
                "rainfall advisory",
            )
        ):
            return (
                False,
                "No active PAGASA rainfall warning found.",
            )

        # Make sure this is actually an NCR bulletin.
        if not any(
            phrase in lower
            for phrase in (
                "metro manila",
                "national capital region",
                "ncr",
            )
        ):
            return (
                False,
                "PAGASA bulletin is not for NCR.",
            )

        # The automatic-suspension concern is specifically
        # Orange/Red, not merely the presence of rain.
        if "red warning level" in lower:
            return (
                True,
                "PAGASA Red Heavy Rainfall Warning for NCR.",
            )

        if "orange warning level" in lower:
            return (
                True,
                "PAGASA Orange Heavy Rainfall Warning for NCR.",
            )

        # Don't treat Yellow as an automatic trigger.
        if "yellow warning level" in lower:
            return (
                False,
                "PAGASA Yellow Heavy Rainfall Warning only.",
            )

        return (
            False,
            "PAGASA rainfall warning found, "
            "but no Orange/Red warning level.",
        )

    except Exception as error:
        print(
            f"PAGASA check failed: {error}",
            file=sys.stderr,
        )

        return (
            False,
            "PAGASA check failed.",
        )


# ---------------------------------------------------------------------------
# FACEBOOK
# ---------------------------------------------------------------------------

def check_facebook(target_date):
    cutoff = (
        target_date
        - timedelta(days=FACEBOOK_LOOKBACK_DAYS)
    )

    try:
        response = SESSION.get(
            FACEBOOK_URL,
            timeout=20,
        )

        if response.status_code != 200:
            print(
                f"Facebook returned HTTP "
                f"{response.status_code}"
            )
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        raw = soup.get_text(
            " ",
            strip=True,
        ).lower()

        if "login" in raw and len(raw) < 5000:
            print(
                "Facebook returned a login page."
            )
            return None

        for tag in soup(
            ["script", "style", "noscript"]
        ):
            tag.decompose()

        content = soup.get_text(
            "\n",
            strip=True,
        )

        lower = content.lower()

        private = (
            "private schools",
            "private school",
            "pribadong paaralan",
        )

        suspension = (
            "suspended",
            "suspension",
            "suspendido",
            "walang pasok",
            "no classes",
        )

        if not any(
            value in lower
            for value in private
        ):
            return None

        if not any(
            value in lower
            for value in suspension
        ):
            return None

        dates = [
            value
            for value in parse_date_from_text(
                content
            )
            if cutoff <= value <= target_date
        ]

        if dates:
            return {
                "private_suspended": True,
                "date": max(dates),
                "reason": (
                    "Facebook private-school "
                    "suspension detected."
                ),
            }

    except Exception as error:
        print(
            f"Facebook check failed: {error}",
            file=sys.stderr,
        )

    return None


# ---------------------------------------------------------------------------
# STATUS OUTPUT
# ---------------------------------------------------------------------------

def status_icon(status):
    return {
        "Synchronous Online": "🟢",
        "Asynchronous Online": "🟢",
        "Mixed Online": "🟢",
        "Online": "🟢",
        "Suspension": "🔴",
        "No School": "❌",
        "Onsite": "🔵",
        "Unknown": "🟡",
    }.get(status, "🟡")


def create_message(
    date,
    statuses,
    reason=None,
    reason_type=None,
):
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
    ]

    for school in ("AGS", "JHS", "SHS"):
        lines.append(
            f"*{school}* | "
            f"{status_icon(statuses[school])} "
            f"{statuses[school]} | 🟡 Unknown"
        )

    if reason:
        if reason_type == "calendar":
            lines.extend(
                [
                    "",
                    "🚨 *NO CLASSES.*",
                    reason,
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "🚨 *PRIVATE-SCHOOL SUSPENSION.*",
                    reason,
                ]
            )

    lines.extend(
        [
            "",
            f"🔗 {ADVISORIES_URL}",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GOOGLE CHAT
# ---------------------------------------------------------------------------

def send_to_google_chat(message):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "GOOGLE_CHAT_WEBHOOK secret is not set."
        )

    SESSION.post(
        WEBHOOK_URL,
        json={"text": message},
        timeout=30,
    ).raise_for_status()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def check_once():
    today = get_ph_date()

    print(
        f"[DEBUG] Philippine date: {today}"
    )

    # ---------------------------------------------------------------
    # 1. Philippine calendar
    # ---------------------------------------------------------------

    calendar_no_classes, calendar_reason = (
        check_ph_calendar(today)
    )

    if calendar_no_classes:
        statuses = {
            school: "No School"
            for school in ("AGS", "JHS", "SHS")
        }

        send_to_google_chat(
            create_message(
                today,
                statuses,
                calendar_reason,
                "calendar",
            )
        )

        return

    # ---------------------------------------------------------------
    # 2. QC government announcements
    # ---------------------------------------------------------------

    qc_result = check_qc_government_feed(
        today
    )

    # ---------------------------------------------------------------
    # 3. PAGASA
    # ---------------------------------------------------------------

    pagasa_trigger, pagasa_reason = (
        check_pagasa_bulletin(today)
    )

    print(
        f"[DEBUG] PAGASA trigger: "
        f"{pagasa_trigger}"
    )

    print(
        f"[DEBUG] PAGASA reason: "
        f"{pagasa_reason}"
    )

    # ---------------------------------------------------------------
    # 4. Ateneo advisory
    #
    # We DON'T require advisory_date == today anymore.
    # A recent advisory can still be authoritative.
    # ---------------------------------------------------------------

    ateneo_soup = None
    ateneo_date = None

    try:
        (
            ateneo_soup,
            ateneo_date,
        ) = get_recent_ateneo_advisory(today)

    except Exception as error:
        print(
            f"[WARNING] Ateneo advisory check failed: "
            f"{error}",
            file=sys.stderr,
        )

    # ---------------------------------------------------------------
    # 5. Facebook fallback
    # ---------------------------------------------------------------

    facebook_result = check_facebook(
        today
    )

    # ---------------------------------------------------------------
    # 6. Determine whether a private-school suspension
    #    is independently confirmed.
    # ---------------------------------------------------------------

    private_suspended = (
        qc_result["private_suspended"]
        or bool(facebook_result)
    )

    # ---------------------------------------------------------------
    # 7. If QC/PAGASA indicates a weather event and the
    #    Ateneo advisory is recent, trust Ateneo's actual
    #    school-specific arrangement over generic assumptions.
    # ---------------------------------------------------------------

    statuses = {
        school: "Onsite"
        for school in ("AGS", "JHS", "SHS")
    }

    if ateneo_soup is not None:
        statuses = get_statuses(
            ateneo_soup
        )

    # ---------------------------------------------------------------
    # 8. Strong private-school suspension signal
    # ---------------------------------------------------------------

    reason = None
    reason_type = None

    if private_suspended:
        statuses = {
            school: "No School"
            for school in ("AGS", "JHS", "SHS")
        }

        if qc_result["private_suspended"]:
            reason = qc_result["reason"]

        elif facebook_result:
            reason = facebook_result["reason"]

        reason_type = "suspension"

    # ---------------------------------------------------------------
    # 9. Alternative delivery / weather trigger
    #
    # Important:
    # QC saying "Alternative Delivery Modes" does NOT itself
    # mean Ateneo is suspended.
    #
    # It DOES mean we should make sure we're using a recent
    # Ateneo advisory instead of falling back to "Onsite".
    # ---------------------------------------------------------------

    elif (
        qc_result["alternative_delivery"]
        or pagasa_trigger
    ):
        if ateneo_soup is not None:
            print(
                "[DEBUG] Weather/alternative-delivery "
                "trigger detected; using recent Ateneo "
                "class-arrangement advisory."
            )

            statuses = get_statuses(
                ateneo_soup
            )

        else:
            print(
                "[WARNING] Weather/alternative-delivery "
                "trigger detected but no recent Ateneo "
                "advisory was found."
            )

            statuses = {
                school: "Unknown"
                for school in ("AGS", "JHS", "SHS")
            }

    # ---------------------------------------------------------------
    # 10. Send
    # ---------------------------------------------------------------

    send_to_google_chat(
        create_message(
            today,
            statuses,
            reason,
            reason_type,
        )
    )


if __name__ == "__main__":
    try:
        check_once()

    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )

        sys.exit(1)
