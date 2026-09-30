import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import feedparser
import holidays
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


# ============================================================
# CONFIG
# ============================================================

ADVISORIES_URL = "https://www.ateneo.edu/advisories"
FACEBOOK_URL = "https://www.facebook.com/ateneodemanila/"

QC_FEED_URL = "https://quezoncity.gov.ph/feed/"
QC_NEWS_URL = "https://quezoncity.gov.ph/news/"
QC_ANNOUNCEMENTS_URL = (
    "https://quezoncity.gov.ph/news-and-media/announcements/"
)

PAGASA_NCR_URL = (
    "https://bagong.pagasa.dost.gov.ph/regional-forecast/ncrprsd"
)

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

FACEBOOK_LOOKBACK_DAYS = 14
ADVISORY_LOOKBACK_DAYS = 7
QC_LOOKBACK_DAYS = 3

PH_TIMEZONE = ZoneInfo("Asia/Manila")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
}


# ============================================================
# SCHOOL ALIASES
# ============================================================

SCHOOL_ALIASES = {
    "ags": [
        "Ateneo Grade School",
        "Ateneo de Manila Grade School",
        "Grade School",
        "AGS",
    ],
    "jhs": [
        "Ateneo Junior High School",
        "Ateneo de Manila Junior High School",
        "Junior High School",
        "AJHS",
        "JHS",
    ],
    "shs": [
        "Ateneo Senior High School",
        "Ateneo de Manila Senior High School",
        "Senior High School",
        "ASHS",
        "SHS",
    ],
}


# ============================================================
# HTTP
# ============================================================

def fetch(url, timeout=20):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        return response
    except Exception as e:
        print(f"[ERROR] Failed to fetch {url}: {e}")
        return None


# ============================================================
# TEXT / DATE HELPERS
# ============================================================

def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_ph_date():
    return datetime.now(PH_TIMEZONE).date()


def parse_date_string(value):
    if not value:
        return None

    value = normalize_text(value)

    formats = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def extract_dates(text):
    if not text:
        return []

    patterns = [
        r"\b(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},\s+\d{4}\b",

        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\.?\s+\d{1,2},\s+\d{4}\b",

        r"\b\d{4}-\d{2}-\d{2}\b",

        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    ]

    found = []

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            parsed = parse_date_string(match)

            if parsed:
                found.append(parsed)

    return found


def dates_in_window(text, target_date, days=1):
    dates = extract_dates(text)

    return [
        d
        for d in dates
        if abs((d - target_date).days) <= days
    ]


# ============================================================
# PH CALENDAR
# ============================================================

def check_ph_calendar(target_date):
    if target_date.weekday() >= 5:
        return True, "Weekend"

    fixed_holidays = {
        (1, 1): "New Year's Day",
        (4, 9): "Araw ng Kagitingan",
        (5, 1): "Labor Day",
        (6, 12): "Independence Day",
        (8, 21): "Ninoy Aquino Day",
        (8, 31): "National Heroes Day",
        (11, 1): "All Saints' Day",
        (11, 2): "All Souls' Day",
        (11, 30): "Bonifacio Day",
        (12, 8): "Feast of the Immaculate Conception",
        (12, 24): "Christmas Eve",
        (12, 25): "Christmas Day",
        (12, 30): "Rizal Day",
        (12, 31): "Last Day of the Year",
    }

    if (target_date.month, target_date.day) in fixed_holidays:
        return True, fixed_holidays[
            (target_date.month, target_date.day)
        ]

    try:
        ph_holidays = holidays.country_holidays(
            "PH",
            years=[target_date.year],
        )

        if target_date in ph_holidays:
            return True, ph_holidays.get(target_date)

    except Exception as e:
        print(f"[CALENDAR] Holiday lookup failed: {e}")

    return False, None


# ============================================================
# CLASSIFICATION
# ============================================================

