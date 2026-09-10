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
PAGASA_NCR_URL = (
    "https://bagong.pagasa.dost.gov.ph/"
    "regional-forecast/ncrprsd"
)

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


# ============================================================
# HTTP
# ============================================================

def fetch(url, timeout=30, **kwargs):
    response = SESSION.get(
        url,
        timeout=timeout,
        **kwargs,
    )

    response.raise_for_status()

    return response


# ============================================================
# DATE HELPERS
# ============================================================

def get_ph_date():
    return datetime.datetime.now(
        PH_TIMEZONE
    ).date()


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
    }.get(
        value.lower().strip()
    )


def parse_single_date(day, month, year):
    month = normalize_month(month)

    if not month:
        return None

    for fmt in (
        "%d %b %Y",
        "%d %B %Y",
    ):
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
        rf"\b({MONTH_PATTERN})\s+"
        rf"(\d{{1,2}}),?\s+(\d{{4}})\b",

        rf"\b(\d{{1,2}})\s+"
        rf"({MONTH_PATTERN})\s+(\d{{4}})\b",
    )

    dates = []

    for index, pattern in enumerate(patterns):
        for match in re.finditer(
            pattern,
            text,
            re.I,
        ):
            a, b, c = match.groups()

            if index == 0:
                value = parse_single_date(
                    b,
                    a,
                    c,
                )
            else:
                value = parse_single_date(
                    a,
                    b,
                    c,
                )

            if value:
                dates.append(value)

    return dates


def dates_in_window(
    text,
    start_date,
    end_date,
):
    return [
        value
        for value in parse_date_from_text(text)
        if start_date <= value <= end_date
    ]


# ============================================================
# PHILIPPINE CALENDAR
# ============================================================

def check_ph_calendar(value):
    if value.weekday() >= 5:
        return True, "Weekend"

    fixed_special_days = {
        (8, 21): "Ninoy Aquino Day",
        (11, 1): "All Saints' Day",
        (12, 8): (
            "Feast of the Immaculate Conception"
        ),
        (12, 24): "Christmas Eve",
        (12, 31): "Last Day of the Year",
    }

    if (
        value.month,
        value.day,
    ) in fixed_special_days:
        return (
            True,
            "Philippine special non-working day: "
            + fixed_special_days[
                (
                    value.month,
                    value.day,
                )
            ],
        )

    holidays_for_year = holidays.country_holidays(
        "PH",
        years=value.year,
    )

    if value in holidays_for_year:
        return (
            True,
            f"Philippine holiday: "
            f"{holidays_for_year.get(value)}",
        )

    return False, None


# ============================================================
# GENERIC HTML
# ============================================================

def get_page_text(soup):
    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
        ]
    ):
        element.decompose()

    return soup.get_text(
        "\n",
        strip=True,
    )


# ============================================================
# ATENEO
# ============================================================

def fetch_advisories():
    return BeautifulSoup(
        fetch(
            ADVISORIES_URL
        ).text,
        "html.parser",
    )


def find_class_arrangements_date(soup):
    text = get_page_text(soup)

    # Try to specifically associate
    # Class Arrangements with Last Updated.
    match = re.search(
        r"Class Arrangements.{0,1500}?"
        r"Last Updated on.{0,150}?"
        rf"(\d{{1,2}})\s+"
        rf"({MONTH_PATTERN})\s+"
        rf"(\d{{4}})",
        text,
        re.I | re.S,
    )

    if match:
        value = parse_single_date(
            *match.groups()
        )

        if value:
            return value

    # Fallback to newest Last Updated date.
    values = [
        parse_single_date(*groups)
        for groups in re.findall(
            r"Last Updated on.{0,150}?"
            rf"(\d{{1,2}})\s+"
            rf"({MONTH_PATTERN})\s+"
            rf"(\d{{4}})",
            text,
            re.I | re.S,
        )
    ]

    values = [
        value
        for value in values
        if value
    ]

    if values:
        print(
            "[WARNING] Could not specifically identify "
            "Class Arrangements update date."
        )

        print(
            "[WARNING] Using newest "
            "'Last Updated' date."
        )

        return max(values)

    raise RuntimeError(
        "Could not find an Ateneo "
        "Class Arrangements update date."
    )


