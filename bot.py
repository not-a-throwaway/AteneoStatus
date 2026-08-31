import os
import re
import sys
import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests
import holidays
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

ADVISORIES_URL = "https://www.ateneo.edu/advisories"
FACEBOOK_URL = "https://www.facebook.com/ateneodemanila/"

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

FACEBOOK_LOOKBACK_DAYS = 14

PH_TIMEZONE = ZoneInfo("Asia/Manila")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
})


def fetch(url, timeout=30):
    """
    Fetch a URL and raise an exception for HTTP errors.
    """

    response = SESSION.get(
        url,
        timeout=timeout,
    )

    response.raise_for_status()

    return response


# ============================================================
# DATE HELPERS
# ============================================================

MONTH_PATTERN = (
    r"Jan(?:uary)?|"
    r"Feb(?:ruary)?|"
    r"Mar(?:ch)?|"
    r"Apr(?:il)?|"
    r"May|"
    r"Jun(?:e)?|"
    r"Jul(?:y)?|"
    r"Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|"
    r"Nov(?:ember)?|"
    r"Dec(?:ember)?"
)


def get_ph_date():
    """
    Return today's date in Philippine time.
    """

    return datetime.datetime.now(
        PH_TIMEZONE
    ).date()


def format_date(date):
    """
    Example:

    September 1
    """

    return (
        date.strftime("%B ")
        + str(date.day)
    )


def normalize_month(month):
    """
    Normalize month abbreviations.

    Examples:

    Sept -> Sep
    September -> September
    """

    month = month.strip().lower()

    aliases = {
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
    }

    return aliases.get(month)


def parse_single_date(day, month, year):
    """
    Parse a date with either abbreviated or full month names.
    """

    normalized_month = normalize_month(month)

    if not normalized_month:
        return None

    value = (
        f"{day} "
        f"{normalized_month} "
        f"{year}"
    )

    for fmt in (
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.datetime.strptime(
                value,
                fmt
            ).date()

        except ValueError:
            pass

    return None


def parse_date_from_text(text):
    """
    Find dates like:

    September 1, 2026
    Sept 1, 2026
    Sep 1 2026

    1 September 2026
    1 Sept 2026
    1 Sep 2026
    """

    patterns = [

        # September 1, 2026
        # Sept 1 2026
        (
            rf"\b"
            rf"({MONTH_PATTERN})"
            rf"\s+"
            rf"(\d{{1,2}})"
            rf",?"
            rf"\s+"
            rf"(\d{{4}})"
            rf"\b"
        ),

        # 1 September 2026
        # 1 Sept 2026
        (
            rf"\b"
            rf"(\d{{1,2}})"
            rf"\s+"
            rf"({MONTH_PATTERN})"
            rf"\s+"
            rf"(\d{{4}})"
            rf"\b"
        ),
    ]

    dates = []

    for index, pattern in enumerate(patterns):

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE
        ):

            parts = match.groups()

            if index == 0:

                month, day, year = parts

            else:

                day, month, year = parts

            parsed = parse_single_date(
                day,
                month,
                year
            )

            if parsed:
                dates.append(parsed)

    return dates


# ============================================================
# PHILIPPINE CALENDAR
# ============================================================

def check_ph_calendar(target_date):
    """
    Check weekends and Philippine holidays.
    """

    # Saturday = 5
    # Sunday = 6

    if target_date.weekday() >= 5:
        return (
            True,
            "Weekend"
        )

    # Extra special non-working days.

    recurring_special_days = {

        (8, 21):
            "Ninoy Aquino Day",

        (11, 1):
            "All Saints' Day",

        (12, 8):
            "Feast of the Immaculate Conception",

        (12, 24):
            "Christmas Eve",

        (12, 31):
            "Last Day of the Year",
    }

    key = (
        target_date.month,
        target_date.day
    )

    if key in recurring_special_days:

        return (
            True,
            "Philippine special non-working day: "
            + recurring_special_days[key]
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
# ATENEO ADVISORIES
# ============================================================

def fetch_advisories():
    """
    Fetch the Ateneo advisories page.
    """

    response = fetch(
        ADVISORIES_URL
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    return soup


def get_page_text(soup):
    """
    Extract reasonably clean page text.
    """

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
    ]):
        tag.decompose()

    return soup.get_text(
        "\n",
        strip=True
    )


