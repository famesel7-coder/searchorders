"""Free-to-bid design projects from FL.ru's public RSS feed.

Only titles explicitly marked '(для всех)' qualify. All offers are
submitted by the freelancer through FL.ru, never via invented direct email.
"""
from __future__ import annotations
import hashlib
import html as stdhtml
import re
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import requests
from lxml import etree,html

URL="https://www.fl.ru/rss/projects.xml"
SOURCES=({"id":"flru-free","title":"FL.ru · бесплатные отклики «для всех»","url":URL},)
DESIGN=re.compile(r"дизайн|дизайнер|логотип|брендинг|айдентик|макет|полиграф|презентац|веб.дизайн|лендинг|интерфейс|figma|сайт|карточк[аи] товар|упаковк",re.I)
BAD=re.compile(r"накрут|отзыв[ао]|положительн.{0,12}отзыв|продвижени|SEO|аудит|разработать бота|CRM|оператор|архитектур|офис[ауы]|интерьер|разместить|написать отзыв|учебн.{0,12}задани",re.I)

def text_from_rss(value):
    fragment=stdhtml.unescape(value or "")
    try:return " ".join(" ".join(html.fromstring('<div>'+fragment+'</div>').itertext()).split())
    except Exception:return " ".join(re.sub(r"<[^>]+>"," ",fragment).split())

def category(title):
    if re.search(r"презентац|слайд",title,re.I):return "presentations"
    if re.search(r"сайт|лендинг|tilda|веб.дизайн",title,re.I):return "web"
    if re.search(r"интерфейс|ui.?ux|figma",title,re.I):return "uiux"
    return "branding"

def scan():
    r=requests.get(URL,timeout=(5,13),headers={
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept":"application/rss+xml,text/xml,text/html"})
    r.raise_for_status()
    if len(r.content)>800000:raise ValueError("Oversized RSS feed")
    root=etree.fromstring(r.content,parser=etree.XMLParser(recover=False,resolve_entities=False,no_network=True))
    entries=root.xpath("//channel/item")
    found=[]
    current=datetime.now(timezone.utc)
    for entry in entries:
        title=text_from_rss(entry.findtext("title"))
        link=(entry.findtext("link") or "").strip()
        dt=(entry.findtext("pubDate") or "").strip()
        description=text_from_rss(entry.findtext("description"))
        if not re.search(r"\(\s*для всех\s*\)",title,re.I):continue
        if not DESIGN.search(title) or BAD.search(title):continue
        parsed=urlparse(link)
        if parsed.scheme!="https" or parsed.netloc not in ("www.fl.ru","fl.ru") or not re.fullmatch(r"/projects/\d+/[a-z0-9-]+\.html",parsed.path):continue
        try:published=parsedate_to_datetime(dt).astimezone(timezone.utc)
        except Exception:continue
        if not current-timedelta(days=5)<=published<=current+timedelta(hours=2):continue
        if len(description)<30 or BAD.search(description[:240]):continue
        # Exclude unpaid barter-like gigs.
        if re.search(r"без\s+оплат|бесплатно поработ|за отзыв",description,re.I):continue
        budget_match=re.search(r"Бюджет:\s*([\d\s]+)\s*₽",title,re.I)
        budget=(budget_match.group(1).strip()+" ₽") if budget_match else ""
        key=hashlib.sha1(link.encode()).hexdigest()
        score=81 if budget else 69
        found.append({"id":key[:20],"url":link,"channel":"flru-free",
          "published_at":published.isoformat(),"discovered_at":current.isoformat(),
          "body":(re.sub(r"\s*\([^)]*для всех[^)]*\)","",title,flags=re.I)+"\n\n"+description)[:3600],
          "category":category(title),"score":score,"contact":link,
          "buyer":re.sub(r"\s*\([^)]*\)","",title)[:110],"budget":budget,
          "reason":"FL.ru: объявление прямо помечено «для всех». Отклик на этот заказ бесплатный через площадку после входа. Прямой email заказчика не опубликован; цена и актуальность требуют проверки перед откликом.",
          "fingerprint":key,"expires_at":""})
    return len(entries),found,[]

FETCHERS={"flru-free":scan}