def classify(text):
    text = normalize_text(text).lower()

    if any(
        phrase in text
        for phrase in [
            "synchronous online",
            "synchronous learning",
            "synchronous classes",
            "synchronous modality",
            "live online classes",
        ]
    ):
        return "Synchronous Online"

    if any(
        phrase in text
        for phrase in [
            "asynchronous online",
            "asynchronous learning",
            "asynchronous classes",
            "asynchronous modality",
        ]
    ):
        return "Asynchronous Online"

    if any(
        phrase in text
        for phrase in [
            "alternative delivery modes",
            "alternative delivery mode",
            "alternative delivery",
        ]
    ):
        if "synchronous" in text:
            return "Synchronous Online"

        if "asynchronous" in text:
            return "Asynchronous Online"

    if any(
        phrase in text
        for phrase in [
            "online modality",
            "online classes",
            "online learning",
            "classes will be held online",
            "learning will be conducted online",
        ]
    ):
        return "Synchronous Online"

    if any(
        phrase in text
        for phrase in [
            "classes are suspended",
            "classes will be suspended",
            "suspension of classes",
            "class suspension",
            "no classes",
            "classes cancelled",
            "classes canceled",
        ]
    ):
        return "No School"

    if any(
        phrase in text
        for phrase in [
            "face-to-face classes",
            "face to face classes",
            "onsite classes",
            "on-site classes",
            "classes will proceed as usual",
            "regular classes",
        ]
    ):
        return "Onsite"

    return None


# ============================================================
# SCHOOL-SPECIFIC ATENEO EXTRACTION
# ============================================================

def get_school_specific_text(soup, school):
    """
    Try to isolate the part of the advisory referring to one
    specific school.

    We look around headings / paragraphs containing the school's
    aliases rather than blindly applying one result to everyone.
    """

    aliases = SCHOOL_ALIASES[school]

    matches = []

    for element in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "strong"]
    ):
        text = normalize_text(
            element.get_text(" ", strip=True)
        )

        if not text:
            continue

        lower = text.lower()

        if any(alias.lower() in lower for alias in aliases):
            matches.append(element)

    if not matches:
        return ""

    chunks = []

    for element in matches:
        chunks.append(
            normalize_text(
                element.get_text(" ", strip=True)
            )
        )

        # Include nearby parent content.
        parent = element.parent

        if parent:
            parent_text = normalize_text(
                parent.get_text(" ", strip=True)
            )

            if parent_text:
                chunks.append(parent_text)

        # Include the next few siblings.
        sibling = element

        for _ in range(3):
            sibling = sibling.find_next_sibling()

            if not sibling:
                break

            sibling_text = normalize_text(
                sibling.get_text(" ", strip=True)
            )

            if sibling_text:
                chunks.append(sibling_text)

    # Deduplicate while preserving order.
    output = []
    seen = set()

    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            output.append(chunk)

    return normalize_text(" ".join(output))


# ============================================================
# ATENEO STATUS EXTRACTION
# ============================================================

def get_statuses(soup):
    page_text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    statuses = {
        "ags": "Unknown",
        "jhs": "Unknown",
        "shs": "Unknown",
    }

    for school in statuses:
        school_text = get_school_specific_text(
            soup,
            school,
        )

        if school_text:
            status = classify(school_text)

            if status:
                statuses[school] = status

    # Only use whole-page classification when no school-specific
    # result exists.
    overall = classify(page_text)

    if overall:
        for school in statuses:
            if statuses[school] == "Unknown":
                statuses[school] = overall

    return statuses


# ============================================================
# RECENT ATENEO ADVISORY
# ============================================================

