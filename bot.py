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

def fetch(url,timeout=30):
 r=SESSION.get(url,timeout=timeout);r.raise_for_status();return r

def get_ph_date():return datetime.datetime.now(PH_TIMEZONE).date()
def format_date(x):return x.strftime("%B ")+str(x.day)

def normalize_month(x):
 return {"jan":"Jan","january":"January","feb":"Feb","february":"February","mar":"Mar","march":"March","apr":"Apr","april":"April","may":"May","jun":"Jun","june":"June","jul":"Jul","july":"July","aug":"Aug","august":"August","sep":"Sep","sept":"Sep","september":"September","oct":"Oct","october":"October","nov":"Nov","november":"November","dec":"Dec","december":"December"}.get(x.lower().strip())

def parse_single_date(day,month,year):
 m=normalize_month(month)
 if not m:return
 for f in("%d %b %Y","%d %B %Y"):
  try:return datetime.datetime.strptime(f"{day} {m} {year}",f).date()
  except ValueError:pass

def parse_date_from_text(text):
 p=(rf"\b({MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})\b");z=[]
 for i,x in enumerate(p):
  for m in re.finditer(x,text,re.I):
   a,b,c=m.groups();v=parse_single_date(b,a,c)if i==0 else parse_single_date(a,b,c)
   if v:z.append(v)
 return z

def check_ph_calendar(x):
 if x.weekday()>=5:return True,"Weekend"
 z={(8,21):"Ninoy Aquino Day",(11,1):"All Saints' Day",(12,8):"Feast of the Immaculate Conception",(12,24):"Christmas Eve",(12,31):"Last Day of the Year"}
 if(x.month,x.day)in z:return True,"Philippine special non-working day: "+z[x.month,x.day]
 h=holidays.country_holidays("PH",years=x.year)
 return(True,f"Philippine holiday: {h.get(x)}")if x in h else(False,None)

def fetch_advisories():return BeautifulSoup(fetch(ADVISORIES_URL).text,"html.parser")

def get_page_text(s):
 for x in s(["script","style","noscript","svg"]):x.decompose()
 return s.get_text("\n",strip=True)