def find_class_arrangements_date(soup):
    """
    Find the date belonging specifically to:

    Class Arrangements

    Example:

    Class Arrangements

    Last Updated on 6:24 pm 1 Sept 2026

    We intentionally do NOT simply take max(all dates),
    because the page may contain dates from announcements
    or other sections.
    """

    text = get_page_text(soup)

    match = re.search(
        r"Class Arrangements"
        r".{0,1000}?"
        r"Last Updated on"
        r".{0,100}?"
        r"(\d{1,2})"
        r"\s+"
        rf"({MONTH_PATTERN})"
        r"\s+"
        r"(\d{4})",

        text,

        re.IGNORECASE
        | re.DOTALL
    )

    if match:

        day, month, year = match.groups()

        parsed = parse_single_date(
            day,
            month,
            year
        )

        if parsed:
            return parsed

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------
    #
    # Look for "Last Updated on" followed by a date.
    #
    # This is less specific, but better than crashing.

    matches = re.findall(
        r"Last Updated on"
        r".{0,100}?"
        r"(\d{1,2})"
        r"\s+"
        rf"({MONTH_PATTERN})"
        r"\s+"
        r"(\d{4})",

        text,

        re.IGNORECASE
        | re.DOTALL
    )

    dates = []

    for day, month, year in matches:

        parsed = parse_single_date(
            day,
            month,
            year
        )

        if parsed:
            dates.append(parsed)

    if dates:

        print(
            "[WARNING] Could not specifically identify "
            "Class Arrangements update date."
        )

        print(
            "[WARNING] Using newest "
            "'Last Updated' date."
        )

        return max(dates)

    raise RuntimeError(
        "Could not find an Ateneo "
        "Class Arrangements update date."
    )


# ============================================================
# SCHOOL ALIASES
# ============================================================

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
# BASIC EDUCATION EXTRACTION
# ============================================================

def find_basic_education_text(soup):
    """
    Extract the Basic Education section.

    Stop before University Operations.
    """

    text = get_page_text(soup)

    match = re.search(
        r"Basic Education"
        r"(.*?)"
        r"(?:University Operations|$)",

        text,

        re.IGNORECASE
        | re.DOTALL
    )

    if not match:

        print(
            "[WARNING] Could not isolate "
            "Basic Education section."
        )

        return text

    return match.group(1)


def find_school_position(text, school):
    """
    Find the earliest occurrence of one of a school's aliases.
    """

    positions = []

    for alias in SCHOOL_ALIASES[school]:

        match = re.search(
            rf"\b{re.escape(alias)}\b",

            text,

            re.IGNORECASE
        )

        if match:

            positions.append(
                (
                    match.start(),
                    match.end(),
                    alias
                )
            )

    if not positions:
        return None

    return min(
        positions,
        key=lambda x: x[0]
    )


def get_school_section(text, school):
    """
    Extract one school's announcement.

    Example:

    Ateneo Grade School
    ...
    Ateneo Junior High School

    Returns only the AGS section.
    """

    school_position = find_school_position(
        text,
        school
    )

    if not school_position:

        print(
            f"[WARNING] Could not find "
            f"{school} section."
        )

        return ""

    start, section_start, alias = (
        school_position
    )

    boundaries = []

    # Other schools are boundaries.

    for other_school in SCHOOL_ALIASES:

        if other_school == school:
            continue

        other_position = find_school_position(
            text[section_start:],
            other_school
        )

        if other_position:

            relative_start = other_position[0]

            boundaries.append(
                section_start
                + relative_start
            )

    # Other page sections are also boundaries.

    boundary_names = [

        "University Operations",
        "Higher Education",
    ]

    for boundary_name in boundary_names:

        match = re.search(
            re.escape(boundary_name),

            text[section_start:],

            re.IGNORECASE
        )

        if match:

            boundaries.append(
                section_start
                + match.start()
            )

    end = (
        min(boundaries)
        if boundaries
        else len(text)
    )

    section = text[
        start:end
    ].strip()

    print(
        f"[DEBUG] {school} matched alias: "
        f"{alias}"
    )

    return section


# ============================================================
# STATUS CLASSIFICATION
# ============================================================