def get_recent_ateneo_advisory(today):
    response = fetch(ADVISORIES_URL)

    if not response:
        return None, None, ""

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    dates = extract_dates(page_text)

    recent_dates = [
        d
        for d in dates
        if today - timedelta(days=ADVISORY_LOOKBACK_DAYS)
        <= d
        <= today
    ]

    arrangement_keywords = [
        "class arrangement",
        "class arrangements",
        "synchronous",
        "asynchronous",
        "online modality",
        "alternative delivery",
        "face-to-face",
        "face to face",
        "classes are suspended",
        "suspension of classes",
        "classes will proceed",
    ]

    has_arrangement = any(
        keyword in page_text.lower()
        for keyword in arrangement_keywords
    )

    if not has_arrangement:
        print("[ATENEO] No class-arrangement information found.")
        return None, None, ""

    advisory_date = (
        max(recent_dates)
        if recent_dates
        else None
    )

    if advisory_date:
        age = (today - advisory_date).days

        print(
            f"[ATENEO] Recent advisory: "
            f"{advisory_date} ({age} day(s) old)"
        )
    else:
        print(
            "[ATENEO] Arrangement found, "
            "but no usable advisory date."
        )

    return soup, advisory_date, page_text


# ============================================================
# QC FEED DISCOVERY
# ============================================================

def is_qc_url(url):
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower()

        return (
            hostname == "quezoncity.gov.ph"
            or hostname.endswith(".quezoncity.gov.ph")
        )

    except Exception:
        return False


def discover_qc_feed_urls():
    candidates = {
        QC_FEED_URL,
        QC_NEWS_URL,
        QC_ANNOUNCEMENTS_URL,
    }

    discovered = set()

    for url in candidates:
        response = fetch(url)

        if not response:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        for link in soup.find_all("link"):
            href = link.get("href")

            if not href:
                continue

            link_type = (
                link.get("type", "")
                or ""
            ).lower()

            href_lower = href.lower()

            if (
                "rss" in link_type
                or "atom" in link_type
                or "feed" in href_lower
                or "rss" in href_lower
            ):
                if is_qc_url(href):
                    discovered.add(href)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            href_lower = href.lower()

            if (
                "feed" in href_lower
                or "rss" in href_lower
                or "atom" in href_lower
            ):
                if is_qc_url(href):
                    discovered.add(href)

    discovered.add(QC_FEED_URL)

    print("[QC] Feed candidates:")

    for url in sorted(discovered):
        print(f"  - {url}")

    return list(discovered)


# ============================================================
# QC ANNOUNCEMENT ANALYSIS
# ============================================================

def analyze_qc_announcement(url, target_date):
    if not is_qc_url(url):
        return None

    response = fetch(url)

    if not response:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    lower = text.lower()

    relevant_dates = dates_in_window(
        text,
        target_date,
        days=QC_LOOKBACK_DAYS,
    )

    if not relevant_dates:
        return None

    private_school = any(
        phrase in lower
        for phrase in [
            "private schools",
            "private school",
            "private educational institutions",
            "pribadong paaralan",
        ]
    )

    suspended = any(
        phrase in lower
        for phrase in [
            "suspension of classes",
            "classes suspended",
            "classes are suspended",
            "face-to-face classes suspended",
            "suspend face-to-face",
            "suspended face-to-face",
            "walang pasok",
            "suspension ng klase",
        ]
    )

    alternative_delivery = any(
        phrase in lower
        for phrase in [
            "alternative delivery modes",
            "alternative delivery mode",
            "alternative delivery",
            "synchronous / asynchronous",
            "synchronous/asynchronous",
            "synchronous and asynchronous",
            "synchronous or asynchronous",
        ]
    )

    if (
        "synchronous" in lower
        and "asynchronous" in lower
    ):
        alternative_delivery = True

    title = ""

    h1 = soup.find("h1")

    if h1:
        title = normalize_text(
            h1.get_text(" ", strip=True)
        )

    if not title:
        title_tag = soup.find("title")

        if title_tag:
            title = normalize_text(
                title_tag.get_text(" ", strip=True)
            )

    newest_date = max(relevant_dates)

    return {
        "url": url,
        "title": title,
        "date": newest_date,
        "private_school": private_school,
        "suspended": suspended,
        "alternative_delivery": alternative_delivery,
        "text": text,
    }


