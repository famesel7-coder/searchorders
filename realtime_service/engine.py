"""Monitor public Telegram channels for genuine design project requests."""
import os, json, re, hashlib, sqlite3, threading, time, concurrent.futures
from pathlib import Path
from datetime import datetime, timezone
import requests
from lxml import html
from .direct_contacts import is_direct_lead

ROOT=Path(__file__).resolve().parent.parent
RUNTIME=Path(os.environ.get("SEARCHORDERS_STATE",str(ROOT/".runtime")))
DB=RUNTIME/"leads.sqlite3"
INTERVAL=max(120,int(os.environ.get("SEARCHORDERS_INTERVAL","300")))
MAX_AGE_HOURS=72
CATEGORIES={
 "web":("Сайты",r"сайт|лендинг|тильд|tilda|webflow|framer|веб.?дизайн|web.?design|wordpress|верстк|редизайн|интернет-магазин"),
 "uiux":("UI/UX",r"ui.?ux|ux.?ui|интерфейс|figma|saas|дизайн.?систем|прототип|product.?design|мобильн.{0,16}приложен"),
 "presentations":("Презентации",r"презентац|pitch.?deck|питч.?дек|слайд|powerpoint|инфографик|keynote|google.?slides"),
 "branding":("Брендинг / графика",r"брендинг|брендбук|айдентик|фирменн.{0,12}стил|визуальн.{0,12}стил|key.?visual|графическ.{0,12}дизайн|smm.?дизайн|дизайн.?баннер|event.?дизайн")
}
INTENT=r"ищем|ищу|ищет|ищет|ищут|требуется|нуж(?:ен|на|но|ны)|подрядчик|необходимо (?:создать|разработать|оформить)|looking for|seeking|need a"
PROJECT=r"проект|разов|фриланс|подряд|удал[её]н|бюджет|оплат|сдельн|договор|freelance|contract|тип работы:\s*проектн"
FULLTIME=r"в штат|на постоянн|полн[а-я]+ занятост|пятиднев|график 5/2|оклад|full.time|тип работы:\s*постоянн"
SELF_PROMO=r"предлага[юем] (?:свои )?услуг|мы (?:разрабатываем|созда[её]м) сайты|помогаем бизнес|наша студия|ищу проекты и сотрудничество|дизайнер.{0,65}открыт к проектам|ищу клиентов на свои услуги"
CONTACT=re.compile(r"(?<![\w.])@[a-zA-Z][\w]{4,31}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://t\.me/[a-zA-Z][\w]{4,31}",re.I)
BLOCKED={"zakaz_design","digitaltender","freelancetaverna","frilans","designizer","jobaem","telegram","pro_zayavki"}
SQL="""CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,url TEXT UNIQUE,channel TEXT,published_at TEXT,discovered_at TEXT,
body TEXT,category TEXT,score INTEGER,contact TEXT,buyer TEXT,budget TEXT,reason TEXT,
fingerprint TEXT,stage TEXT DEFAULT 'new',notified INTEGER DEFAULT 0, contacted INTEGER NOT NULL DEFAULT 0, saved INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_time ON leads(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_fp ON leads(fingerprint);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT,sources INTEGER,posts INTEGER,matched INTEGER,new_leads INTEGER,errors TEXT);
CREATE TABLE IF NOT EXISTS draft_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 lead_id TEXT NOT NULL,
 content TEXT NOT NULL,
 method TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draft_lead ON draft_history(lead_id, id DESC);
CREATE TABLE IF NOT EXISTS email_source_checks(
 source_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL, fetched INTEGER DEFAULT 0,
 matched INTEGER DEFAULT 0, last_error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS translation_cache(
 lead_id TEXT NOT NULL, source_digest TEXT NOT NULL,
 translated_body TEXT NOT NULL, translated_at TEXT NOT NULL,
 PRIMARY KEY(lead_id,source_digest)
);
"""