def find_class_arrangements_date(s):
 t=get_page_text(s)
 m=re.search(r"Class Arrangements.{0,1000}?Last Updated on.{0,100}?"rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",t,re.I|re.S)
 if m and(v:=parse_single_date(*m.groups())):return v
 z=[parse_single_date(*x)for x in re.findall(r"Last Updated on.{0,100}?"rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})",t,re.I|re.S)]
 if z:return max(z)
 raise RuntimeError("Could not find an Ateneo Class Arrangements update date.")

SCHOOL_ALIASES={"AGS":["Ateneo Grade School","Ateneo Grade School (AGS)","AGS"],"JHS":["Ateneo Junior High School","Ateneo Junior High School (AJHS)","AJHS","JHS"],"SHS":["Ateneo Senior High School","Ateneo Senior High School (ASHS)","ASHS","SHS"]}

def find_school_position(t,k):
 z=[]
 for a in SCHOOL_ALIASES[k]:
  if m:=re.search(rf"\b{re.escape(a)}\b",t,re.I):z.append((m.start(),m.end(),a))
 return min(z,key=lambda x:x[0])if z else None

def get_school_section(t,k):
 p=find_school_position(t,k)
 if not p:return""
 s,e,a=p;z=[]
 for j in SCHOOL_ALIASES:
  if j!=k and(p:=find_school_position(t[e:],j)):z.append(e+p[0])
 for j in("University Operations","Higher Education"):
  if m:=re.search(re.escape(j),t[e:],re.I):z.append(e+m.start())
 print(f"[DEBUG] {k} matched alias: {a}")
 return t[s:min(z or[len(t)])].strip()

def classify(t):
 if not t:return"Unknown"
 t=t.lower()
 y=lambda p:any(re.search(x,t)for x in p)
 a=y(("synchronous online","online synchronous","synchronous classes?","synchronous session","synchronous instruction","synchronous modality","synchronous learning","shifting to synchronous","shift to synchronous"))
 b=y(("asynchronous online","online asynchronous","asynchronous modality","asynchronous classes?","asynchronous period","asynchronous tasks?","asynchronous instruction","asynchronous work","asynchronous learning","asynchronous activities","shifting to asynchronous","shift to asynchronous"))
 if a and b:return"Mixed Online"
 if a:return"Synchronous Online"
 if b:return"Asynchronous Online"
 if y(("online classes","online class","online modality","online instruction","virtual classes","virtual instruction","remote learning","remote classes","classes will be conducted online","classes remain online","shifting to online","shift to online")):return"Online"
 if y(("classes are suspended","classes have been suspended","classes remain suspended","class suspension is in effect","all classes are suspended","classes are cancelled","classes are canceled","no classes will be held","no classes today","walang pasok")):return"Suspension"
 if y(("onsite classes","on-site classes","face-to-face classes","face to face classes","f2f classes","onsite instruction","classes.*resume.*onsite","resume.*onsite classes")):return"Onsite"
 return"Unknown"

def get_statuses(s):
 t=get_page_text(s);z={}
 for k in("AGS","JHS","SHS"):
  z[k]=classify(get_school_section(t,k))
  print(f"[DEBUG] {k}: {z[k]}")
 return z

def check_qc_government_feed(x):
 u=("https://quezoncity.gov.ph/feed/","https://quezoncity.gov.ph/news/")
 d={f"{x:%B} {x.day} {x.year}".lower(),f"{x:%B} {x.day}".lower(),f"{x:%b} {x.day} {x.year}".lower(),f"{x.day} {x:%B} {x.year}".lower(),f"{x:%B}-{x.day}-{x.year}".lower(),f"{x:%B} {x.day}, {x.year}".lower()}
 s=("suspendido","walang pasok","suspended","suspension","no classes");p=("private schools","private school","pribadong paaralan","pribadong school")
 def ck(t,h=""):
  t=(h+" "+t).lower()
  return(1,"Private-school suspension: "+h)if any(a in t for a in d)and any(a in t for a in s)and any(a in t for a in p)else None
 for q in u:
  try:
   z=BeautifulSoup(fetch(q,10).text,"xml"if"feed"in q else"html.parser")
   for i in z.find_all("item"if"feed"in q else"a"):
    h=i.title.get_text(" ",strip=True)if i.title else i.get_text(" ",strip=True);v=i.description.get_text(" ",strip=True)if getattr(i,"description",None)else i.get("href","")
    if r:=ck(v,h):return r
  except Exception as e:print(f"QC check failed: {e}",file=sys.stderr)
 return False,"No matching private-school suspension."

def check_pagasa_bulletin(x):
 try:
  t=fetch("https://bagong.pagasa.dost.gov.ph/weather",10).text.lower()
  return(True,"PAGASA Orange/Red rainfall warning mentioned.")if("metro manila"in t or"quezon city"in t)and("red rainfall warning"in t or"orange rainfall warning"in t)else(False,"No relevant PAGASA trigger.")
 except Exception as e:print(f"PAGASA check failed: {e}",file=sys.stderr);return False,"PAGASA check failed."

def check_facebook(x):
 try:
  s=BeautifulSoup(SESSION.get(FACEBOOK_URL,timeout=20).text,"html.parser");t=s.get_text(" ",strip=True).lower()
  if"login"in t and len(t)<5000:return
  for z in s(["script","style","noscript"]):z.decompose()
  t=s.get_text("\n",strip=True);l=t.lower()
  if not any(a in l for a in("private schools","private school","pribadong paaralan"))or not any(a in l for a in("suspended","suspension","suspendido","walang pasok","no classes")):return
  z=[a for a in parse_date_from_text(t)if x-timedelta(days=FACEBOOK_LOOKBACK_DAYS)<=a<=x]
  return{"private_suspended":True,"date":max(z),"reason":"Facebook private-school suspension detected."}if z else None
 except Exception as e:print(f"Facebook check failed: {e}",file=sys.stderr)

def status_icon(x):return{"Synchronous Online":"🟢","Asynchronous Online":"🟢","Mixed Online":"🟢","Online":"🟢","Suspension":"🔴","No School":"❌","Onsite":"🔵"}.get(x,"🟡")

def create_message(x,s,r=None,t=None):
 y=x+timedelta(1);a,b=format_date(x),format_date(y)
 z=["Yall heres the school status :D","",f"this is for: *{a}* and *{b}*","",f"*School* | *{a}* | *{b}*","--------------------------------"]+[f"*{k}* | {status_icon(s[k])} {s[k]} | 🟡 Unknown"for k in("AGS","JHS","SHS")]
 if r:z+=["",("🚨 *NO CLASSES.*"if t=="calendar"else"🚨 *Private schools are suspended.*"),r]
 return"\n".join(z+["",f"🔗 {ADVISORIES_URL}"])

def send_to_google_chat(x):
 if not WEBHOOK_URL:raise RuntimeError("GOOGLE_CHAT_WEBHOOK secret is not set.")
 SESSION.post(WEBHOOK_URL,json={"text":x},timeout=30).raise_for_status()

def check_once():
 x=get_ph_date();n,r=check_ph_calendar(x)
 if n:
  s={k:"No School"for k in("AGS","JHS","SHS")}
  return send_to_google_chat(create_message(x,s,r,"calendar"))
 s=get_statuses(fetch_advisories())if find_class_arrangements_date(a:=fetch_advisories())==x else{k:"Onsite"for k in("AGS","JHS","SHS")}
 q,qr=check_qc_government_feed(x);f=check_facebook(x)
 if q or f:s={k:"No School"for k in("AGS","JHS","SHS")};r=qr if q else f["reason"]
 else:r=None
 send_to_google_chat(create_message(x,s,r,"suspension"if q or f else None))

if __name__=="__main__":
 try:check_once()
 except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(1)