# ============================================================
# QC GOVERNMENT FEED
# ============================================================

def check_qc_government_feed(target_date=None):
    if target_date is None:
        target_date = get_ph_date()

    feed_urls = discover_qc_feed_urls()

    announcements = []

    for feed_url in feed_urls:
        print(f"[QC] Reading feed: {feed_url}")

        response = fetch(feed_url)

        if not response:
            continue

        parsed = feedparser.parse(
            response.content
        )

        for entry in parsed.entries:
            entry_url = (
                entry.get("link")
                or entry.get("id")
                or ""
            )

            if not entry_url:
                continue

            if not is_qc_url(entry_url):
                continue

            result = analyze_qc_announcement(
                entry_url,
                target_date,
            )

            if result:
                announcements.append(result)

    unique = {}

    for announcement in announcements:
        unique[announcement["url"]] = announcement

    announcements = list(unique.values())

    if not announcements:
        print(
            "[QC] Feed produced no usable announcements; "
            "scanning announcements page."
        )

        response = fetch(
            QC_ANNOUNCEMENTS_URL
        )

        if response:
            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            for a in soup.find_all(
                "a",
                href=True,
            ):
                href = a["href"]

                if not is_qc_url(href):
                    continue

                result = analyze_qc_announcement(
                    href,
                    target_date,
                )

                if result:
                    unique[result["url"]] = result

            announcements = list(
                unique.values()
            )

    if not announcements:
        print("[QC] No relevant announcement found.")

        return {
            "private_suspended": False,
            "alternative_delivery": False,
            "reason": None,
            "title": None,
            "date": None,
            "url": None,
        }

    announcements.sort(
        key=lambda x: x["date"],
        reverse=True,
    )

    newest = announcements[0]

    private_suspended = (
        newest["private_school"]
        and newest["suspended"]
    )

    alternative_delivery = (
        newest["alternative_delivery"]
    )

    print(
        f"[QC] Newest announcement: "
        f"{newest['title'] or '(untitled)'}"
    )

    print(
        f"[QC] Date: {newest['date']}"
    )

    print(
        f"[QC] Private school: "
        f"{newest['private_school']}"
    )

    print(
        f"[QC] Suspended: "
        f"{newest['suspended']}"
    )

    print(
        f"[QC] Alternative delivery: "
        f"{newest['alternative_delivery']}"
    )

    print(
        f"[QC] URL: {newest['url']}"
    )

    return {
        "private_suspended": private_suspended,
        "alternative_delivery": alternative_delivery,
        "reason": (
            "Private-school suspension + "
            "Alternative Delivery Modes"
            if (
                private_suspended
                and alternative_delivery
            )
            else (
                "Private-school suspension"
                if private_suspended
                else (
                    "Alternative Delivery Modes"
                    if alternative_delivery
                    else None
                )
            )
        ),
        "title": newest["title"],
        "date": newest["date"],
        "url": newest["url"],
    }


# ============================================================
# PAGASA
# ============================================================

def check_pagasa_bulletin():
    response = fetch(PAGASA_NCR_URL)

    if not response:
        return False, None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = normalize_text(
        soup.get_text(" ", strip=True)
    ).lower()

    if "red warning level" in text:
        return True, "PAGASA NCR Red Warning"

    if "orange warning level" in text:
        return True, "PAGASA NCR Orange Warning"

    return False, None


# ============================================================
# FACEBOOK
# ============================================================