def conn():
 RUNTIME.mkdir(exist_ok=True,parents=True)
 db=sqlite3.connect(DB,timeout=30,check_same_thread=False)
 db.row_factory=sqlite3.Row
 db.executescript(SQL)
 # Older installs stored mutually exclusive 'saved' and 'contacted' as one
 # stage. Migrate once, preserving all existing flags without data loss.
 columns={row["name"] for row in db.execute("PRAGMA table_info(leads)")}
 if "contacted" not in columns:
  db.execute("ALTER TABLE leads ADD COLUMN contacted INTEGER NOT NULL DEFAULT 0")
 if "saved" not in columns:
  db.execute("ALTER TABLE leads ADD COLUMN saved INTEGER NOT NULL DEFAULT 0")
 if "expires_at" not in columns:
  db.execute("ALTER TABLE leads ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")
 if "contacted" not in columns or "saved" not in columns:
  db.execute("UPDATE leads SET contacted=1 WHERE stage='contacted'")
  db.execute("UPDATE leads SET saved=1 WHERE stage='saved'")
  db.execute("UPDATE leads SET stage='new' WHERE stage IN ('contacted','saved')")
  db.commit()
 return db

def sources():
 registry=json.loads((ROOT/"data/search_sources.json").read_text(encoding="utf8"))["source_registry"]
 urls=[x["url"] for x in registry if x.get("tier")=="telegram_primary"]
 extra=RUNTIME/"extra_sources.json"
 if extra.exists():
  try: urls.extend(x for x in json.loads(extra.read_text()) if re.fullmatch(r"https://t\.me/s/[A-Za-z0-9_]+",x))
  except (ValueError,OSError):pass
 return list(dict.fromkeys(urls))

def contacted():
 try:
  data=json.loads((ROOT/"data/outreach_status.json").read_text())
  return {str(x.get("contact")).strip().lower() for x in data.get("contacted",[]) if isinstance(x,dict) and isinstance(x.get("contact"),str) and x.get("contact").strip()}
 except (OSError,ValueError):return set()

def classify(text,url,node,channel,published):
 age=(datetime.now(timezone.utc)-published).total_seconds()/3600
 # Many repost channels pack unrelated job offers into one post.
 # Never combine a design keyword from one ad with a contact from another.
 if (text.count(" ➡️ ")>1 or (re.search(r"\b1\.\s*#",text) and re.search(r"\b2\.\s*#",text))):return None
 if re.search(r"ищу проекты|(?:^|\\s)я (?:веб[- ]?)?дизайнер|(?:^|\\s)я графический дизайнер|услуги по разработке",text[:200],re.I):return None
 if re.search(r"(?:#|\b)(?:продактменеджер|product manager|контентассистент|методист|маркетолог|smmассистент|сторис-мейкер|менеджер по привлечению|ai-ассистент)",text[:160],re.I):return None
 if re.search(r"(?:подписывайтесь|наш канал включили|подборка каналов|подпишись на канал)",text[:500],re.I):return None
 if re.search(r"я основатель|мы помогаем бизнесу|что мы разрабатываем|мы оказываем услуги",text[:550],re.I):return None
 if re.search(r"ищем дизайнеров для сотрудничества на разных проектах|вступай в команду дизайнеров",text[:230],re.I):return None
 if age < -1 or age > MAX_AGE_HOURS:return None
 category=None;hits=0
 for key,(label,pattern) in CATEGORIES.items():
  found=len(re.findall(pattern,text,re.I))
  if found>hits:category=key;hits=found
 if not category or not re.search(INTENT,text[:650],re.I):return None
 if not any(re.search(p,text[:520],re.I) for _,p in CATEGORIES.values()):return None
 if re.search(SELF_PROMO,text,re.I) and not re.search(r"ищ[уе]м|нуж(?:ен|на|но|ны)|требуется",text,re.I):return None
 project=bool(re.search(PROJECT,text,re.I))
 fulltime=bool(re.search(FULLTIME,text,re.I))
 if fulltime and not re.search(r"проектная работа|проектный формат|под конкретный проект|разовая задача|сдельно|фриланс|freelance",text,re.I):return None
 if re.search(r"\bвакансия|#ваканси",text[:170],re.I) and not re.search(r"проектная работа|под проект|фриланс|сдельн|contract|freelance|краткосрочн",text,re.I):return None
 links=node.xpath(".//a/@href")
 matches=CONTACT.findall(text+" "+" ".join(x for x in links if "t.me/" in x or x.startswith("mailto:")))
 cc=[]
 for item in matches:
  item=item.replace("https://t.me/","@").replace("http://t.me/","@").replace("mailto:","").strip(".,;:()")
  if item.lstrip("@").lower() in BLOCKED or item.lstrip("@").lower()==channel.lower() or item.lower().endswith("bot"):continue
  if item.lower() not in [x.lower() for x in cc]:cc.append(item)
 if not cc:return None
 # Prefer an explicitly published email over a Telegram handle.
 cc.sort(key=lambda v: 0 if re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}",v) else 1)
 if cc[0].lower().startswith(("info@","hello@")) and not re.search(r"контакт|отклик|писать|пишите|резюме|портфолио",text,re.I):return None
 buyer_match=re.search(r"(?:компания|агентство|заказчик)\s*[:—-]\s*([^\n,]{3,45})",text,re.I)
 buyer=buyer_match.group(1).strip(" .—-") if buyer_match else ""
 budget_match=re.search(r"(?:бюджет|оплата|стоимость)\s*[:—-]\s*([^\n]{3,45})",text,re.I)
 budget=budget_match.group(1).strip() if budget_match else ""
 if any(x in budget.lower() for x in ["бот","контакт","t.me"]):budget=""
 score=max(0,min(99,38+min(hits,4)*8+(16 if project else -10)+(15 if not fulltime else -24)+(10 if age<24 else 0)+(5 if buyer else 0)))
 if score<60:return None
 fp=hashlib.sha1((re.sub(r"\W+","",text.lower())[:220]+cc[0].lower()).encode()).hexdigest()
 return dict(id=hashlib.sha1(url.encode()).hexdigest()[:20],url=url,channel=channel,
  published_at=published.isoformat(),discovered_at=datetime.now(timezone.utc).isoformat(),body=text[:3600],
  category=category,score=score,contact=cc[0],buyer=buyer,budget=budget,
  reason="Контакт опубликован в Telegram; дата поста канала, оригинал заказа требует проверки; "+("проектный формат" if project else "формат нужно уточнить")+
  ("; возможно штат" if fulltime else "")+("; компания требует проверки" if not buyer else ""),
  fingerprint=fp)

