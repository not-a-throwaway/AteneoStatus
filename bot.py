import os,re,sys,datetime
from datetime import timedelta
from zoneinfo import ZoneInfo
import requests,holidays
from bs4 import BeautifulSoup

ADVISORIES_URL="https://www.ateneo.edu/advisories"
FACEBOOK_URL="https://www.facebook.com/ateneodemanila/"
WEBHOOK_URL=os.environ.get("GOOGLE_CHAT_WEBHOOK")
FACEBOOK_LOOKBACK_DAYS=14
PH_TIMEZONE=ZoneInfo("Asia/Manila")
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"})
MONTH_PATTERN=r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"

SCHOOL_ALIASES={
    "AGS":["Ateneo Grade School","Ateneo Grade School (AGS)","AGS"],
    "JHS":["Ateneo Junior High School","Ateneo Junior High School (AJHS)","AJHS","JHS"],
    "SHS":["Ateneo Senior High School","Ateneo Senior High School (ASHS)","ASHS","SHS"]
}

def fetch(url,timeout=30):
    r=SESSION.get(url,timeout=timeout)
    r.raise_for_status()
    return r

def get_ph_date():
    return datetime.datetime.now(PH_TIMEZONE).date()

def format_date(x):
    return x.strftime("%B ")+str(x.day)

def normalize_month(x):
    return {
        "jan":"Jan","january":"January",
        "feb":"Feb","february":"February",
        "mar":"Mar","march":"March",
        "apr":"Apr","april":"April",
        "may":"May",
        "jun":"Jun","june":"June",
        "jul":"Jul","july":"July",
        "aug":"Aug","august":"August",
        "sep":"Sep","sept":"Sep","september":"September",
        "oct":"Oct","october":"October",
        "nov":"Nov","november":"November",
        "dec":"Dec","december":"December"
    }.get(x.lower().strip())

def parse_single_date(day,month,year):
    m=normalize_month(month)
    if not m:return
    for f in("%d %b %Y","%d %B %Y"):
        try:
            return datetime.datetime.strptime(f"{day} {m} {year}",f).date()
        except ValueError:
            pass

def parse_date_from_text(text):
    p=(
        rf"\b({MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})\b"
    )
    z=[]
    for i,x in enumerate(p):
        for m in re.finditer(x,text,re.I):
            a,b,c=m.groups()
            v=parse_single_date(b,a,c) if i==0 else parse_single_date(a,b,c)
            if v:z.append(v)
    return z

def check_ph_calendar(x):
    if x.weekday()>=5:return True,"Weekend"

    z={
        (8,21):"Ninoy Aquino Day",
        (11,1):"All Saints' Day",
        (12,8):"Feast of the Immaculate Conception",
        (12,24):"Christmas Eve",
        (12,31):"Last Day of the Year"
    }

    if(x.month,x.day)in z:
        return True,"Philippine special non-working day: "+z[x.month,x.day]

    h=holidays.country_holidays("PH",years=x.year)
    return(True,f"Philippine holiday: {h.get(x)}")if x in h else(False,None)

def fetch_advisories():
    return BeautifulSoup(fetch(ADVISORIES_URL).text,"html.parser")

def get_page_text(s):
    for x in s(["script","style","noscript","svg"]):
        x.decompose()
    return s.get_text("\n",strip=True)

def find_class_arrangements_date(s):
    text=get_page_text(s)

    m=re.search(
        r"Class Arrangements.{0,1000}?Last Updated on.{0,100}?"
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",
        text,re.I|re.S
    )

    if m and(v:=parse_single_date(*m.groups())):
        return v

    z=[
        parse_single_date(*x)
        for x in re.findall(
            r"Last Updated on.{0,100}?"
            rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",
            text,re.I|re.S
        )
    ]

    if z:
        print("[WARNING] Could not specifically identify Class Arrangements update date.")
        print("[WARNING] Using newest 'Last Updated' date.")
        return max(z)

    raise RuntimeError("Could not find an Ateneo Class Arrangements update date.")

def find_school_position(text,school):
    z=[]

    for alias in SCHOOL_ALIASES[school]:
        if m:=re.search(rf"\b{re.escape(alias)}\b",text,re.I):
            z.append((m.start(),m.end(),alias))

    return min(z,key=lambda x:x[0]) if z else None

def get_school_section(text,school):
    p=find_school_position(text,school)

    if not p:
        print(f"[WARNING] Could not find {school} section.")
        return ""

    start,end,alias=p
    boundaries=[]

    for other in SCHOOL_ALIASES:
        if other==school:
            continue

        p=find_school_position(text[end:],other)

        if p:
            boundaries.append(end+p[0])

    for boundary in("University Operations","Higher Education"):
        if m:=re.search(re.escape(boundary),text[end:],re.I):
            boundaries.append(end+m.start())

    section=text[start:min(boundaries or[len(text)])].strip()

    print(f"[DEBUG] {school} matched alias: {alias}")
    return section