def check_facebook_private_suspension(target_date=None):
    """
    Facebook is a noisy source: its page can contain older posts and
    cached text, so a generic "no classes" + "Ateneo" match is NOT
    enough to cancel school.

    We only return True when the page contains a date matching
    target_date (or, if no date is supplied, today's date) alongside
    an explicit suspension statement.
    """
    if target_date is None:
        target_date = get_ph_date()

    response = fetch(FACEBOOK_URL)
    if not response:
        return False

    soup = BeautifulSoup(response.text, "html.parser")
    text = normalize_text(soup.get_text(" ", strip=True))

    if not text:
        return False

    lower = text.lower()

    suspension_terms = [
        "no classes",
        "classes suspended",
        "class suspension",
        "walang pasok",
        "suspension of classes",
        "suspension ng klase",
    ]

    if not any(term in lower for term in suspension_terms):
        return False

    # Never treat an undated Facebook page as a current suspension.
    dates = extract_dates(text)
    if target_date not in dates:
        print(
            "[FACEBOOK] Suspension language found, but no matching "
            f"date for {target_date}; ignoring it."
        )
        return False

    print(
        f"[FACEBOOK] Explicit suspension dated {target_date} found."
    )
    return True


# ============================================================
# SCHOOL-SPECIFIC TOMORROW GUESSER
# ============================================================

