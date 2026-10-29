"""Public project boards with verified job-specific email addresses.

Only scan open calls and dated contract/gig briefs. Do not infer email from
site footers, crawl arbitrary links, infer dates or send messages.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from lxml import html

PENDING_LIST="https://agency.thepending.com/jobs/"
PENDING_HOST="agency.thepending.com"
IMPACTPOOL_URL="https://www.impactpool.org/jobs/1243128"
SOURCES=(
    {"id":"pending-agency","title":"The Pending Agency","url":PENDING_LIST,"kind":"public-board"},
    {"id":"impactpool-design","title":"Impactpool · public tender","url":IMPACTPOOL_URL,"kind":"verified-open-call"},
)
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; SearchOrders/1.0; public job listing monitor)"}
EMAIL=re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",re.I)
DESIGN=re.compile(r"graphic designer|freelance designer|digital designer|presentation design|pitch deck|visual identity|brand design|ui.?ux|product designer|web designer|design agency|дизайнер|айдентик|презентац",re.I)
CONTRACT=re.compile(r"freelance|contract|gig|single project|project.by.project|ad.hoc|supplier|tender|consultancy|подряд|проектн",re.I)
NEGATIVE=re.compile(r"dutch (?:reading/writing|language|fluency).{0,45}(?:must|required)|(?:must|required).{0,45}dutch|must be based in (?:the )?(?:usa|united states|netherlands)|on.?site only|full.?time only",re.I)
APPLY=re.compile(r"please (?:send|email)|applications? (?:should|must|can)|email your|send your (?:portfolio|cv|resume)|to [\w.+-]+@[\w.-]+\.[a-z]{2,}|via (?:e-?mail|mail)|how to apply",re.I)

def now():
    return datetime.now(timezone.utc)

def category_for(text):
    from .engine import CATEGORIES
    counts={k:len(re.findall(pattern,text,re.I)) for k,(_,pattern) in CATEGORIES.items()}
    key=max(counts,key=counts.get)
    if counts[key]:return key
    if re.search(r"pitch deck|presentation designer|powerpoint|slides",text,re.I):return "presentations"
    if re.search(r"ui.?ux|ux.?ui|interface|product designer|figma screens",text,re.I):return "uiux"
    if re.search(r"web designer|website|landing page|webflow|tilda",text,re.I):return "web"
    if re.search(r"graphic design|freelance designer|editorial design|brand design|visual design|artwork",text,re.I):return "branding"
    return None

def fetch_html(url):
    parsed=urlparse(url)
    if parsed.scheme!="https" or parsed.hostname not in (PENDING_HOST,"www.impactpool.org"):
        raise ValueError("Unapproved source URL")
    response=requests.get(url,timeout=(5,15),headers=HEADERS)
    response.raise_for_status()
    if len(response.content)>1500000:raise ValueError("Page too large")
    return html.fromstring(response.content)

def normalize_text(dom):
    main=dom.xpath("//main")
    if not main:return ""
    text=" ".join(" ".join(main[0].itertext()).split())
    clean=text.split("Copy link Post image",1)[0][:6000]
    # Several external sites send incorrectly labelled UTF-8; fix only known
    # quotation mojibake before extracting explicit application subjects.
    return clean.replace("â","“").replace("â","”").replace("â","’")

def extract_email(text):
    # Never select a generic footer email. Only the brief's body is searched.
    if not APPLY.search(text):return None
    emails=EMAIL.findall(text)
    for address in emails:
        if address.lower().startswith(("noreply@","no-reply@","privacy@","dpo@")):continue
        # Avoid broad generic email if no explicit application instruction in the brief.
        return address.lower()
    return None

def make_lead(url,body,contact,buyer,channel,deadline=None,source_date=None,
              note="",score=83,category_override=None):
    category=category_override or category_for(body)
    if not category or not contact:return None
    if not DESIGN.search(body) or not CONTRACT.search(body):return None
    if NEGATIVE.search(body):return None
    if not APPLY.search(body):return None
    if deadline and deadline < now().date():return None
    if source_date and source_date > now()+timedelta(days=1):return None
    dated=source_date or now()
    reason=(note or "Проверено на открытой странице вакансии") + (
       "; дата публикации подтверждена" if source_date else
       "; дата карточки = обнаружение, оригинальная дата размещения не опубликована"
    )
    if deadline:reason+="; срок отклика до "+deadline.isoformat()
    fingerprint=hashlib.sha1((url+"|"+contact).encode()).hexdigest()
    return {
      "id":hashlib.sha1(url.encode()).hexdigest()[:20],
      "url":url,"channel":channel,
      "published_at":dated.isoformat(),"discovered_at":now().isoformat(),
      "body":body[:3600],"category":category,"score":score,
      "contact":contact,"buyer":buyer[:100],"budget":"","reason":reason,
      "fingerprint":fingerprint,
      "expires_at":deadline.isoformat() if deadline else ""
    }

def pending_candidates():
    dom=fetch_html(PENDING_LIST)
    links=[]
    for a in dom.xpath('//a[contains(@href,"/jobs/job/")]'):
        href=urljoin(PENDING_LIST,a.get("href","")).split("?",1)[0]
        if not re.fullmatch(r"https://agency\.thepending\.com/jobs/job/[0-9a-f-]{36}/?",href):continue
        text=" ".join(a.itertext())
        if DESIGN.search(text) and CONTRACT.search(text) and href not in links:
            links.append(href)
    return links[:12]

def pending_detail(url):
    dom=fetch_html(url)
    main=normalize_text(dom)
    if not main:return None
    # Project description ends before the site's own scripts or application form.
    title=dom.xpath("//h1//text()")
    title=" ".join(" ".join(title).split())[:120]
    if not DESIGN.search(title):return None
    contact=extract_email(main)
    if not contact:return None
    deadline=None
    match=re.search(r"Apply by\s*[·:]\s*(\d{4}-\d\d-\d\d)",main,re.I)
    if match:
        try:deadline=datetime.strptime(match.group(1),"%Y-%m-%d").date()
        except ValueError:pass
    start=re.search(r"Project dates\s*[·:]\s*(\d{4}-\d\d-\d\d)",main,re.I)
    if not deadline and start:
        try:
            startday=datetime.strptime(start.group(1),"%Y-%m-%d").date()
            if startday < now().date()-timedelta(days=70):return None
        except ValueError:return None
    elif not deadline and not start:
        # Undated evergreen talent rosters are not a current client brief.
        return None
    if not deadline:
        end_match=re.search(r"Project dates\s*[·:]\s*\d{4}-\d\d-\d\d\s*[–-]\s*(\d{4}-\d\d-\d\d)",main,re.I)
        if end_match:
            try:deadline=datetime.strptime(end_match.group(1),"%Y-%m-%d").date()
            except ValueError:pass
    lead_in=main.split(title,1)[0]
    # The provider labels employer immediately before the job title.
    # An initial letter before the name is a UI avatar, not part of the company.
    lead_in=lead_in.split("International applicants welcome",1)[-1].strip()
    short_buyer=re.sub(r"^[A-Z]\s+","",lead_in).strip()[:80]
    # Many boards include remote labels, not proof that the user qualifies.
    is_roster="occasional project-based work" in main.lower()
    return make_lead(url,main,contact,short_buyer,"pending-agency",deadline=deadline,
         note=("Пул фрилансеров для будущих задач; оплаченный заказ пока не подтверждён"
               if is_roster else "Проверено в каталоге The Pending Agency · проект/контракт"),
         score=68 if is_roster else 84)

def fetch_pending():
    links=pending_candidates()
    rows=[]
    errors=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(pending_detail,url):url for url in links}
        for f in as_completed(futures):
            try:
                item=f.result()
                if item:rows.append(item)
            except Exception as e:errors.append(f"{futures[f]}: {str(e)[:100]}")
    return len(links)+1,rows,errors

def fetch_impactpool():
    dom=fetch_html(IMPACTPOOL_URL)
    text=normalize_text(dom)
    # This is a verified tender on Impactpool: do not harvest random site
    # emails such as support or privacy from navigation.
    if not text or "Transparency International" not in text:return 1,[],[]
    deadline=None
    m=re.search(r"Application deadline:\s*(October\s+31,\s*2026)",text,re.I)
    if m:deadline=datetime.strptime("2026-10-31","%Y-%m-%d").date()
    if not deadline or deadline<now().date():return 1,[],[]
    # Only accept the address from the explicit HOW TO APPLY paragraph.
    match=re.search(r"Applications should be sent.{0,150}?by email to\s*("+EMAIL.pattern+r")",text,re.I|re.S)
    if not match:return 1,[],[]
    address=match.group(1).lower()
    # Preserve the application instructions and email address rather than
    # discarding them in a 3600-character prefix of a long vacancy.
    apply_at=text.find("HOW TO APPLY")
    body=text[:2300]+(" … "+text[apply_at:apply_at+1000] if apply_at>=0 else " … "+text[4800:5600])
    row=make_lead(IMPACTPOOL_URL,body,address,"Transparency International",
             "impactpool-design",deadline=deadline,category_override="branding",
             note="Открытый конкурс поставщиков: проектная графика и публикации",score=83)
    return 1,[row] if row else [],[]

FETCHERS={"pending-agency":fetch_pending,"impactpool-design":fetch_impactpool}