def classify(text):
    if not text:
        return "Unknown"

    text=text.lower()


    async_patterns=(
        r"\basynchronous online\b",
        r"\bonline asynchronous\b",
        r"\basynchronous modality\b",
        r"\basynchronous classes?\b",
        r"\basynchronous period\b",
        r"\basynchronous instruction\b",
        r"\basynchronous learning\b",
        r"\basynchronous activities\b",
        r"\bshift(?:ing)? to asynchronous\b",
        r"\basync(?:hronous)? online\b"
    )

    sync_patterns=(
        r"\bsynchronous online\b",
        r"\bonline synchronous\b",
        r"\bsynchronous classes?\b",
        r"\bsynchronous session\b",
        r"\bsynchronous instruction\b",
        r"\bsynchronous modality\b",
        r"\bsynchronous learning\b",
        r"\bshift(?:ing)? to synchronous\b",
        r"\bsync(?:hronous)? online\b"
    )

    async_hits=[m for p in async_patterns if(m:=re.search(p,text))]
    sync_hits=[m for p in sync_patterns if(m:=re.search(p,text))]


    if async_hits and sync_hits:
        a=min(async_hits,key=lambda x:x.start())
        s=min(sync_hits,key=lambda x:x.start())

        before=text[max(0,min(a.start(),s.start())-150):min(len(text),max(a.end(),s.end())+150)]

        if re.search(r"(asynchronous).{0,80}(online|modality|classes|instruction|learning)",before,re.S):
            if not re.search(r"(synchronous).{0,80}(online|modality|classes|instruction|learning)",before,re.S):
                return "Asynchronous Online"

        if re.search(r"(synchronous).{0,80}(online|modality|classes|instruction|learning)",before,re.S):
            if not re.search(r"(asynchronous).{0,80}(online|modality|classes|instruction|learning)",before,re.S):
                return "Synchronous Online"

        return "Asynchronous Online" if a.start()<s.start() else "Synchronous Online"

    if async_hits:
        return "Asynchronous Online"

    if sync_hits:
        return "Synchronous Online"

    online_patterns=(
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
        r"\bshift to online\b"
    )

    if any(re.search(p,text)for p in online_patterns):
        return "Online"

    suspension_patterns=(
        r"\bclasses are suspended\b",
        r"\bclasses have been suspended\b",
        r"\bclasses remain suspended\b",
        r"\bclass suspension is in effect\b",
        r"\ball classes are suspended\b",
        r"\bclasses are cancelled\b",
        r"\bclasses are canceled\b",
        r"\bno classes will be held\b",
        r"\bno classes today\b",
        r"\bwalang pasok\b"
    )

    if any(re.search(p,text)for p in suspension_patterns):
        return "Suspension"

    onsite_patterns=(
        r"\bonsite classes\b",
        r"\bon-site classes\b",
        r"\bface-to-face classes\b",
        r"\bface to face classes\b",
        r"\bf2f classes\b",
        r"\bonsite instruction\b",
        r"\bclasses.*resume.*onsite\b",
        r"\bresume.*onsite classes\b"
    )

    if any(re.search(p,text)for p in onsite_patterns):
        return "Onsite"

    return "Unknown"

def get_statuses(soup):
    text=get_page_text(soup)
    statuses={}

    for school in("AGS","JHS","SHS"):
        section=get_school_section(text,school)
        statuses[school]=classify(section)

        print(f"[DEBUG] {school}: {statuses[school]}")
        print(f"[DEBUG] {school} section:")
        print(section[:500])
        print("-"*40)

    return statuses

def check_qc_government_feed(target_date):
    urls=(
        "https://quezoncity.gov.ph/feed/",
        "https://quezoncity.gov.ph/news/"
    )

    dates={
        f"{target_date:%B} {target_date.day} {target_date.year}".lower(),
        f"{target_date:%B} {target_date.day}".lower(),
        f"{target_date:%b} {target_date.day} {target_date.year}".lower(),
        f"{target_date.day} {target_date:%B} {target_date.year}".lower(),
        f"{target_date:%B}-{target_date.day}-{target_date.year}".lower(),
        f"{target_date:%B} {target_date.day}, {target_date.year}".lower()
    }

    suspension=("suspendido","walang pasok","suspended","suspension","no classes")
    private=("private schools","private school","pribadong paaralan","pribadong school")

    def inspect(text,title=""):
        text=(title+" "+text).lower()

        if not any(x in text for x in dates):
            return

        if not any(x in text for x in suspension):
            return

        if not any(x in text for x in private):
            return

        return True,"Private-school suspension: "+title

    for url in urls:
        try:
            soup=BeautifulSoup(fetch(url,10).text,"xml"if"feed"in url else"html.parser")

            for item in soup.find_all("item"if"feed"in url else"a"):
                title=item.title.get_text(" ",strip=True)if item.title else item.get_text(" ",strip=True)
                description=item.description.get_text(" ",strip=True)if getattr(item,"description",None)else item.get("href","")

                if result:=inspect(description,title):
                    return result

        except Exception as e:
            print(f"QC check failed: {e}",file=sys.stderr)

    return False,"No matching private-school suspension."