def guess_school_tomorrow(
    school,
    today,
    ateneo_soup,
    advisory_date,
    advisory_text,
    qc_result,
    pagasa_trigger,
    pagasa_reason,
    facebook_suspension,
):
    """
    Make an independent prediction for ONE school.

    Returns:
        status
        confidence
        reasons
        scores
    """

    tomorrow = today + timedelta(days=1)

    # In the absence of a closure/online announcement, the normal
    # school-day state is Onsite. "Unknown" should only be used when
    # the source data itself is unavailable, not simply because no
    # special announcement was found.
    scores = {
        "Synchronous Online": 0,
        "Asynchronous Online": 0,
        "No School": 0,
        "Onsite": 55,
    }

    reasons = [
        "No explicit closure or online arrangement found; "
        "defaulting to normal onsite classes."
    ]

    # --------------------------------------------------------
    # Calendar
    # --------------------------------------------------------

    holiday, holiday_reason = check_ph_calendar(
        tomorrow
    )

    if holiday:
        scores["No School"] += 100

        reasons.append(
            f"Calendar: {holiday_reason}"
        )

    # --------------------------------------------------------
    # QC
    # --------------------------------------------------------

    if qc_result["private_suspended"]:
        scores["No School"] += 20

        reasons.append(
            "QC indicates a private-school suspension."
        )

    if qc_result["alternative_delivery"]:
        scores["Synchronous Online"] += 25
        scores["Asynchronous Online"] += 25

        # Alternative Delivery Mode overrides generic
        # suspension evidence.
        scores["No School"] -= 15

        reasons.append(
            "QC indicates Alternative Delivery Modes."
        )

    # --------------------------------------------------------
    # PAGASA
    # --------------------------------------------------------

    if pagasa_trigger:
        scores["Synchronous Online"] += 20
        scores["Asynchronous Online"] += 20

        reasons.append(
            f"PAGASA: {pagasa_reason}"
        )

    # --------------------------------------------------------
    # SCHOOL-SPECIFIC ATENEO ADVISORY
    # --------------------------------------------------------

    school_text = ""

    if ateneo_soup is not None:
        school_text = get_school_specific_text(
            ateneo_soup,
            school,
        )

    school_lower = school_text.lower()

    # --------------------------------------------------------
    # Strong school-specific signals
    # --------------------------------------------------------

    if school_lower:
        if any(
            phrase in school_lower
            for phrase in [
                "synchronous online",
                "synchronous learning",
                "synchronous classes",
                "synchronous modality",
                "live online classes",
            ]
        ):
            scores["Synchronous Online"] += 70

            reasons.append(
                "Ateneo advisory specifically mentions "
                "synchronous learning for this school."
            )

        if any(
            phrase in school_lower
            for phrase in [
                "asynchronous online",
                "asynchronous learning",
                "asynchronous classes",
                "asynchronous modality",
            ]
        ):
            scores["Asynchronous Online"] += 70

            reasons.append(
                "Ateneo advisory specifically mentions "
                "asynchronous learning for this school."
            )

        if any(
            phrase in school_lower
            for phrase in [
                "online modality",
                "online classes",
                "online learning",
            ]
        ):
            scores["Synchronous Online"] += 35

            reasons.append(
                "Ateneo advisory specifically mentions "
                "online learning for this school."
            )

        if (
            "alternative delivery" in school_lower
            and "synchronous" in school_lower
        ):
            scores["Synchronous Online"] += 35

        if (
            "alternative delivery" in school_lower
            and "asynchronous" in school_lower
        ):
            scores["Asynchronous Online"] += 35

        if any(
            phrase in school_lower
            for phrase in [
                "classes are suspended",
                "classes will be suspended",
                "no classes",
                "class suspension",
            ]
        ):
            scores["No School"] += 60

            reasons.append(
                "Ateneo advisory specifically suspends "
                "this school's classes."
            )

        if any(
            phrase in school_lower
            for phrase in [
                "onsite classes",
                "on-site classes",
                "face-to-face classes",
                "face to face classes",
                "classes will proceed as usual",
                "regular classes",
            ]
        ):
            scores["Onsite"] += 50

            reasons.append(
                "Ateneo advisory specifically indicates "
                "onsite/regular classes for this school."
            )

    # --------------------------------------------------------
    # If no school-specific section exists, use the overall
    # advisory, but at LOWER confidence.
    # --------------------------------------------------------

    elif advisory_text:
        text = advisory_text.lower()

        if "synchronous" in text:
            scores["Synchronous Online"] += 15

            reasons.append(
                "Recent Ateneo advisory mentions "
                "synchronous learning, but no school-specific "
                "section was found."
            )

        if "asynchronous" in text:
            scores["Asynchronous Online"] += 15

            reasons.append(
                "Recent Ateneo advisory mentions "
                "asynchronous learning, but no school-specific "
                "section was found."
            )

        if (
            "online modality" in text
            or "online classes" in text
        ):
            scores["Synchronous Online"] += 10

        if (
            "face-to-face" in text
            and "suspend" in text
        ):
            scores["Synchronous Online"] += 10
            scores["Asynchronous Online"] += 10

    # --------------------------------------------------------
    # Facebook
    # --------------------------------------------------------

    if facebook_suspension:
        scores["No School"] += 10

        reasons.append(
            "Ateneo Facebook appears to indicate "
            "a private-school suspension."
        )

    # --------------------------------------------------------
    # Clean scores
    # --------------------------------------------------------

    scores = {
        status: max(0, score)
        for status, score in scores.items()
    }

    best_status = max(
        scores,
        key=scores.get,
    )

    best_score = scores[best_status]

    # Onsite has a normal-school baseline, so an ordinary day no longer
    # becomes "Unknown" just because there is no special announcement.
    if best_score <= 0:
        return (
            "Unknown",
            0,
            reasons,
            scores,
        )

    # --------------------------------------------------------
    # Confidence
    #
    # This is an evidence score, NOT a mathematical probability.
    # We deliberately cap it below 100 because public info can
    # still be wrong or superseded.
    # --------------------------------------------------------

    confidence = min(
        99,
        max(
            50,
            int(best_score),
        ),
    )

    return (
        best_status,
        confidence,
        reasons,
        scores,
    )


# ============================================================
# GUESS ALL THREE SCHOOLS
# ============================================================

def guess_tomorrow_statuses(
    today,
    ateneo_soup,
    advisory_date,
    advisory_text,
    qc_result,
    pagasa_trigger,
    pagasa_reason,
    facebook_suspension,
):
    guesses = {}

    for school in [
        "ags",
        "jhs",
        "shs",
    ]:
        guesses[school] = guess_school_tomorrow(
            school=school,
            today=today,
            ateneo_soup=ateneo_soup,
            advisory_date=advisory_date,
            advisory_text=advisory_text,
            qc_result=qc_result,
            pagasa_trigger=pagasa_trigger,
            pagasa_reason=pagasa_reason,
            facebook_suspension=facebook_suspension,
        )

    return guesses