def fetch(url):
 channel=url.rstrip("/").rsplit("/",1)[-1]
 response=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=14)
 response.raise_for_status()
 tree=html.fromstring(response.content)
 posts=tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," tgme_widget_message_wrap ")]')
 out=[]
 for node in posts:
  times=node.xpath(".//time/@datetime")
  urls=node.xpath('.//a[contains(@class,"tgme_widget_message_date")]/@href')
  bodies=node.xpath('.//*[contains(@class,"tgme_widget_message_text")]')
  if not(times and urls and bodies):continue
  try:dt=datetime.fromisoformat(times[0].replace("Z","+00:00"))
  except ValueError:continue
  body=" ".join(" ".join(bodies[0].itertext()).split())
  if not body:continue
  item=classify(body,urls[0],bodies[0],channel,dt)
  if item:out.append(item)
 return len(posts),out

class Monitor:
 def __init__(self): self.lock=threading.Lock();self.active=False;self.last={};self.stop=threading.Event()
 def scan(self,notify=None,force_email=False):
  if not self.lock.acquire(False):return {"busy":True}
  self.active=True
  errors=[];new=[];matched=0;count=0;fetched=0
  try:
   from .email_sources import SOURCES as EMAIL_SOURCES,FETCHERS as EMAIL_FETCHERS
   from .direct_email_sources import SOURCES as DIRECT_SOURCES,FETCHERS as DIRECT_FETCHERS
   from .hh_sources import SOURCES as HH_SOURCES,FETCHERS as HH_FETCHERS
   # Telegram reposts do not prove the contact belongs to the buyer.
   # Keep their old data in the archive; do not ingest them as new direct leads.
   urls=[]
   with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    futures={ex.submit(fetch,url):url for url in urls}
    db=conn();outreach=contacted()
    # Do not reintroduce a previous customer's repost, even if the
    # message URL or wording changed. Keep archived leads in the database.
    outreach.update(row["contact"].lower() for row in db.execute(
        "SELECT DISTINCT contact FROM leads WHERE contacted=1 OR stage='dismissed'"
    ) if row["contact"])
    for future in concurrent.futures.as_completed(futures):
     count+=1
     try:
      posts,leads=future.result();fetched+=posts;matched+=len(leads)
      for item in leads:
       if not is_direct_lead(item):continue
       item.setdefault("expires_at","")
       if item["contact"].lower() in outreach:continue
       if db.execute("SELECT 1 FROM leads WHERE url=? OR fingerprint=?",(item["url"],item["fingerprint"])).fetchone():continue
       db.execute("""INSERT OR IGNORE INTO leads(id,url,channel,published_at,discovered_at,body,category,score,contact,buyer,budget,reason,fingerprint,expires_at)
           VALUES(:id,:url,:channel,:published_at,:discovered_at,:body,:category,:score,:contact,:buyer,:budget,:reason,:fingerprint,:expires_at)""",item)
       if db.execute("SELECT changes()").fetchone()[0]:new.append(item)
     except Exception as e:errors.append(f"{futures[future]}: {str(e)[:100]}")
    # Non-Telegram public boards: check every 15 minutes. Re-run through
    # the button only after a short cooldown, to respect source bandwidth.
    for src in (*EMAIL_SOURCES,*DIRECT_SOURCES,*HH_SOURCES):
     name=src["id"]
     previous=db.execute("SELECT checked_at,last_error FROM email_source_checks WHERE source_id=?",(name,)).fetchone()
     if previous:
      try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(previous["checked_at"])).total_seconds()
      except ValueError:age=999999
      wait = 3600 if name=="hh-direct" and "403" in str(previous["last_error"] or "") else 900
      if age < (120 if force_email and wait == 900 else wait):continue
     count+=1
     check_time=datetime.now(timezone.utc).isoformat()
     try:
      fetcher=(EMAIL_FETCHERS.get(name) or DIRECT_FETCHERS.get(name) or HH_FETCHERS.get(name))
      nposts,items,source_errors=fetcher()
      fetched+=nposts;matched+=sum(1 for item in items if is_direct_lead(item))
      errors.extend(source_errors)
      for item in items:
       if not is_direct_lead(item):continue
       item.setdefault("expires_at","")
       if item["contact"].lower() in outreach:continue
       if db.execute("SELECT 1 FROM leads WHERE url=? OR fingerprint=?",(item["url"],item["fingerprint"])).fetchone():continue
       db.execute("""INSERT OR IGNORE INTO leads(id,url,channel,published_at,discovered_at,body,category,score,contact,buyer,budget,reason,fingerprint,expires_at)
         VALUES(:id,:url,:channel,:published_at,:discovered_at,:body,:category,:score,:contact,:buyer,:budget,:reason,:fingerprint,:expires_at)""",item)
       if db.execute("SELECT changes()").fetchone()[0]:new.append(item)
      err_text="; ".join(source_errors)[:300]
     except Exception as exc:
      nposts=0;items=[];err_text=str(exc)[:300];errors.append(name+": "+err_text)
     db.execute("""INSERT INTO email_source_checks(source_id,checked_at,fetched,matched,last_error)
        VALUES(?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
        checked_at=excluded.checked_at,fetched=excluded.fetched,
        matched=excluded.matched,last_error=excluded.last_error""",
        (name,check_time,nposts,len(items),err_text))
    now=datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO scans(at,sources,posts,matched,new_leads,errors) VALUES(?,?,?,?,?,?)",
       (now,count,fetched,matched,len(new),json.dumps(errors,ensure_ascii=False)))
    db.commit();db.close()
   self.last={"at":now,"sources":count,"posts":fetched,"matched":matched,"new":len(new),"errors":errors}
   if notify and new: notify(new)
   return self.last
  finally:self.active=False;self.lock.release()
 def start(self,notify=None):
  def run():
   while not self.stop.is_set():
    self.scan(notify)
    self.stop.wait(INTERVAL)
  threading.Thread(target=run,name="searchorders-scanner",daemon=True).start()