def is_recent_advisory_date(
    advisory_date,
    today,
):
    minimum = (
        today
        - timedelta(
            days=ADVISORY_LOOKBACK_DAYS
        )
    )

    return (
        minimum
        <= advisory_date
        <= today
    )


def find_school_position(
    text,
    school,
):
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

    return (
        min(
            positions,
            key=lambda item: item[0],
        )
        if positions
        else None
    )


def get_school_section(
    text,
    school,
):
    position = find_school_position(
        text,
        school,
    )

    if not position:
        print(
            f"[WARNING] Could not find "
            f"{school} section."
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

    section = text[
        start:section_end
    ].strip()

    print(
        f"[DEBUG] {school} matched alias: "
        f"{alias}"
    )

    return section


# ============================================================
# ATENEO STATUS CLASSIFICATION
# ============================================================

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
        if (
            match := re.search(
                pattern,
                text,
            )
        )
    ]

    sync_hits = [
        match
        for pattern in synchronous_patterns
        if (
            match := re.search(
                pattern,
                text,
            )
        )
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
            if first_async.start()
            < first_sync.start()
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
        re.search(
            pattern,
            text,
        )
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
        re.search(
            pattern,
            text,
        )
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
        re.search(
            pattern,
            text,
        )
        for pattern in onsite_patterns
    ):
        return "Onsite"

    return "Unknown"


def get_statuses(soup):
    text = get_page_text(soup)

    statuses = {}

    for school in (
        "AGS",
        "JHS",
        "SHS",
    ):
        section = get_school_section(
            text,
            school,
        )

        statuses[school] = classify(
            section
        )

        print(
            f"[DEBUG] {school}: "
            f"{statuses[school]}"
        )

        print(
            f"[DEBUG] {school} section:"
        )

        print(
            section[:500]
        )

        print("-" * 40)

    return statuses


def advisory_has_school_arrangements(
    soup,
):
    text = get_page_text(
        soup
    ).lower()

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


def get_recent_ateneo_advisory(
    today,
):
    soup = fetch_advisories()

    advisory_date = (
        find_class_arrangements_date(
            soup
        )
    )

    print(
        "[DEBUG] Ateneo advisory date: "
        f"{advisory_date}"
    )

    if not is_recent_advisory_date(
        advisory_date,
        today,
    ):
        print(
            "[DEBUG] Ateneo advisory is older "
            f"than {ADVISORY_LOOKBACK_DAYS} days."
        )

        return None, advisory_date

    if not advisory_has_school_arrangements(
        soup
    ):
        print(
            "[WARNING] Ateneo advisory does not "
            "appear to contain class-arrangement "
            "information."
        )

        return None, advisory_date

    return soup, advisory_date


# ============================================================
# QC FEED DISCOVERY
# ============================================================

def same_official_domain(url):
    try:
        hostname = urlparse(
            url
        ).hostname

        if not hostname:
            return False

        hostname = hostname.lower()

        return (
            hostname == "quezoncity.gov.ph"
            or hostname.endswith(
                ".quezoncity.gov.ph"
            )
        )

    except Exception:
        return False


