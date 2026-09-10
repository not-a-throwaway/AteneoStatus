import os
import re
from datetime import datetime, date, timedelta
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
# SCHOOL NAMES
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
        "Junior High School",
        "JHS",
    ],
    "shs": [
        "Ateneo Senior High School",
        "Senior High School",
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
# DATE HELPERS
# ============================================================

def get_ph_date():
    return datetime.now(PH_TIMEZONE).date()


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


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
    """
    Extract common English date formats from arbitrary text.
    """
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
        d for d in dates
        if abs((d - target_date).days) <= days
    ]


# ============================================================
# PHILIPPINE CALENDAR
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
# ATENEO ADVISORY CLASSIFICATION
# ============================================================

def classify(text):
    text = normalize_text(text).lower()

    # Most specific first.
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
            "alternative delivery mode",
            "alternative delivery modes",
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
# ATENEO SCHOOL STATUS
# ============================================================

def get_statuses(soup):
    """
    Extract AGS/JHS/SHS statuses from the advisory page.
    """

    text = soup.get_text(" ", strip=True)

    statuses = {
        "ags": "Unknown",
        "jhs": "Unknown",
        "shs": "Unknown",
    }

    # Try to classify school-specific sections first.
    for school, aliases in SCHOOL_ALIASES.items():
        for alias in aliases:
            matches = soup.find_all(
                string=lambda s: s and alias.lower() in s.lower()
            )

            for match in matches:
                parent = match.parent

                # Search a reasonably sized surrounding area.
                chunks = [
                    parent.get_text(" ", strip=True)
                    if parent else "",
                ]

                if parent and parent.parent:
                    chunks.append(
                        parent.parent.get_text(" ", strip=True)
                    )

                combined = " ".join(chunks)
                status = classify(combined)

                if status:
                    statuses[school] = status
                    break

            if statuses[school] != "Unknown":
                break

    # If school-specific extraction failed, inspect the entire advisory.
    overall = classify(text)

    if overall:
        for school in statuses:
            if statuses[school] == "Unknown":
                statuses[school] = overall

    return statuses


# ============================================================
# FIND RECENT ATENEO ADVISORY
# ============================================================