def classify(text):
    """
    Determine school status.

    Important priority:

    Synchronous Online
    Asynchronous Online
    Mixed Online
    Suspension
    Online
    Onsite
    Unknown

    We do NOT classify a school as "Suspension" merely
    because the announcement mentions QC suspending
    face-to-face classes.

    Ateneo may then say:

        "AGS will be shifting to synchronous online"

    In that case the actual school status is ONLINE.
    """

    if not text:
        return "Unknown"

    text = text.lower()

    # --------------------------------------------------------
    # SYNCHRONOUS
    # --------------------------------------------------------

    synchronous_patterns = [

        r"\bsynchronous online\b",

        r"\bonline synchronous\b",

        r"\bsynchronous classes?\b",

        r"\bsynchronous session\b",

        r"\bsynchronous instruction\b",

        r"\bsynchronous modality\b",

        r"\bsynchronous learning\b",

        r"\bshifting to synchronous\b",

        r"\bshift to synchronous\b",
    ]

    # --------------------------------------------------------
    # ASYNCHRONOUS
    # --------------------------------------------------------

    asynchronous_patterns = [

        r"\basynchronous online\b",

        r"\bonline asynchronous\b",

        r"\basynchronous modality\b",

        r"\basynchronous classes?\b",

        r"\basynchronous period\b",

        r"\basynchronous tasks?\b",

        r"\basynchronous instruction\b",

        r"\basynchronous work\b",

        r"\basynchronous learning\b",

        r"\basynchronous activities\b",

        r"\bshifting to asynchronous\b",

        r"\bshift to asynchronous\b",
    ]

    has_sync = any(
        re.search(
            pattern,
            text
        )
        for pattern in synchronous_patterns
    )

    has_async = any(
        re.search(
            pattern,
            text
        )
        for pattern in asynchronous_patterns
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Check specific online modalities BEFORE suspension.
    #
    # The text might say:
    #
    # "Due to the suspension of face-to-face classes,
    # AGS will shift to synchronous online modality."
    #
    # That is NOT "No School".
    # --------------------------------------------------------

    if has_sync and has_async:

        return "Mixed Online"

    if has_sync:

        return "Synchronous Online"

    if has_async:

        return "Asynchronous Online"

    # --------------------------------------------------------
    # GENERAL ONLINE
    # --------------------------------------------------------

    online_patterns = [

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
    ]

    if any(
        re.search(
            pattern,
            text
        )
        for pattern in online_patterns
    ):

        return "Online"

    # --------------------------------------------------------
    # ACTUAL SUSPENSION
    # --------------------------------------------------------

    suspension_patterns = [

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
    ]

    if any(
        re.search(
            pattern,
            text
        )
        for pattern in suspension_patterns
    ):

        return "Suspension"

    # --------------------------------------------------------
    # ONSITE
    # --------------------------------------------------------

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
        re.search(
            pattern,
            text
        )
        for pattern in onsite_patterns
    ):

        return "Onsite"

    return "Unknown"


def get_statuses(soup):
    """
    Extract AGS/JHS/SHS statuses.
    """

    basic_education = find_basic_education_text(
        soup
    )

    statuses = {}

    for school in (
        "AGS",
        "JHS",
        "SHS",
    ):

        section = get_school_section(
            basic_education,
            school
        )

        status = classify(
            section
        )

        statuses[school] = status

        print(
            f"[DEBUG] {school}: {status}"
        )

        print(
            f"[DEBUG] {school} section:"
        )

        print(
            section[:500]
        )

        print(
            "-" * 40
        )

    return statuses


# ============================================================
# QC GOVERNMENT FEED
# ============================================================

