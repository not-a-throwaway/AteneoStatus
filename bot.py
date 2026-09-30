AU='suspension ng klase'
AT='walang pasok'
AS='classes suspended'
AR='face-to-face'
AQ='regular classes'
AP='classes will proceed as usual'
AO='on-site classes'
AN='onsite classes'
AM='face to face classes'
AL='face-to-face classes'
AK='classes will be suspended'
AJ='online learning'
AI='alternative delivery mode'
AH='alternative delivery modes'
AG='asynchronous modality'
AF='asynchronous classes'
AE='asynchronous learning'
AD='asynchronous online'
AC='live online classes'
AB='synchronous modality'
AA='synchronous classes'
A9='synchronous learning'
A8='synchronous online'
u='reason'
t='suspended'
s='private_school'
r='href'
q='no classes'
p='class suspension'
o='online classes'
n=list
j='suspension of classes'
i='classes are suspended'
h='online modality'
g='%B %d, %Y'
f=Exception
c='asynchronous'
b='synchronous'
a='alternative delivery'
Z=max
X='private_suspended'
W='xml'
U='date'
T='title'
R='url'
Q='Unknown'
P='Onsite'
O='Asynchronous Online'
N='alternative_delivery'
M=''
L='shs'
K='jhs'
J='ags'
I='Synchronous Online'
H='No School'
G=' '
E=False
D=any
C=True
B=None
A=print
import os,re
from datetime import datetime as v,timedelta as d
from urllib.parse import urlparse as AV
import feedparser as AW,holidays as AX,requests as w
from bs4 import BeautifulSoup as V
from zoneinfo import ZoneInfo as AY
AZ='https://www.ateneo.edu/advisories'
Aa='https://www.facebook.com/ateneodemanila/'
x='https://quezoncity.gov.ph/feed/'
Ab='https://quezoncity.gov.ph/news/'
y='https://quezoncity.gov.ph/news-and-media/announcements/'
Ac='https://bagong.pagasa.dost.gov.ph/regional-forecast/ncrprsd'
z=os.environ.get('GOOGLE_CHAT_WEBHOOK')
Aq=14
Ad=7
Ae=3
Af=AY('Asia/Manila')
Ag={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'}
Ah={J:['Ateneo Grade School','Ateneo de Manila Grade School','Grade School','AGS'],K:['Ateneo Junior High School','Ateneo de Manila Junior High School','Junior High School','AJHS','JHS'],L:['Ateneo Senior High School','Ateneo de Manila Senior High School','Senior High School','ASHS','SHS']}
def S(url,timeout=20):
	try:B=w.get(url,headers=Ag,timeout=timeout);B.raise_for_status();return B
	except f as C:A(f"[ERROR] Failed to fetch {url}: {C}");return
def F(text):return re.sub('\\s+',G,text or M).strip()
def k():return v.now(Af).date()
def Ai(value):
	A=value
	if not A:return
	A=F(A);B=[g,'%b %d, %Y','%B %d %Y','%b %d %Y','%Y-%m-%d','%m/%d/%Y','%m-%d-%Y','%d/%m/%Y','%d-%m-%Y']
	for C in B:
		try:return v.strptime(A,C).date()
		except ValueError:pass
def l(text):
	if not text:return[]
	C=['\\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}\\b','\\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\\.?\\s+\\d{1,2},\\s+\\d{4}\\b','\\b\\d{4}-\\d{2}-\\d{2}\\b','\\b\\d{1,2}/\\d{1,2}/\\d{4}\\b'];A=[]
	for D in C:
		for E in re.findall(D,text,flags=re.I):
			B=Ai(E)
			if B:A.append(B)
	return A
def Aj(text,target_date,days=1):A=l(text);return[A for A in A if abs((A-target_date).days)<=days]
def A0(target_date):
	D=target_date
	if D.weekday()>=5:return C,'Weekend'
	F={(1,1):"New Year's Day",(4,9):'Araw ng Kagitingan',(5,1):'Labor Day',(6,12):'Independence Day',(8,21):'Ninoy Aquino Day',(8,31):'National Heroes Day',(11,1):"All Saints' Day",(11,2):"All Souls' Day",(11,30):'Bonifacio Day',(12,8):'Feast of the Immaculate Conception',(12,24):'Christmas Eve',(12,25):'Christmas Day',(12,30):'Rizal Day',(12,31):'Last Day of the Year'}
	if(D.month,D.day)in F:return C,F[D.month,D.day]
	try:
		G=AX.country_holidays('PH',years=[D.year])
		if D in G:return C,G.get(D)
	except f as H:A(f"[CALENDAR] Holiday lookup failed: {H}")
	return E,B
def A1(text):
	A=text;A=F(A).lower()
	if D(B in A for B in[A8,A9,AA,AB,AC]):return I
	if D(B in A for B in[AD,AE,AF,AG]):return O
	if D(B in A for B in[AH,AI,a]):
		if b in A:return I
		if c in A:return O
	if D(B in A for B in[h,o,AJ,'classes will be held online','learning will be conducted online']):return I
	if D(B in A for B in[i,AK,j,p,q,'classes cancelled','classes canceled']):return H
	if D(B in A for B in[AL,AM,AN,AO,AP,AQ]):return P
def A2(soup,school):
	Q=Ah[school];H=[]
	for A in soup.find_all(['h1','h2','h3','h4','h5','h6','p','li','td','strong']):
		J=F(A.get_text(G,strip=C))
		if not J:continue
		R=J.lower()
		if D(A.lower()in R for A in Q):H.append(A)
	if not H:return M
	B=[]
	for A in H:
		B.append(F(A.get_text(G,strip=C)));K=A.parent
		if K:
			L=F(K.get_text(G,strip=C))
			if L:B.append(L)
		E=A
		for S in range(3):
			E=E.find_next_sibling()
			if not E:break
			N=F(E.get_text(G,strip=C))
			if N:B.append(N)
	O=[];P=set()
	for I in B:
		if I not in P:P.add(I);O.append(I)
	return F(G.join(O))
def m(soup):
	I=F(soup.get_text(G,strip=C));A={J:Q,K:Q,L:Q}
	for B in A:
		D=A2(soup,B)
		if D:
			E=A1(D)
			if E:A[B]=E
	H=A1(I)
	if H:
		for B in A:
			if A[B]==Q:A[B]=H
	return A
def A3(today):
	H=today;J=S(AZ)
	if not J:return B,B,M
	K=V(J.text,W);I=F(K.get_text(G,strip=C));N=l(I);L=[A for A in N if H-d(days=Ad)<=A<=H];O=['class arrangement','class arrangements',b,c,h,a,AR,'face to face',i,j,'classes will proceed'];P=D(A in I.lower()for A in O)
	if not P:A('[ATENEO] No class-arrangement information found.');return B,B,M
	E=Z(L)if L else B
	if E:Q=(H-E).days;A(f"[ATENEO] Recent advisory: {E} ({Q} day(s) old)")
	else:A('[ATENEO] Arrangement found, but no usable advisory date.')
	return K,E,I
def Y(url):
	try:A=AV(url).hostname or M;A=A.lower();return A=='quezoncity.gov.ph'or A.endswith('.quezoncity.gov.ph')
	except f:return E
def Ak():
	N='feed';L='atom';G='rss';O={x,Ab,y};E=set()
	for F in O:
		H=S(F)
		if not H:continue
		I=V(H.text,W)
		for J in I.find_all('link'):
			B=J.get(r)
			if not B:continue
			K=(J.get('type',M)or M).lower();D=B.lower()
			if G in K or L in K or N in D or G in D:
				if Y(B):E.add(B)
		for P in I.find_all('a',href=C):
			B=P[r];D=B.lower()
			if N in D or G in D or L in D:
				if Y(B):E.add(B)
	E.add(x);A('[QC] Feed candidates:')
	for F in sorted(E):A(f"  - {F}")
	return n(E)
def A4(url,target_date):
	E=url
	if not Y(E):return
	J=S(E)
	if not J:return
	H=V(J.text,W);I=F(H.get_text(G,strip=C));A=I.lower();K=Aj(I,target_date,days=Ae)
	if not K:return
	Q=D(B in A for B in['private schools','private school','private educational institutions','pribadong paaralan']);X=D(B in A for B in[j,AS,i,'face-to-face classes suspended','suspend face-to-face','suspended face-to-face',AT,AU]);L=D(B in A for B in[AH,AI,a,'synchronous / asynchronous','synchronous/asynchronous','synchronous and asynchronous','synchronous or asynchronous'])
	if b in A and c in A:L=C
	B=M;O=H.find('h1')
	if O:B=F(O.get_text(G,strip=C))
	if not B:
		P=H.find(T)
		if P:B=F(P.get_text(G,strip=C))
	d=Z(K);return{R:E,T:B,U:d,s:Q,t:X,N:L,'text':I}
def A5(target_date=B):
	I=target_date
	if I is B:I=k()
	b=Ak();F=[]
	for P in b:
		A(f"[QC] Reading feed: {P}");H=S(P)
		if not H:continue
		c=AW.parse(H.content)
		for Q in c.entries:
			K=Q.get('link')or Q.get('id')or M
			if not K:continue
			if not Y(K):continue
			G=A4(K,I)
			if G:F.append(G)
	J={}
	for Z in F:J[Z[R]]=Z
	F=n(J.values())
	if not F:
		A('[QC] Feed produced no usable announcements; scanning announcements page.');H=S(y)
		if H:
			d=V(H.text,W)
			for e in d.find_all('a',href=C):
				a=e[r]
				if not Y(a):continue
				G=A4(a,I)
				if G:J[G[R]]=G
			F=n(J.values())
	if not F:A('[QC] No relevant announcement found.');return{X:E,N:E,u:B,T:B,U:B,R:B}
	F.sort(key=lambda x:x[U],reverse=C);D=F[0];L=D[s]and D[t];O=D[N];A(f"[QC] Newest announcement: {D[T]or'(untitled)'}");A(f"[QC] Date: {D[U]}");A(f"[QC] Private school: {D[s]}");A(f"[QC] Suspended: {D[t]}");A(f"[QC] Alternative delivery: {D[N]}");A(f"[QC] URL: {D[R]}");return{X:L,N:O,u:'Private-school suspension + Alternative Delivery Modes'if L and O else'Private-school suspension'if L else'Alternative Delivery Modes'if O else B,T:D[T],U:D[U],R:D[R]}
def A6():
	A=S(Ac)
	if not A:return E,B
	H=V(A.text,W);D=F(H.get_text(G,strip=C)).lower()
	if'red warning level'in D:return C,'PAGASA NCR Red Warning'
	if'orange warning level'in D:return C,'PAGASA NCR Orange Warning'
	return E,B
def A7(target_date=B):
	H=target_date
	if H is B:H=k()
	J=S(Aa)
	if not J:return E
	K=V(J.text,W);I=F(K.get_text(G,strip=C))
	if not I:return E
	L=I.lower();M=[q,AS,p,AT,j,AU]
	if not D(A in L for A in M):return E
	N=l(I)
	if H not in N:A(f"[FACEBOOK] Suspension language found, but no matching date for {H}; ignoring it.");return E
	A(f"[FACEBOOK] Explicit suspension dated {H} found.");return C
def Al(school,today,ateneo_soup,advisory_date,advisory_text,qc_result,pagasa_trigger,pagasa_reason,facebook_suspension):
	K=qc_result;J=advisory_text;G=ateneo_soup;T=today+d(days=1);A={I:0,O:0,H:0,P:55};C=['No explicit closure or online arrangement found; defaulting to normal onsite classes.'];U,V=A0(T)
	if U:A[H]+=100;C.append(f"Calendar: {V}")
	if K[X]:A[H]+=20;C.append('QC indicates a private-school suspension.')
	if K[N]:A[I]+=25;A[O]+=25;A[H]-=15;C.append('QC indicates Alternative Delivery Modes.')
	if pagasa_trigger:A[I]+=20;A[O]+=20;C.append(f"PAGASA: {pagasa_reason}")
	L=M
	if G is not B:L=A2(G,school)
	E=L.lower()
	if E:
		if D(A in E for A in[A8,A9,AA,AB,AC]):A[I]+=70;C.append('Ateneo advisory specifically mentions synchronous learning for this school.')
		if D(A in E for A in[AD,AE,AF,AG]):A[O]+=70;C.append('Ateneo advisory specifically mentions asynchronous learning for this school.')
		if D(A in E for A in[h,o,AJ]):A[I]+=35;C.append('Ateneo advisory specifically mentions online learning for this school.')
		if a in E and b in E:A[I]+=35
		if a in E and c in E:A[O]+=35
		if D(A in E for A in[i,AK,q,p]):A[H]+=60;C.append("Ateneo advisory specifically suspends this school's classes.")
		if D(A in E for A in[AN,AO,AL,AM,AP,AQ]):A[P]+=50;C.append('Ateneo advisory specifically indicates onsite/regular classes for this school.')
	elif J:
		F=J.lower()
		if b in F:A[I]+=15;C.append('Recent Ateneo advisory mentions synchronous learning, but no school-specific section was found.')
		if c in F:A[O]+=15;C.append('Recent Ateneo advisory mentions asynchronous learning, but no school-specific section was found.')
		if h in F or o in F:A[I]+=10
		if AR in F and'suspend'in F:A[I]+=10;A[O]+=10
	if facebook_suspension:A[H]+=10;C.append('Ateneo Facebook appears to indicate a private-school suspension.')
	A={A:Z(0,B)for(A,B)in A.items()};R=Z(A,key=A.get);S=A[R]
	if S<=0:return Q,0,C,A
	W=min(99,Z(50,int(S)));return R,W,C,A
def Am(today,ateneo_soup,advisory_date,advisory_text,qc_result,pagasa_trigger,pagasa_reason,facebook_suspension):
	A={}
	for B in[J,K,L]:A[B]=Al(school=B,today=today,ateneo_soup=ateneo_soup,advisory_date=advisory_date,advisory_text=advisory_text,qc_result=qc_result,pagasa_trigger=pagasa_trigger,pagasa_reason=pagasa_reason,facebook_suspension=facebook_suspension)
	return A
def e(status,confidence):
	A=status
	if A==Q:return'Guess: Unknown (no idea)'
	return f"Guess: {A} ({confidence}% sure)"
def An(today,statuses,tomorrow_guesses):C=today;B=tomorrow_guesses;A=statuses;G=C+d(days=1);D=B[J];E=B[K];F=B[L];return f"""📚 Ateneo School Status

Today - {C.strftime(g)}
• AGS: {A[J]}
• JHS: {A[K]}
• SHS: {A[L]}

Tomorrow — {G.strftime(g)}
• AGS: {e(D[0],D[1])}
• JHS: {e(E[0],E[1])}
• SHS: {e(F[0],F[1])}"""
def Ao(message):
	B=message
	if not z:A('[CHAT] GOOGLE_CHAT_WEBHOOK is not set.');A(B);return E
	try:D=w.post(z,json={'text':B},timeout=20);D.raise_for_status();A('[CHAT] Message sent successfully.');return C
	except f as F:A(f"[CHAT] Failed to send message: {F}");return E
def Ap():
	I='=';C=k();A();A(I*70);A(f"School status check — {C.strftime(g)}");A(I*70);b,c=A0(C)
	if b:D={J:H,K:H,L:H};A(f"[TODAY] No School — {c}");G={X:E,N:E,u:B,T:B,U:B,R:B};S=E;W=B;F=B;f=B;h=M;V=E
	else:
		G=A5(C);A(f"[DEBUG] QC private suspended: {G[X]}");A(f"[DEBUG] QC alternative delivery: {G[N]}");S,W=A6();A(f"[DEBUG] PAGASA trigger: {S}");A(f"[DEBUG] PAGASA reason: {W}");F,f,h=A3(C)
		if F is not B:D=m(F)
		else:D={J:P,K:P,L:P}
		V=A7(C);A(f"[DEBUG] Facebook private suspension: {V}");i=G[X]or V
		if i and not G[N]:D={J:H,K:H,L:H};A('[TODAY] Private-school suspension without Alternative Delivery -> No School')
		elif G[N]or S:
			if F is not B:D=m(F);A('[TODAY] Alternative delivery/weather signal -> using Ateneo advisory.')
			else:D={J:Q,K:Q,L:Q};A('[TODAY] Signal found but no recent Ateneo advisory.')
		elif F is not B:D=m(F);A('[TODAY] Using recent Ateneo advisory.')
		else:D={J:P,K:P,L:P};A('[TODAY] No relevant advisory -> Onsite.')
	A();A(I*70);A('TOMORROW — INDEPENDENT SCHOOL GUESSES');A(I*70);Y=C+d(days=1);j=A5(Y);l,n=A6();o,p,q=A3(C);r=A7(Y);Z=Am(today=C,ateneo_soup=o,advisory_date=p,advisory_text=q,qc_result=j,pagasa_trigger=l,pagasa_reason=n,facebook_suspension=r)
	for(s,t)in[(J,'AGS'),(K,'JHS'),(L,'SHS')]:
		O=Z[s];A(f"{t}: {e(O[0],O[1])}");A(f"  Scores: {O[3]}")
		for v in O[2]:A(f"  - {v}")
		A()
	a=An(C,D,Z);A(I*70);A('FINAL MESSAGE');A(I*70);A(a);A();Ao(a)
if __name__=='__main__':Ap()