def format_guessed_status(
    status,
    confidence,
):
    if status == "Unknown":
        return "Guess: Unknown (no idea)"

    return (
        f"Guess: {status} "
        f"({confidence}% sure)"
    )


# ============================================================
# MESSAGE
# ============================================================

def create_message(
    today,
    statuses,
    tomorrow_guesses,
):
    tomorrow = today + timedelta(days=1)

    ags_guess = tomorrow_guesses["ags"]
    jhs_guess = tomorrow_guesses["jhs"]
    shs_guess = tomorrow_guesses["shs"]

    return (
        f"📚 Ateneo School Status\n\n"
        f"Today - {today.strftime('%B %d, %Y')}\n"
        f"• AGS: {statuses['ags']}\n"
        f"• JHS: {statuses['jhs']}\n"
        f"• SHS: {statuses['shs']}\n\n"
        f"Tomorrow — {tomorrow.strftime('%B %d, %Y')}\n"
        f"• AGS: "
        f"{format_guessed_status(ags_guess[0], ags_guess[1])}\n"
        f"• JHS: "
        f"{format_guessed_status(jhs_guess[0], jhs_guess[1])}\n"
        f"• SHS: "
        f"{format_guessed_status(shs_guess[0], shs_guess[1])}"
    )


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_to_google_chat(message):
    if not WEBHOOK_URL:
        print(
            "[CHAT] GOOGLE_CHAT_WEBHOOK is not set."
        )
        print(message)
        return False

    try:
        response = requests.post(
            WEBHOOK_URL,
            json={"text": message},
            timeout=20,
        )

        response.raise_for_status()

        print(
            "[CHAT] Message sent successfully."
        )

        return True

    except Exception as e:
        print(
            f"[CHAT] Failed to send message: {e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def check_once():
    today = get_ph_date()

    print()
    print("=" * 70)
    print(
        f"School status check — "
        f"{today.strftime('%B %d, %Y')}"
    )
    print("=" * 70)

    # ========================================================
    # TODAY
    # ========================================================

    calendar_closed, calendar_reason = (
        check_ph_calendar(today)
    )

    if calendar_closed:
        statuses = {
            "ags": "No School",
            "jhs": "No School",
            "shs": "No School",
        }

        print(
            f"[TODAY] No School — "
            f"{calendar_reason}"
        )

        # Still fetch tomorrow's information below.
        qc_result = {
            "private_suspended": False,
            "alternative_delivery": False,
            "reason": None,
            "title": None,
            "date": None,
            "url": None,
        }

        pagasa_trigger = False
        pagasa_reason = None

        ateneo_soup = None
        advisory_date = None
        advisory_text = ""

        facebook_suspension = False

    else:
        # ====================================================
        # QC
        # ====================================================

        qc_result = check_qc_government_feed(
            today
        )

        print(
            f"[DEBUG] QC private suspended: "
            f"{qc_result['private_suspended']}"
        )

        print(
            f"[DEBUG] QC alternative delivery: "
            f"{qc_result['alternative_delivery']}"
        )

        # ====================================================
        # PAGASA
        # ====================================================

        pagasa_trigger, pagasa_reason = (
            check_pagasa_bulletin()
        )

        print(
            f"[DEBUG] PAGASA trigger: "
            f"{pagasa_trigger}"
        )

        print(
            f"[DEBUG] PAGASA reason: "
            f"{pagasa_reason}"
        )

        # ====================================================
        # ATENEO
        # ====================================================

        (
            ateneo_soup,
            advisory_date,
            advisory_text,
        ) = get_recent_ateneo_advisory(
            today
        )

        if ateneo_soup is not None:
            statuses = get_statuses(
                ateneo_soup
            )
        else:
            statuses = {
                "ags": "Onsite",
                "jhs": "Onsite",
                "shs": "Onsite",
            }

        # ====================================================
        # FACEBOOK
        # ====================================================

        facebook_suspension = (
            check_facebook_private_suspension(today)
        )

        print(
            f"[DEBUG] Facebook private suspension: "
            f"{facebook_suspension}"
        )

        # ====================================================
        # TODAY DECISION ENGINE
        # ====================================================

        private_suspended = (
            qc_result["private_suspended"]
            or facebook_suspension
        )

        if (
            private_suspended
            and not qc_result["alternative_delivery"]
        ):
            statuses = {
                "ags": "No School",
                "jhs": "No School",
                "shs": "No School",
            }

            print(
                "[TODAY] Private-school suspension "
                "without Alternative Delivery -> "
                "No School"
            )

        elif (
            qc_result["alternative_delivery"]
            or pagasa_trigger
        ):
            if ateneo_soup is not None:
                statuses = get_statuses(
                    ateneo_soup
                )

                print(
                    "[TODAY] Alternative delivery/weather "
                    "signal -> using Ateneo advisory."
                )
            else:
                statuses = {
                    "ags": "Unknown",
                    "jhs": "Unknown",
                    "shs": "Unknown",
                }

                print(
                    "[TODAY] Signal found but no "
                    "recent Ateneo advisory."
                )

        elif ateneo_soup is not None:
            statuses = get_statuses(
                ateneo_soup
            )

            print(
                "[TODAY] Using recent Ateneo advisory."
            )

        else:
            statuses = {
                "ags": "Onsite",
                "jhs": "Onsite",
                "shs": "Onsite",
            }

            print(
                "[TODAY] No relevant advisory -> Onsite."
            )

    # ========================================================
    # TOMORROW
    # ========================================================

    print()
    print("=" * 70)
    print("TOMORROW — INDEPENDENT SCHOOL GUESSES")
    print("=" * 70)

    # If today had no QC/Ateneo fetch because it was a holiday,
    # refresh the public sources for tomorrow.
    tomorrow = today + timedelta(days=1)

    tomorrow_qc = check_qc_government_feed(
        tomorrow
    )

    tomorrow_pagasa_trigger, tomorrow_pagasa_reason = (
        check_pagasa_bulletin()
    )

    # Use recent Ateneo information for the guess.
    (
        tomorrow_ateneo_soup,
        tomorrow_advisory_date,
        tomorrow_advisory_text,
    ) = get_recent_ateneo_advisory(
        today
    )

    tomorrow_facebook = (
        check_facebook_private_suspension(tomorrow)
    )

    tomorrow_guesses = guess_tomorrow_statuses(
        today=today,
        ateneo_soup=tomorrow_ateneo_soup,
        advisory_date=tomorrow_advisory_date,
        advisory_text=tomorrow_advisory_text,
        qc_result=tomorrow_qc,
        pagasa_trigger=tomorrow_pagasa_trigger,
        pagasa_reason=tomorrow_pagasa_reason,
        facebook_suspension=tomorrow_facebook,
    )

    for school, label in [
        ("ags", "AGS"),
        ("jhs", "JHS"),
        ("shs", "SHS"),
    ]:
        guess = tomorrow_guesses[school]

        print(
            f"{label}: "
            f"{format_guessed_status(guess[0], guess[1])}"
        )

        print(
            f"  Scores: {guess[3]}"
        )

        for reason in guess[2]:
            print(
                f"  - {reason}"
            )

        print()

    # ========================================================
    # SEND
    # ========================================================

    message = create_message(
        today,
        statuses,
        tomorrow_guesses,
    )

    print("=" * 70)
    print("FINAL MESSAGE")
    print("=" * 70)
    print(message)
    print()

    send_to_google_chat(message)


if __name__ == "__main__":
    check_once()
