"""Public live tenders with an official on-platform application route.

This connector never invents buyer contacts or pretends that a platform link
is an email. It scans only public open Workspace tender cards and their own
detail pages. Submissions require the user's own account and action.
"""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
import requests
from lxml import html

BASE="https://workspace.ru"
SOURCES=(
 {"id":"workspace-identity","title":"Workspace · дизайн и брендинг","url":"https://workspace.ru/tenders/identity/"},
 {"id":"workspace-web","title":"Workspace · сайты","url":"https://workspace.ru/tenders/web-development/"}
)
RU_MONTHS={"января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
 "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12}

def parse_date(text:str):
 match=re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})",text,re.I)
 if not match:return None
 try:return date(int(match.group(3)),RU_MONTHS[match.group(2).lower()],int(match.group(1)))
 except (KeyError,ValueError):return None

def fetch(url):
 parsed=urlparse(url)
 if parsed.scheme!="https" or parsed.netloc!="workspace.ru" or not parsed.path.startswith("/tenders/"):
  raise ValueError("URL is not an approved Workspace tender")
 r=requests.get(url,timeout=(5,14),headers={"User-Agent":"Mozilla/5.0 (SearchOrders personal research tool)"})
 r.raise_for_status()
 if len(r.content)>2_000_000:raise ValueError("Workspace page unexpectedly large")
 return html.fromstring(r.content)

def compact(text):
 return " ".join(str(text).split())

def list_candidates(source):
 page=fetch(source["url"])
 out=[]
 for card in page.xpath('//*[@data-tender-card]')[:14]:
  states=card.xpath('.//*[@data-change-status-text]/@data-change-status-text')
  if "open" not in states:continue
  links=card.xpath('.//a[starts-with(@href,"/tenders/")]')
  if not links:continue
  title=compact(" ".join(links[0].itertext()))
  if not title or "закрытый тендер" in title.lower():continue
  url=urljoin(BASE,links[0].get("href"))
  if not re.fullmatch(r"https://workspace\.ru/tenders/[a-z0-9-]+-\d{3,6}/",url):continue
  cardtext=compact(" ".join(card.itertext()))
  deadline_match=re.search(r"Крайний срок приема заявок:\s*(\d{1,2}\s+[а-яё]+\s+\d{4})",cardtext,re.I)
  publication_match=re.search(r"Опубликован\s*(\d{1,2}\s+[а-яё]+\s+\d{4})",cardtext,re.I)
  deadline=parse_date(deadline_match.group(1)) if deadline_match else None
  published=parse_date(publication_match.group(1)) if publication_match else None
  today=datetime.now(timezone.utc).date()
  if not deadline or deadline<today:continue
  # No false "new this week" labels for tenders lacking a verified date.
  if not published or published>today or published<today-timedelta(days=40):continue
  budget_text=re.search(r"(?:(?:до\s*)?[\d\s]+(?:-\s*[\d\s]+)?)\s*Опубликован",cardtext,re.I)
  budget=compact(budget_text.group(0).replace("Опубликован","")) if budget_text else ""
  # Exclude ambiguous software-only requests that need full engineering teams.
  if re.search(r"умный калькулятор|программа\b|продвижение|SEO\b|инженерной сантехники",title,re.I):continue
  if source["id"]=="workspace-web" and not re.search(r"сайт|редизайн|интернет-магазин|лендинг",title,re.I):continue
  out.append(dict(url=url,title=title,published=published,deadline=deadline,budget=budget,
                  corporate_email="корпоративный e-mail" in cardtext))
 return out[:9]

def candidate_to_lead(candidate,source):
 detail=fetch(candidate["url"])
 descs=detail.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," tendercard__desc ")]')
 desc=compact(" ".join(descs[0].itertext())) if descs else ""
 if len(desc)<40:return None
 if "Чтобы участвовать в тендере войдите/зарегистрируйтесь" not in compact(" ".join(detail.xpath('//body//text()'))):
  # Requirements change from time to time; keep only a verifiable apply route.
  return None
 category="branding" if source["id"]=="workspace-identity" else "web"
 posted=datetime.combine(candidate["published"],datetime.min.time(),tzinfo=timezone.utc)
 fingerprint=hashlib.sha1(candidate["url"].encode()).hexdigest()
 # The official Workspace help states that proactive public tender bids
 # require paid PRO. A corporate email badge is not the actual email.
 reason=("Workspace: самостоятельный отклик на публичный тендер требует платного PRO. "
         "Бесплатно — только если заказчик сам пригласит. "
         "Контакт через официальную площадку, не является прямым email заказчика. "
         +("Заказчик указал корпоративный email, но публично он не раскрыт."
           if candidate["corporate_email"] else "Прямой email заказчика не опубликован."))
 return {
  "id":fingerprint[:20],"url":candidate["url"],"channel":"workspace-tender",
  "published_at":posted.isoformat(),"discovered_at":datetime.now(timezone.utc).isoformat(),
  "body":(candidate["title"]+".\n"+desc)[:3600],"category":category,
  "score":83 if candidate["corporate_email"] else 76,
  "contact":candidate["url"],"buyer":candidate["title"][:110],
  "budget":candidate["budget"],"reason":reason,
  "fingerprint":fingerprint,"expires_at":candidate["deadline"].isoformat()
 }

def scan_source(source):
 candidates=list_candidates(source)
 rows=[]
 errors=[]
 with ThreadPoolExecutor(max_workers=3) as ex:
  futures={ex.submit(candidate_to_lead,c,source):c for c in candidates}
  for future in as_completed(futures):
   try:
    result=future.result()
    if result:rows.append(result)
   except Exception as e:errors.append(f'{futures[future]["url"]}: {str(e)[:110]}')
 return len(candidates)+1,rows,errors

FETCHERS={s["id"]:(lambda s=s:scan_source(s)) for s in SOURCES}
