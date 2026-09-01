
import os,re,datetime as D
from datetime import timedelta as T
from zoneinfo import ZoneInfo as Z
import requests,holidays
from bs4 import BeautifulSoup as B

A="https://www.ateneo.edu/advisories";F="https://www.facebook.com/ateneodemanila/";W=os.getenv("GOOGLE_CHAT_WEBHOOK");Q=Z("Asia/Manila");S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
M=r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
X={"AGS":"Ateneo Grade School|AGS","JHS":"Ateneo Junior High School|AJHS|JHS","SHS":"Ateneo Senior High School|ASHS|SHS"}
O=lambda u,t=30:(lambda r:(r.raise_for_status(),r)[1])(S.get(u,timeout=t))
N=lambda x:{"jan":"Jan","january":"January","feb":"Feb","february":"February","mar":"Mar","march":"March","apr":"Apr","april":"April","may":"May","jun":"Jun","june":"June","jul":"Jul","july":"July","aug":"Aug","august":"August","sep":"Sep","sept":"Sep","september":"September","oct":"Oct","october":"October","nov":"Nov","november":"November","dec":"Dec","december":"December"}.get(x.lower())
P=lambda a,m,y:next((D.datetime.strptime(f"{a} {N(m)} {y}",f).date()for f in("%d %b %Y","%d %B %Y")if N(m)),None)
R=lambda s:sum(([P(*(z.groups()[::-1] if i else z.groups()))]for i,p in enumerate((rf"\b({M})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",rf"\b(\d{{1,2}})\s+({M})\s+(\d{{4}})\b"))for z in re.finditer(p,s,re.I)),[])

def tx(s):
 [x.decompose()for x in s(["script","style","noscript","svg"])]
 return s.get_text("\n",strip=True)

def sec(t,k):
 q=re.search(r"\b(?:"+X[k]+r")\b",t,re.I)
 if not q:return""
 e=q.end();z=[e]
 for j in X:
  j!=k and (m:=re.search(r"\b(?:"+X[j]+r")\b",t[e:],re.I))and z.append(e+m.start())
 for j in("University Operations","Higher Education"):
  (m:=re.search(j,t[e:],re.I))and z.append(e+m.start())
 return t[q.start():min(z)].strip()

def st(x):
 x=x.lower()
 a=any(re.search(p,x)for p in("synchronous online","online synchronous","synchronous classes?","synchronous session","synchronous instruction","synchronous modality","synchronous learning","shifting to synchronous","shift to synchronous"))
 b=any(re.search(p,x)for p in("asynchronous online","online asynchronous","asynchronous modality","asynchronous classes?","asynchronous period","asynchronous tasks?","asynchronous instruction","asynchronous work","asynchronous learning","asynchronous activities","shifting to asynchronous","shift to asynchronous"))
 return "Mixed Online"if a and b else"Synchronous Online"if a else"Asynchronous Online"if b else"Online"if any(re.search(p,x)for p in("online classes","online class","online modality","online instruction","virtual classes","virtual instruction","remote learning","remote classes","classes will be conducted online","classes remain online","shifting to online","shift to online"))else"Suspension"if any(re.search(p,x)for p in("classes are suspended","classes have been suspended","classes remain suspended","class suspension is in effect","all classes are suspended","classes are cancelled","classes are canceled","no classes will be held","no classes today","walang pasok"))else"Onsite"if any(re.search(p,x)for p in("onsite classes","on-site classes","face-to-face classes","face to face classes","f2f classes","onsite instruction","classes.*resume.*onsite","resume.*onsite classes"))else"Unknown"

def cal(x):
 if x.weekday()>4:return 1,"Weekend"
 z={(8,21):"Ninoy Aquino Day",(11,1):"All Saints' Day",(12,8):"Feast of the Immaculate Conception",(12,24):"Christmas Eve",(12,31):"Last Day of the Year"}
 if(x.month,x.day)in z:return 1,"Philippine special non-working day: "+z[x.month,x.day]
 h=holidays.country_holidays("PH",years=x.year)
 return(1,"Philippine holiday: "+h.get(x))if x in h else(0,None)

def qc(x):
 ds={x.strftime(f).lower()for f in("%B %-d %Y","%B %-d","%b %-d %Y","%-d %B %Y","%B-%-d-%Y","%B %-d, %Y")}
 def f(t):
  t=t.lower()
  return"Private-school suspension: "+t[:100]if any(a in t for a in ds)and any(a in t for a in("suspendido","walang pasok","suspended","suspension","no classes"))and any(a in t for a in("private schools","private school","pribadong paaralan","pribadong school"))else None
 for u in("https://quezoncity.gov.ph/feed/","https://quezoncity.gov.ph/news/"):
  try:
   s=B(O(u,10).text,"xml"if"feed"in u else"html.parser")
   for i in s.find_all("item"if"feed"in u else"a"):
    if z:=f(i.get_text(" ",strip=True)+" "+i.get("href","")):return 1,z
  except:pass
 return 0,None

def fb(x):
 try:
  s=B(S.get(F,timeout=20).text,"html.parser");t=s.get_text(" ",strip=True)
  if"login"in t.lower()and len(t)<5000:return
  [z.decompose()for z in s(["script","style","noscript"])]
  t=s.get_text(" ",strip=True)
  if not any(a in t.lower()for a in("private schools","private school","pribadong paaralan"))or not any(a in t.lower()for a in("suspended","suspension","suspendido","walang pasok","no classes")):return
  z=[a for a in R(t)if x-T(14)<=a<=x]
  return(1,"Facebook private-school suspension detected.")if z else None
 except:pass

def icon(x):return{"Synchronous Online":"🟢","Asynchronous Online":"🟢","Mixed Online":"🟢","Online":"🟢","Suspension":"🔴","No School":"❌","Onsite":"🔵"}.get(x,"🟡")

def send(x):S.post(W,json={"text":x},timeout=30).raise_for_status()

def main():
 x=D.datetime.now(Q).date();n,r=cal(x)
 if n:s={k:"No School"for k in X};return send("\n".join(["Yall heres the school status :D","",f"this is for: *{x:%B} {x.day}* and *{(x+T(1)):%B} {(x+T(1)).day}*","",f"*School* | *{x:%B} {x.day}* | *{(x+T(1)):%B} {(x+T(1)).day}*","--------------------------------"]+[f"*{k}* | ❌ No School | 🟡 Unknown"for k in X]+["","🚨 *NO CLASSES.*",r,"",f"🔗 {A}"]))
 a=B(O(A).text,"html.parser");t=tx(a)
 m=re.search(r"Class Arrangements.{0,1000}?Last Updated on.{0,100}?"rf"(\d{{1,2}})\s+({M})\s+(\d{{4}})",t,re.I|re.S)
 s={k:st(sec(t,k))for k in X}if m and P(*m.groups())==x else{k:"Onsite"for k in X}
 n,r=qc(x);f=fb(x)
 if n or f:s={k:"No School"for k in X};r=r if n else f[1]
 y=x+T(1);z=[f"Yall heres the school status :D","",f"this is for: *{x:%B} {x.day}* and *{y:%B} {y.day}*","",f"*School* | *{x:%B} {x.day}* | *{y:%B} {y.day}*","--------------------------------"]+[f"*{k}* | {icon(s[k])} {s[k]} | 🟡 Unknown"for k in X]
 if r:z+=["","🚨 *Private schools are suspended.*"if n or f else"",r]
 send("\n".join(z+["",f"🔗 {A}"]))

try:main()
except Exception as e:print("ERROR:",e);raise