def check_pagasa_bulletin(target_date):
    try:
        text=fetch("https://bagong.pagasa.dost.gov.ph/weather",10).text.lower()

        if("metro manila"in text or"quezon city"in text)and("red rainfall warning"in text or"orange rainfall warning"in text):
            return True,"PAGASA Orange/Red rainfall warning mentioned."

        return False,"No relevant PAGASA trigger."

    except Exception as e:
        print(f"PAGASA check failed: {e}",file=sys.stderr)
        return False,"PAGASA check failed."

def check_facebook(target_date):
    cutoff=target_date-timedelta(days=FACEBOOK_LOOKBACK_DAYS)

    try:
        response=SESSION.get(FACEBOOK_URL,timeout=20)

        if response.status_code!=200:
            print(f"Facebook returned HTTP {response.status_code}")
            return

        soup=BeautifulSoup(response.text,"html.parser")
        raw=soup.get_text(" ",strip=True).lower()

        if"login"in raw and len(raw)<5000:
            print("Facebook returned a login page.")
            return

        for tag in soup(["script","style","noscript"]):
            tag.decompose()

        content=soup.get_text("\n",strip=True)
        lower=content.lower()

        private=("private schools","private school","pribadong paaralan")
        suspension=("suspended","suspension","suspendido","walang pasok","no classes")

        if not any(x in lower for x in private):
            return

        if not any(x in lower for x in suspension):
            return

        dates=[
            x for x in parse_date_from_text(content)
            if cutoff<=x<=target_date
        ]

        if dates:
            return {
                "private_suspended":True,
                "date":max(dates),
                "reason":"Facebook private-school suspension detected."
            }

    except Exception as e:
        print(f"Facebook check failed: {e}",file=sys.stderr)

def status_icon(status):
    return{
        "Synchronous Online":"🟢",
        "Asynchronous Online":"🟢",
        "Mixed Online":"🟢",
        "Online":"🟢",
        "Suspension":"🔴",
        "No School":"❌",
        "Onsite":"🔵",
        "Unknown":"🟡"
    }.get(status,"🟡")

def create_message(date,statuses,reason=None,reason_type=None):
    next_date=date+timedelta(days=1)
    date1=format_date(date)
    date2=format_date(next_date)

    lines=[
        "Yall heres the school status :D",
        "",
        f"this is for: *{date1}* and *{date2}*",
        "",
        f"*School* | *{date1}* | *{date2}*",
        "--------------------------------"
    ]

    for school in("AGS","JHS","SHS"):
        lines.append(
            f"*{school}* | "
            f"{status_icon(statuses[school])} "
            f"{statuses[school]} | 🟡 Unknown"
        )

    if reason:
        lines.extend([
            "",
            "🚨 *NO CLASSES.*" if reason_type=="calendar"
            else "🚨 *Private schools are suspended.*",
            reason
        ])

    lines.extend([
        "",
        f"🔗 {ADVISORIES_URL}"
    ])

    return"\n".join(lines)

def send_to_google_chat(message):
    if not WEBHOOK_URL:
        raise RuntimeError("GOOGLE_CHAT_WEBHOOK secret is not set.")

    SESSION.post(
        WEBHOOK_URL,
        json={"text":message},
        timeout=30
    ).raise_for_status()

def check_once():
    today=get_ph_date()

    calendar_no_classes,calendar_reason=check_ph_calendar(today)

    if calendar_no_classes:
        statuses={x:"No School"for x in("AGS","JHS","SHS")}

        send_to_google_chat(
            create_message(
                today,
                statuses,
                calendar_reason,
                "calendar"
            )
        )
        return

    soup=fetch_advisories()
    advisory_date=find_class_arrangements_date(soup)

    if advisory_date==today:
        statuses=get_statuses(soup)
    else:
        statuses={x:"Onsite"for x in("AGS","JHS","SHS")}

    qc_private,qc_reason=check_qc_government_feed(today)
    facebook_result=check_facebook(today)

    private_suspended=qc_private or bool(facebook_result)

    reason=None
    reason_type=None

    if private_suspended:
        statuses={x:"No School"for x in("AGS","JHS","SHS")}
        reason=qc_reason if qc_private else facebook_result["reason"]
        reason_type="suspension"

    send_to_google_chat(
        create_message(
            today,
            statuses,
            reason,
            reason_type
        )
    )

if __name__=="__main__":
    try:
        check_once()
    except Exception as error:
        print(f"ERROR: {error}",file=sys.stderr)
        sys.exit(1)
