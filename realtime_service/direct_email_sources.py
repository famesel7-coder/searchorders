"""Public Design Jobs Board: freelance offers with an explicit application email."""
from __future__ import annotations
import hashlib,re
from datetime import datetime,timezone
from urllib.parse import urlparse,unquote
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from lxml import html

BASE="https://www.designjobsboard.com/"
SOURCES=({"id":"design-jobs-board","title":"Design Jobs Board · прямой email","url":BASE},)
EMAIL=re.compile(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$")
FREELANCE=re.compile(r"\b(?:freelance|contract|ad.hoc)\b",re.I)
DESIGN=re.compile(r"\b(?:designer|typograph|presentation|graphic|digital|brand|artworker|ui.?ux)\b",re.I)
BAD_LOCATION=re.compile(r"UK.based (?:only|applicants)|applicants must (?:live|reside|be based) in (?:the )?(?:UK|US)|must have (?:the )?right to work in (?:the )?(?:UK|US)|office.based|on.site only",re.I)

def fetch(url):
 u=urlparse(url)
 if u.scheme!="https" or u.netloc!="www.designjobsboard.com":raise ValueError("Unapproved source")
 r=requests.get(url,timeout=(5,15),headers={"User-Agent":"Mozilla/5.0"})
 r.raise_for_status()
 if len(r.content)>2_000_000:raise ValueError("Unexpected size")
 return html.fromstring(r.content)

def parse_age(text):
 m=re.search(r"JOB ADDED\s+(\d+)\s+(day|week|month)s?\s+ago",text,re.I)
 if not m:return None
 return int(m[1])*{"day":1,"week":7,"month":30}[m[2].lower()]

def candidates():
 root=fetch(BASE);result=[];seen=set()
 for a in root.xpath('//a[starts-with(@href,"https://www.designjobsboard.com/job/")]'):
  url=a.get("href","")
  if not re.fullmatch(r"https://www\.designjobsboard\.com/job/\d{4,7}/[a-z0-9-]+/",url) or url in seen:continue
  seen.add(url)
  heading=a.getparent().getparent()
  title=" ".join(" ".join(heading.itertext()).split())
  if not (FREELANCE.search(title) and DESIGN.search(title)):continue
  if re.search("Full Time|Part Time|Hybrid|UK.based only",title,re.I):continue
  block=heading
  for _ in range(7):
   if block is None or "Apply Now" in " ".join(block.itertext()):break
   block=block.getparent()
  if block is None:continue
  age=parse_age(" ".join(" ".join(block.itertext()).split()))
  if age is None or age>30:continue
  links=[x.get("href","") for x in block.xpath('.//a[@href]') if "Apply Now" in " ".join(x.itertext())]
  for link in links:
   if not link.startswith("mailto:"):continue
   contact=unquote(link.split(":",1)[1].split("?",1)[0]).strip().lower()
   if EMAIL.fullmatch(contact):
    result.append({"url":url,"contact":contact,"age":age,"title":title[:150]})
    break
 return result[:12]

def detail(item):
 root=fetch(item["url"])
 title=(root.xpath("string(//title)") or "").replace(" - Design Jobs Board","").strip() or item["title"]
 alltext=" ".join(" ".join(root.xpath("//body//text()")).split())
 snippet=alltext.split("The speed read",1)[-1].split("Apply Now",1)[0][:3200]
 if len(snippet)<90 or BAD_LOCATION.search(snippet):return None
 if not FREELANCE.search(item["title"]+" "+snippet):return None
 if not DESIGN.search(item["title"]+" "+snippet):return None
 now=datetime.now(timezone.utc).isoformat()
 reason=("В карточке указан прямой email для фриланс-отклика. Дата = обнаружение; "
         f"площадка указывает приблизительно {item['age']} дней после публикации. "
         "Проверь актуальность и требования до отправки.")
 score=83
 if "working font" in snippet.lower():
  reason+=" Узкая задача: создание работающих шрифтов, нужен соответствующий опыт."
  score=62
 key=hashlib.sha1(item["url"].encode()).hexdigest()
 return {"id":key[:20],"url":item["url"],"channel":"design-jobs-board",
         "published_at":now,"discovered_at":now,"body":(title+"\n\n"+snippet)[:3600],
         "category":"branding","score":score,"contact":item["contact"],"buyer":title[:120],
         "budget":"","reason":reason,"fingerprint":key,"expires_at":""}

def scan():
 items=candidates();results=[];errors=[]
 with ThreadPoolExecutor(max_workers=3) as pool:
  futures={pool.submit(detail,x):x for x in items}
  for future in as_completed(futures):
   try:
    row=future.result()
    if row:results.append(row)
   except Exception as e:errors.append(f'{futures[future]["url"]}: {str(e)[:120]}')
 return len(items)+1,results,errors

FETCHERS={"design-jobs-board":scan}