def check_qc_government_feed(target_date):

    rss_url = (
        "https://quezoncity.gov.ph/feed/"
    )

    fallback_url = (
        "https://quezoncity.gov.ph/news/"
    )

    # Generate common ways a date might appear.

    date_strings = {

        # September 1 2026

        (
            f"{target_date.strftime('%B')} "
            f"{target_date.day} "
            f"{target_date.year}"
        ).lower(),

        # September 1

        (
            f"{target_date.strftime('%B')} "
            f"{target_date.day}"
        ).lower(),

        # Sep 1 2026

        (
            f"{target_date.strftime('%b')} "
            f"{target_date.day} "
            f"{target_date.year}"
        ).lower(),

        # 1 September 2026

        (
            f"{target_date.day} "
            f"{target_date.strftime('%B')} "
            f"{target_date.year}"
        ).lower(),

        # September-1-2026

        (
            f"{target_date.strftime('%B')}-"
            f"{target_date.day}-"
            f"{target_date.year}"
        ).lower(),

        # September 1, 2026

        (
            f"{target_date.strftime('%B')} "
            f"{target_date.day}, "
            f"{target_date.year}"
        ).lower(),
    }

    suspension_words = [

        "suspendido",

        "walang pasok",

        "suspended",

        "suspension",

        "no classes",
    ]

    private_school_words = [

        "private schools",

        "private school",

        "pribadong paaralan",

        "pribadong school",
    ]

    def inspect(text, title=""):

        combined = (
            title
            + " "
            + text
        ).lower()

        has_date = any(
            date_string in combined
            for date_string in date_strings
        )

        if not has_date:
            return None

        has_suspension = any(
            word in combined
            for word in suspension_words
        )

        if not has_suspension:
            return None

        has_private = any(
            word in combined
            for word in private_school_words
        )

        if not has_private:
            return None

        return (
            True,

            (
                "Private-school suspension: "
                f"{title}"
            ).strip()
        )

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    try:

        response = fetch(
            rss_url,
            timeout=10
        )

        soup = BeautifulSoup(
            response.text,
            "xml"
        )

        for item in soup.find_all("item"):

            title = (
                item.title.get_text(
                    " ",
                    strip=True
                )
                if item.title
                else ""
            )

            description = (
                item.description.get_text(
                    " ",
                    strip=True
                )
                if item.description
                else ""
            )

            result = inspect(
                description,
                title
            )

            if result:

                return result

    except Exception as error:

        print(
            f"QC RSS check failed: {error}",
            file=sys.stderr
        )

    # --------------------------------------------------------
    # HTML FALLBACK
    # --------------------------------------------------------

    try:

        response = fetch(
            fallback_url,
            timeout=10
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for link in soup.find_all("a"):

            href = link.get(
                "href",
                ""
            )

            link_text = link.get_text(
                " ",
                strip=True
            )

            result = inspect(
                link_text
                + " "
                + href,

                link_text
            )

            if result:

                return result

    except Exception as error:

        print(
            f"QC fallback failed: {error}",
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
    """
    Informational check.

    IMPORTANT:

    This does NOT automatically suspend Ateneo classes.

    The actual QC/Ateneo announcement is more authoritative
    for this bot.
    """

    url = (
        "https://bagong.pagasa.dost.gov.ph/weather"
    )

    try:

        response = fetch(
            url,
            timeout=10
        )

        html = response.text.lower()

        has_ncr = (

            "metro manila" in html

            or

            "quezon city" in html
        )

        if not has_ncr:

            return (
                False,
                "No NCR-specific PAGASA trigger."
            )

        rainfall_warning = any(

            phrase in html

            for phrase in [

                "red rainfall warning",

                "orange rainfall warning",
            ]
        )

        if rainfall_warning:

            return (
                True,
                "PAGASA Orange/Red rainfall warning "
                "mentioned."
            )

        return (
            False,
            "No relevant PAGASA trigger."
        )

    except Exception as error:

        print(
            f"PAGASA check failed: {error}",
            file=sys.stderr
        )

        return (
            False,
            "PAGASA check failed."
        )


# ============================================================
# FACEBOOK
# ============================================================

def check_facebook(target_date):
    """
    Best-effort Facebook check.

    Facebook frequently blocks scraping, so this should NEVER
    be the only authoritative source.
    """

    cutoff = (
        target_date
        - timedelta(
            days=FACEBOOK_LOOKBACK_DAYS
        )
    )

    try:

        response = SESSION.get(
            FACEBOOK_URL,
            timeout=20
        )

        if response.status_code != 200:

            print(
                f"Facebook returned HTTP "
                f"{response.status_code}"
            )

            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        raw_text = soup.get_text(
            " ",
            strip=True
        )

        lower = raw_text.lower()

        if (
            "log in" in lower
            and len(raw_text) < 5000
        ):

            print(
                "Facebook returned a login page."
            )

            return None

        for tag in soup([
            "script",
            "style",
            "noscript",
        ]):

            tag.decompose()

        content = soup.get_text(
            "\n",
            strip=True
        )

        content_lower = content.lower()

        private_school_words = [

            "private schools",

            "private school",

            "pribadong paaralan",
        ]

        suspension_words = [

            "suspended",

            "suspension",

            "suspendido",

            "walang pasok",

            "no classes",
        ]

        if not any(
            word in content_lower
            for word in private_school_words
        ):

            return None

        if not any(
            word in content_lower
            for word in suspension_words
        ):

            return None

        dates = parse_date_from_text(
            content
        )

        recent_dates = [

            date

            for date in dates

            if cutoff <= date <= target_date
        ]

        if not recent_dates:

            return None

        newest = max(
            recent_dates
        )

        return {

            "private_suspended": True,

            "date": newest,

            "reason": (
                "Facebook private-school "
                "suspension detected."
            ),
        }

    except Exception as error:

        print(
            f"Facebook check failed: {error}",
            file=sys.stderr
        )

    return None


# ============================================================
# DISPLAY
# ============================================================

def status_icon(status):

    icons = {

        "Synchronous Online": "🟢",

        "Asynchronous Online": "🟢",

        "Mixed Online": "🟢",

        "Online": "🟢",

        "Suspension": "🔴",

        "No School": "❌",

        "Onsite": "🔵",

        "Unknown": "🟡",
    }

    return icons.get(
        status,
        "🟡"
    )


def create_message(
    date,
    statuses,
    reason=None,
    reason_type=None,
):
    """
    Create the Google Chat message.
    """

    next_date = (
        date
        + timedelta(days=1)
    )

    date1 = format_date(
        date
    )

    date2 = format_date(
        next_date
    )

    lines = [

        "Yall heres the school status :D",

        "",

        (
            f"this is for: "
            f"*{date1}* and *{date2}*"
        ),

        "",

        (
            f"*School* | "
            f"*{date1}* | "
            f"*{date2}*"
        ),

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

        lines.append("")

        if reason_type == "calendar":

            lines.extend([

                "🚨 *NO CLASSES.*",

                reason,
            ])

        elif reason_type == "suspension":

            lines.extend([

                "🚨 *Private schools are suspended.*",

                reason,
            ])

    lines.extend([

        "",

        f"🔗 {ADVISORIES_URL}",
    ])

    return "\n".join(
        lines
    )


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_to_google_chat(message):

    if not WEBHOOK_URL:

        raise RuntimeError(
            "GOOGLE_CHAT_WEBHOOK secret "
            "is not set."
        )

    response = SESSION.post(

        WEBHOOK_URL,

        json={
            "text": message
        },

        timeout=30
    )

    response.raise_for_status()


# ============================================================
# MAIN
# ============================================================

def check_once():

    today = get_ph_date()

    print(
        "=" * 60
    )

    print(
        "Ateneo School Status Bot"
    )

    print(
        f"Today's Philippine date: "
        f"{format_date(today)}"
    )

    print(
        f"Philippine timezone: "
        f"{PH_TIMEZONE}"
    )

    print(
        f"Advisories URL: "
        f"{ADVISORIES_URL}"
    )

    print(
        f"Facebook lookback: "
        f"{FACEBOOK_LOOKBACK_DAYS} days"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # PHILIPPINE CALENDAR
    # --------------------------------------------------------

    calendar_no_classes, calendar_reason = (
        check_ph_calendar(
            today
        )
    )

    print(
        "Philippine calendar: "
        + (
            calendar_reason

            if calendar_no_classes

            else "Normal school day"
        )
    )

    if calendar_no_classes:

        print(
            f">>> NO CLASSES: "
            f"{calendar_reason}"
        )

        statuses = {

            "AGS": "No School",

            "JHS": "No School",

            "SHS": "No School",
        }

        message = create_message(

            today,

            statuses,

            reason=calendar_reason,

            reason_type="calendar",
        )

        print()
        print(message)
        print()

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

    print()
    print(
        "Checking Ateneo advisories..."
    )

    soup = fetch_advisories()

    advisory_date = (
        find_class_arrangements_date(
            soup
        )
    )

    print(
        f"Class Arrangements "
        f"last updated: "
        f"{format_date(advisory_date)}"
    )

    aten_status_valid = (
        advisory_date == today
    )

    print(
        f"Ateneo advisory matches today: "
        f"{aten_status_valid}"
    )

    if aten_status_valid:

        print(
            ">>> Using today's Ateneo "
            "Class Arrangements."
        )

        statuses = get_statuses(
            soup
        )

    else:

        print(
            ">>> Class Arrangements was not "
            "updated today."
        )

        print(
            ">>> Defaulting to Onsite."
        )

        statuses = {

            "AGS": "Onsite",

            "JHS": "Onsite",

            "SHS": "Onsite",
        }

    # --------------------------------------------------------
    # QC GOVERNMENT
    # --------------------------------------------------------

    print()
    print(
        "Checking QC government feed..."
    )

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

    print()
    print(
        "Checking PAGASA..."
    )

    pagasa_trigger, pagasa_reason = (
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

    print()
    print(
        "Checking Facebook..."
    )

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
    # PRIVATE SCHOOL SUSPENSION
    # --------------------------------------------------------

    private_suspended = (

        qc_private

        or

        facebook_private
    )

    suspension_reason = None

    reason_type = None

    if private_suspended:

        print()
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

            "SHS": "No School",
        }

        suspension_reason = reason

        reason_type = "suspension"

    # --------------------------------------------------------
    # FINAL MESSAGE
    # --------------------------------------------------------

    message = create_message(

        today,

        statuses,

        reason=suspension_reason,

        reason_type=reason_type,
    )

    print()
    print(
        "=" * 60
    )

    print(
        "FINAL MESSAGE"
    )

    print(
        "=" * 60
    )

    print()
    print(message)
    print()

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

    except Exception as error:

        print(
            f"ERROR: {error}",
            file=sys.stderr
        )

        sys.exit(1)