def discover_qc_feed_urls():
    """
    Discover RSS/Atom feeds from official QC pages.

    The known feed URL is retained as a fallback,
    but actual entries are still followed and verified.
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
                fetch(
                    starting_url,
                    timeout=15,
                ).text,
                "html.parser",
            )

            for link in soup.find_all(
                "link",
                href=True,
            ):
                rel = " ".join(
                    link.get(
                        "rel",
                        [],
                    )
                ).lower()

                link_type = (
                    link.get(
                        "type",
                        "",
                    ).lower()
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
                    and same_official_domain(
                        href
                    )
                ):
                    candidates.add(
                        href
                    )

            for anchor in soup.find_all(
                "a",
                href=True,
            ):
                anchor_text = anchor.get_text(
                    " ",
                    strip=True,
                ).lower()

                href = urljoin(
                    starting_url,
                    anchor["href"],
                )

                if (
                    same_official_domain(
                        href
                    )
                    and (
                        "rss" in anchor_text
                        or "feed" in anchor_text
                        or "atom" in anchor_text
                        or "rss" in href.lower()
                        or "feed" in href.lower()
                    )
                ):
                    candidates.add(
                        href
                    )

        except Exception as error:
            print(
                "[WARNING] Could not inspect "
                f"QC source {starting_url}: "
                f"{error}",
                file=sys.stderr,
            )

    candidates.add(
        QC_FEED_URL
    )

    print(
        "[DEBUG] Discovered QC feed URLs:"
    )

    for url in sorted(candidates):
        print(
            f"  {url}"
        )

    return sorted(
        candidates
    )


# ============================================================
# QC ANNOUNCEMENTS
# ============================================================

def looks_like_qc_class_announcement(
    title,
    text,
):
    combined = (
        title
        + " "
        + text
    ).lower()

    return (
        (
            "walang pasok" in combined
            or "class suspension" in combined
            or "classes suspended" in combined
            or "face-to-face classes" in combined
            or "alternative delivery" in combined
        )
        and (
            "school" in combined
            or "classes" in combined
            or "paaralan" in combined
        )
    )


def analyze_qc_announcement(
    url,
    target_date,
):
    """
    Follow the actual official QC announcement.

    The RSS entry itself is NOT considered authoritative.
    """

    if not same_official_domain(
        url
    ):
        print(
            "[DEBUG] Ignoring non-QC URL: "
            f"{url}"
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

        text = get_page_text(
            soup
        )

        title = (
            soup.title.get_text(
                " ",
                strip=True,
            )
            if soup.title
            else ""
        )

        combined = (
            title
            + "\n"
            + text
        ).lower()

        announcement_dates = dates_in_window(
            combined,
            target_date
            - timedelta(
                days=QC_LOOKBACK_DAYS
            ),
            target_date
            + timedelta(days=1),
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
                "alternative delivery",
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
            "date": max(
                announcement_dates
            ),
            "private_school": private_school,
            "suspended": suspended,
            "alternative_delivery": (
                alternative_delivery
            ),
            "text": text,
        }

    except Exception as error:
        print(
            "[WARNING] QC announcement check "
            f"failed for {url}: {error}",
            file=sys.stderr,
        )

        return None


def check_qc_government_feed(
    target_date,
):
    """
    Discover QC's feed, inspect its entries,
    then follow each relevant official announcement.

    The actual announcement body is what determines
    private-school suspension and alternative delivery.
    """

    feed_urls = (
        discover_qc_feed_urls()
    )

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
                    "[DEBUG] No entries in QC feed: "
                    f"{feed_url}"
                )

                continue

            print(
                f"[DEBUG] Checking "
                f"{len(parsed.entries)} "
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

                if not same_official_domain(
                    link
                ):
                    continue

                quick_text = (
                    title
                    + " "
                    + summary
                ).lower()

                if not any(
                    phrase in quick_text
                    for phrase in (
                        "walang pasok",
                        "class suspension",
                        "classes suspended",
                        "face-to-face classes",
                        "alternative delivery",
                        "school",
                    )
                ):
                    continue

                result = analyze_qc_announcement(
                    link,
                    target_date,
                )

                if result:
                    announcements.append(
                        result
                    )

        except Exception as error:
            print(
                "[WARNING] QC feed failed "
                f"{feed_url}: {error}",
                file=sys.stderr,
            )

    if not announcements:
        return {
            "private_suspended": False,
            "alternative_delivery": False,
            "reason": (
                "No recent matching "
                "QC announcement."
            ),
            "announcement": None,
        }

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
        f"  private="
        f"{newest['private_school']}"
    )

    print(
        f"  suspended="
        f"{newest['suspended']}"
    )

    print(
        "  alternative_delivery="
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


# ============================================================
# PAGASA
# ============================================================

def check_pagasa_bulletin(
    target_date,
):
    """
    Check PAGASA's NCR-specific page.

    Orange/Red triggers additional scrutiny, but do NOT
    directly override an explicit Ateneo advisory.
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

        text = get_page_text(
            soup
        )

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
                "No active PAGASA rainfall "
                "warning found.",
            )

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

        if "red warning level" in lower:
            return (
                True,
                "PAGASA Red Heavy Rainfall "
                "Warning for NCR.",
            )

        if "orange warning level" in lower:
            return (
                True,
                "PAGASA Orange Heavy Rainfall "
                "Warning for NCR.",
            )

        if "yellow warning level" in lower:
            return (
                False,
                "PAGASA Yellow Heavy Rainfall "
                "Warning only.",
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


# ============================================================
# FACEBOOK
# ============================================================

def check_facebook(
    target_date,
):
    cutoff = (
        target_date
        - timedelta(
            days=FACEBOOK_LOOKBACK_DAYS
        )
    )

    try:
        response = SESSION.get(
            FACEBOOK_URL,
            timeout=20,
        )

        if response.status_code != 200:
            print(
                "Facebook returned HTTP "
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

        if (
            "login" in raw
            and len(raw) < 5000
        ):
            print(
                "Facebook returned a login page."
            )

            return None

        for tag in soup(
            [
                "script",
                "style",
                "noscript",
            ]
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
            if cutoff
            <= value
            <= target_date
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


# ============================================================
# STATUS OUTPUT
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
        "Unknown": "🟡",
    }.get(
        status,
        "🟡",
    )


def create_message(
    date,
    statuses,
    reason=None,
    reason_type=None,
):
    next_date = (
        date
        + timedelta(days=1)
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
    ]

    for school in (
        "AGS",
        "JHS",
        "SHS",
    ):
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


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_to_google_chat(
    message,
):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "GOOGLE_CHAT_WEBHOOK secret "
            "is not set."
        )

    SESSION.post(
        WEBHOOK_URL,
        json={
            "text": message,
        },
        timeout=30,
    ).raise_for_status()


# ============================================================
# MAIN DECISION ENGINE
# ============================================================

def check_once():
    today = get_ph_date()

    print(
        f"[DEBUG] Philippine date: {today}"
    )

    # --------------------------------------------------------
    # 1. Philippine calendar
    # --------------------------------------------------------

    (
        calendar_no_classes,
        calendar_reason,
    ) = check_ph_calendar(
        today
    )

    if calendar_no_classes:
        statuses = {
            school: "No School"
            for school in (
                "AGS",
                "JHS",
                "SHS",
            )
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

    # --------------------------------------------------------
    # 2. QC government announcements
    # --------------------------------------------------------

    qc_result = (
        check_qc_government_feed(
            today
        )
    )

    # --------------------------------------------------------
    # 3. PAGASA
    # --------------------------------------------------------

    (
        pagasa_trigger,
        pagasa_reason,
    ) = check_pagasa_bulletin(
        today
    )

    print(
        "[DEBUG] PAGASA trigger: "
        f"{pagasa_trigger}"
    )

    print(
        "[DEBUG] PAGASA reason: "
        f"{pagasa_reason}"
    )

    # --------------------------------------------------------
    # 4. Recent Ateneo advisory
    #
    # IMPORTANT:
    # We no longer require advisory_date == today.
    # Anything within the previous 7 days is considered.
    # --------------------------------------------------------

    ateneo_soup = None
    ateneo_date = None

    try:
        (
            ateneo_soup,
            ateneo_date,
        ) = get_recent_ateneo_advisory(
            today
        )

    except Exception as error:
        print(
            "[WARNING] Ateneo advisory check "
            f"failed: {error}",
            file=sys.stderr,
        )

    # --------------------------------------------------------
    # 5. Facebook fallback
    # --------------------------------------------------------

    facebook_result = check_facebook(
        today
    )

    # --------------------------------------------------------
    # DEBUG
    # --------------------------------------------------------

    print(
        "========== DECISION DEBUG =========="
    )

    print(
        "[DEBUG] QC private suspended: "
        f"{qc_result['private_suspended']}"
    )

    print(
        "[DEBUG] QC alternative delivery: "
        f"{qc_result['alternative_delivery']}"
    )

    print(
        "[DEBUG] QC reason: "
        f"{qc_result['reason']}"
    )

    if qc_result["announcement"]:
        announcement = (
            qc_result["announcement"]
        )

        print(
            "[DEBUG] QC announcement title: "
            f"{announcement['title']}"
        )

        print(
            "[DEBUG] QC announcement date: "
            f"{announcement['date']}"
        )

        print(
            "[DEBUG] QC announcement URL: "
            f"{announcement['url']}"
        )

    print(
        "[DEBUG] Facebook suspension: "
        f"{bool(facebook_result)}"
    )

    print(
        "[DEBUG] Ateneo advisory date: "
        f"{ateneo_date}"
    )

    print(
        "[DEBUG] Ateneo recent: "
        f"{ateneo_soup is not None}"
    )

    print(
        "[DEBUG] PAGASA trigger: "
        f"{pagasa_trigger}"
    )

    print(
        "===================================="
    )

    # --------------------------------------------------------
    # 6. Get Facebook/QC suspension signals
    # --------------------------------------------------------

    private_suspended = (
        qc_result["private_suspended"]
        or bool(facebook_result)
    )

    # --------------------------------------------------------
    # 7. Default state
    # --------------------------------------------------------

    statuses = {
        school: "Onsite"
        for school in (
            "AGS",
            "JHS",
            "SHS",
        )
    }

    reason = None
    reason_type = None

    # --------------------------------------------------------
    # 8. CRITICAL PRECEDENCE
    #
    # Alternative Delivery Mode OVERRIDES a generic
    # private-school suspension signal.
    #
    # Example:
    #
    # QC:
    #   private schools suspended
    #   alternative delivery modes
    #
    # Ateneo:
    #   synchronous online
    #
    # RESULT:
    #   synchronous online
    #
    # But:
    #
    # QC:
    #   private schools suspended
    #   NO alternative delivery
    #
    # RESULT:
    #   No School
    # --------------------------------------------------------

    if (
        private_suspended
        and not qc_result[
            "alternative_delivery"
        ]
    ):
        statuses = {
            school: "No School"
            for school in (
                "AGS",
                "JHS",
                "SHS",
            )
        }

        if qc_result[
            "private_suspended"
        ]:
            reason = qc_result[
                "reason"
            ]

        elif facebook_result:
            reason = facebook_result[
                "reason"
            ]

        reason_type = "suspension"

        print(
            "[DEBUG] Decision: "
            "PRIVATE-SCHOOL SUSPENSION"
        )

    # --------------------------------------------------------
    # 9. Alternative delivery / PAGASA
    #
    # If either source indicates a weather-related event,
    # use the recent Ateneo advisory.
    # --------------------------------------------------------

    elif (
        qc_result[
            "alternative_delivery"
        ]
        or pagasa_trigger
    ):
        if ateneo_soup is not None:
            print(
                "[DEBUG] Decision: "
                "RECENT ATENEO ADVISORY "
                "OVERRIDES GENERIC "
                "SUSPENSION SIGNAL"
            )

            statuses = get_statuses(
                ateneo_soup
            )

        else:
            print(
                "[WARNING] Weather/alternative "
                "delivery trigger detected, "
                "but no recent Ateneo advisory "
                "was found."
            )

            statuses = {
                school: "Unknown"
                for school in (
                    "AGS",
                    "JHS",
                    "SHS",
                )
            }

    # --------------------------------------------------------
    # 10. Normal case
    #
    # If Ateneo has a recent advisory, use it.
    # --------------------------------------------------------

    elif ateneo_soup is not None:
        print(
            "[DEBUG] Decision: "
            "RECENT ATENEO ADVISORY"
        )

        statuses = get_statuses(
            ateneo_soup
        )

    # --------------------------------------------------------
    # 11. No useful advisory
    # --------------------------------------------------------

    else:
        print(
            "[DEBUG] Decision: "
            "NO RECENT ATENEO ADVISORY; "
            "DEFAULTING TO ONSITE"
        )

    # --------------------------------------------------------
    # 12. Final debug
    # --------------------------------------------------------

    print(
        "========== FINAL STATUS =========="
    )

    for school in (
        "AGS",
        "JHS",
        "SHS",
    ):
        print(
            f"[DEBUG] {school}: "
            f"{statuses[school]}"
        )

    print(
        "=================================="
    )

    # --------------------------------------------------------
    # 13. Send
    # --------------------------------------------------------

    send_to_google_chat(
        create_message(
            today,
            statuses,
            reason,
            reason_type,
        )
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        check_once()

    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )

        sys.exit(1)