def get_recent_ateneo_advisory(today):
    """
    The advisory does NOT have to be dated today.

    If an advisory containing class-arrangement information was
    published within the previous week, use it.
    """

    response = fetch(ADVISORIES_URL)

    if not response:
        return None, None, ""

    soup = BeautifulSoup(response.text, "html.parser")

    page_text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    # Look for date information anywhere on the page.
    dates = extract_dates(page_text)

    recent_dates = [
        d for d in dates
        if today - timedelta(days=ADVISORY_LOOKBACK_DAYS)
        <= d
        <= today
    ]

    # Look for class arrangement terminology.
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

    advisory_date = max(recent_dates) if recent_dates else None

    if advisory_date:
        age = (today - advisory_date).days
        print(
            f"[ATENEO] Found recent advisory date: "
            f"{advisory_date} ({age} day(s) old)"
        )
    else:
        print(
            "[ATENEO] Class-arrangement information found, "
            "but no usable date was detected."
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
    """
    Discover RSS/Atom feeds from official QC pages.

    The feed itself is NOT treated as the announcement.
    We follow the individual entry URL and inspect that page.
    """

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

        soup = BeautifulSoup(response.text, "html.parser")

        # RSS/Atom <link> tags.
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

        # Also inspect normal links.
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

    # Known official feed as fallback.
    discovered.add(QC_FEED_URL)

    print("[QC] Feed candidates:")

    for url in sorted(discovered):
        print(f"  - {url}")

    return list(discovered)


# ============================================================
# QC ANNOUNCEMENT ANALYSIS
# ============================================================

def analyze_qc_announcement(url, target_date):
    """
    Fetch the actual QC announcement page and determine what it says.
    """

    if not is_qc_url(url):
        return None

    response = fetch(url)

    if not response:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    lower = text.lower()

    # Ignore ancient announcements.
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

    # A more explicit check for modality language.
    if (
        "synchronous" in lower
        and "asynchronous" in lower
    ):
        alternative_delivery = True

    title = ""

    # Try to get the page title / H1.
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

        parsed = feedparser.parse(response.content)

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

            # Inspect the actual announcement URL.
            result = analyze_qc_announcement(
                entry_url,
                target_date,
            )

            if result:
                announcements.append(result)

    # Remove duplicate URLs.
    unique = {}

    for announcement in announcements:
        unique[announcement["url"]] = announcement

    announcements = list(unique.values())

    # --------------------------------------------------------
    # If RSS discovery failed, inspect official announcements page
    # links directly.
    # --------------------------------------------------------

    if not announcements:
        print(
            "[QC] Feed produced no usable announcements; "
            "scanning official announcements page."
        )

        response = fetch(QC_ANNOUNCEMENTS_URL)

        if response:
            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            for a in soup.find_all("a", href=True):
                href = a["href"]

                if not is_qc_url(href):
                    continue

                result = analyze_qc_announcement(
                    href,
                    target_date,
                )

                if result:
                    unique[result["url"]] = result

            announcements = list(unique.values())

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

    # Newest relevant announcement wins.
    announcements.sort(
        key=lambda x: x["date"],
        reverse=True,
    )

    newest = announcements[0]

    private_suspended = (
        newest["private_school"]
        and newest["suspended"]
    )

    alternative_delivery = newest["alternative_delivery"]

    print(
        f"[QC] Newest announcement: "
        f"{newest['title'] or '(untitled)'}"
    )

    print(f"[QC] Date: {newest['date']}")
    print(f"[QC] Private school: {newest['private_school']}")
    print(f"[QC] Suspended: {newest['suspended']}")
    print(
        f"[QC] Alternative delivery: "
        f"{newest['alternative_delivery']}"
    )
    print(f"[QC] URL: {newest['url']}")

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

    # Only Orange/Red are treated as a trigger.
    if "red warning level" in text:
        return True, "PAGASA NCR Red Warning"

    if "orange warning level" in text:
        return True, "PAGASA NCR Orange Warning"

    return False, None


# ============================================================
# FACEBOOK
# ============================================================

def check_facebook_private_suspension():
    response = fetch(FACEBOOK_URL)

    if not response:
        return False

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = normalize_text(
        soup.get_text(" ", strip=True)
    ).lower()

    if not text:
        return False

    suspension_terms = [
        "no classes",
        "classes suspended",
        "class suspension",
        "walang pasok",
        "suspension of classes",
    ]

    private_terms = [
        "private schools",
        "private school",
        "ateneo",
    ]

    has_suspension = any(
        term in text
        for term in suspension_terms
    )

    has_private = any(
        term in text
        for term in private_terms
    )

    return has_suspension and has_private


# ============================================================
# TOMORROW GUESSER
# ============================================================

def guess_tomorrow_status(today):
    """
    Guess tomorrow's status from publicly available information.

    This is deliberately separate from the official status engine.
    """

    tomorrow = today + timedelta(days=1)

    scores = {
        "Synchronous Online": 0,
        "Asynchronous Online": 0,
        "No School": 0,
        "Onsite": 0,
    }

    reasons = []

    # --------------------------------------------------------
    # 1. Weekend / holiday
    # --------------------------------------------------------

    is_holiday, holiday_reason = check_ph_calendar(
        tomorrow
    )

    if is_holiday:
        scores["No School"] += 100
        reasons.append(
            f"Calendar: {holiday_reason}"
        )

    # --------------------------------------------------------
    # 2. QC
    # --------------------------------------------------------

    try:
        qc = check_qc_government_feed(tomorrow)

        if qc["private_suspended"]:
            scores["No School"] += 25
            reasons.append(
                "QC indicates a private-school suspension."
            )

        if qc["alternative_delivery"]:
            # Alternative Delivery Modes is evidence for
            # online learning, but does not distinguish
            # synchronous vs asynchronous by itself.
            scores["Synchronous Online"] += 35
            scores["Asynchronous Online"] += 30

            # Important:
            # alternative delivery overrides the generic
            # "private school suspended" interpretation.
            scores["No School"] -= 20

            reasons.append(
                "QC indicates Alternative Delivery Modes."
            )

    except Exception as e:
        print(f"[GUESS] QC failed: {e}")

    # --------------------------------------------------------
    # 3. PAGASA
    # --------------------------------------------------------

    try:
        pagasa_trigger, pagasa_reason = (
            check_pagasa_bulletin()
        )

        if pagasa_trigger:
            scores["Synchronous Online"] += 25
            scores["Asynchronous Online"] += 20

            reasons.append(
                f"PAGASA: {pagasa_reason}"
            )

    except Exception as e:
        print(f"[GUESS] PAGASA failed: {e}")

    # --------------------------------------------------------
    # 4. Recent Ateneo advisory
    # --------------------------------------------------------

    try:
        soup, advisory_date, advisory_text = (
            get_recent_ateneo_advisory(today)
        )

        if soup is not None:
            text = advisory_text.lower()

            if "synchronous" in text:
                scores["Synchronous Online"] += 60

                reasons.append(
                    "Recent Ateneo advisory mentions "
                    "synchronous learning."
                )

            if "asynchronous" in text:
                scores["Asynchronous Online"] += 60

                reasons.append(
                    "Recent Ateneo advisory mentions "
                    "asynchronous learning."
                )

            if (
                "online modality" in text
                or "online classes" in text
                or "online learning" in text
            ):
                scores["Synchronous Online"] += 40

                reasons.append(
                    "Recent Ateneo advisory mentions "
                    "online learning."
                )

            if (
                "face-to-face" in text
                and "suspend" in text
            ):
                scores["Synchronous Online"] += 25
                scores["Asynchronous Online"] += 20

                reasons.append(
                    "Recent Ateneo advisory suspends "
                    "face-to-face classes."
                )

            if advisory_date:
                reasons.append(
                    f"Advisory date: {advisory_date}"
                )

    except Exception as e:
        print(f"[GUESS] Ateneo failed: {e}")

    # --------------------------------------------------------
    # 5. Facebook
    # --------------------------------------------------------

    try:
        facebook_suspension = (
            check_facebook_private_suspension()
        )

        if facebook_suspension:
            scores["No School"] += 15

            reasons.append(
                "Ateneo Facebook appears to indicate "
                "a private-school suspension."
            )

    except Exception as e:
        print(f"[GUESS] Facebook failed: {e}")

    # --------------------------------------------------------
    # 6. Choose result
    # --------------------------------------------------------

    # Don't allow a negative score.
    scores = {
        status: max(0, score)
        for status, score in scores.items()
    }

    best_status = max(
        scores,
        key=scores.get,
    )

    best_score = scores[best_status]

    # Nothing useful at all.
    if best_score <= 0:
        return (
            "Unknown",
            0,
            reasons,
            scores,
        )

    # Convert our evidence score to a more readable percentage.
    #
    # 100 = extremely strong evidence.
    # We don't claim mathematical probability here.
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


def format_guessed_status(status, confidence):
    if status == "Unknown":
        return "Guess: Unknown (no idea)"

    return f"Guess: {status} ({confidence}% sure)"


# ============================================================
# MESSAGE
# ============================================================

def create_message(
    today,
    statuses,
    tomorrow_guess,
    tomorrow_confidence,
):
    tomorrow_display = format_guessed_status(
        tomorrow_guess,
        tomorrow_confidence,
    )

    return (
        f"📚 Ateneo School Status\n\n"
        f"Today — {today.strftime('%B %d, %Y')}\n"
        f"• AGS: {statuses['ags']}\n"
        f"• JHS: {statuses['jhs']}\n"
        f"• SHS: {statuses['shs']}\n\n"
        f"Tomorrow — "
        f"{(today + timedelta(days=1)).strftime('%B %d, %Y')}\n"
        f"• {tomorrow_display}"
    )


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_to_google_chat(message):
    if not WEBHOOK_URL:
        print("[CHAT] GOOGLE_CHAT_WEBHOOK is not set.")
        print(message)
        return False

    try:
        response = requests.post(
            WEBHOOK_URL,
            json={"text": message},
            timeout=20,
        )

        response.raise_for_status()

        print("[CHAT] Message sent successfully.")
        return True

    except Exception as e:
        print(f"[CHAT] Failed to send message: {e}")
        return False


# ============================================================
# MAIN
# ============================================================

def check_once():
    today = get_ph_date()

    print()
    print("=" * 60)
    print(
        f"School status check — "
        f"{today.strftime('%B %d, %Y')}"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # TODAY: Calendar
    # --------------------------------------------------------

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
            f"[TODAY] No School — {calendar_reason}"
        )

    else:
        # ----------------------------------------------------
        # QC
        # ----------------------------------------------------

        qc_result = check_qc_government_feed(today)

        print(
            f"[DEBUG] QC private suspended: "
            f"{qc_result['private_suspended']}"
        )

        print(
            f"[DEBUG] QC alternative delivery: "
            f"{qc_result['alternative_delivery']}"
        )

        # ----------------------------------------------------
        # PAGASA
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Ateneo
        # ----------------------------------------------------

        (
            ateneo_soup,
            advisory_date,
            advisory_text,
        ) = get_recent_ateneo_advisory(today)

        if advisory_soup := ateneo_soup:
            statuses = get_statuses(
                advisory_soup
            )
        else:
            statuses = {
                "ags": "Onsite",
                "jhs": "Onsite",
                "shs": "Onsite",
            }

        # ----------------------------------------------------
        # Facebook
        # ----------------------------------------------------

        facebook_suspension = (
            check_facebook_private_suspension()
        )

        print(
            f"[DEBUG] Facebook private suspension: "
            f"{facebook_suspension}"
        )

        # ----------------------------------------------------
        # DECISION ENGINE
        # ----------------------------------------------------

        private_suspended = (
            qc_result["private_suspended"]
            or facebook_suspension
        )

        # IMPORTANT:
        #
        # Private-school suspension alone:
        #     -> No School
        #
        # Private-school suspension + Alternative Delivery:
        #     -> Alternative Delivery wins
        #     -> inspect Ateneo advisory instead
        #
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
                "without alternative delivery -> No School"
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
                    "signal -> using recent Ateneo advisory"
                )

            else:
                statuses = {
                    "ags": "Unknown",
                    "jhs": "Unknown",
                    "shs": "Unknown",
                }

                print(
                    "[TODAY] Signal detected but no recent "
                    "Ateneo advisory found."
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
                "[TODAY] No relevant advisory -> Onsite"
            )

    # --------------------------------------------------------
    # TOMORROW GUESS
    # --------------------------------------------------------

    (
        tomorrow_guess,
        tomorrow_confidence,
        guess_reasons,
        guess_scores,
    ) = guess_tomorrow_status(today)

    tomorrow_display = format_guessed_status(
        tomorrow_guess,
        tomorrow_confidence,
    )

    print()
    print("=" * 60)
    print("TOMORROW GUESS")
    print("=" * 60)

    print(f"Guess: {tomorrow_display}")

    print()
    print("Scores:")

    for status, score in guess_scores.items():
        print(f"  {status}: {score}")

    print()
    print("Reasons:")

    if guess_reasons:
        for reason in guess_reasons:
            print(f"  - {reason}")
    else:
        print("  - No useful public information found.")

    print("=" * 60)

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = create_message(
        today,
        statuses,
        tomorrow_guess,
        tomorrow_confidence,
    )

    print()
    print(message)
    print()

    send_to_google_chat(message)


if __name__ == "__main__":
    check_once()
