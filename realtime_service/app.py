"""Local SearchOrders dashboard + API + notification delivery. No automated outreach."""
import json, os, html, re, sys, threading, urllib.request, urllib.parse, subprocess
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .engine import ROOT,RUNTIME,conn,Monitor,sources,INTERVAL
from .email_sources import SOURCES as EMAIL_SOURCES
from .platform_sources import SOURCES as PLATFORM_SOURCES
from .outreach import create_draft, subject_for_brief
from .translation import looks_english,body_digest,translate_to_russian
PORT=int(os.environ.get("SEARCHORDERS_PORT","8787"))
HOST=os.environ.get("SEARCHORDERS_HOST","127.0.0.1")
CONFIG=RUNTIME/"settings.json"
monitor=Monitor()
draft_lock=threading.Lock()
translation_lock=threading.Lock()

def settings():
 if not CONFIG.exists():return {}
 try:return json.loads(CONFIG.read_text())
 except (OSError,ValueError):return {}

def save_settings(data):
 RUNTIME.mkdir(exist_ok=True,parents=True)
 file=CONFIG.with_suffix(".tmp")
 fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 os.fchmod(fd,0o600)
 with os.fdopen(fd,"w",encoding="utf8") as f:
  json.dump(data,f,ensure_ascii=False,indent=2)
 file.replace(CONFIG)

def telegram(method,payload,token):
 body=json.dumps(payload).encode()
 req=urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",data=body,
 headers={"Content-Type":"application/json"},method="POST")
 with urllib.request.urlopen(req,timeout=10) as res:return json.load(res)

def send_notifications(rows):
 s=settings();token=s.get("telegram_token","");chat=s.get("telegram_chat_id","")
 recent=datetime.now(timezone.utc)
 eligible=[]
 for row in rows:
  dt=datetime.fromisoformat(row["published_at"])
  if ((recent-dt).total_seconds()<=25*60 and row["score"]>=int(s.get("min_alert_score",80))
      and re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}",str(row.get("contact", "")))):
   eligible.append(row)
 if eligible and sys.platform=="darwin":
  title="SearchOrders: email-заявки"
  message=f"Новых заявок с опубликованным email: {len(eligible)}. Откройте панель."
  try:subprocess.run(["/usr/bin/osascript","-e",f'display notification "{message}" with title "{title}"'],timeout=5,capture_output=True)
  except Exception as e:print("Local notification:",str(e)[:100],file=sys.stderr)
 if not token or not chat:return
 for row in eligible:
  caption={
   "web":"Сайты","uiux":"UI/UX","presentations":"Презентации","branding":"Брендинг / графика"
  }.get(row["category"],row["category"])
  message=(f"🔎 <b>Новый кандидат: {html.escape(caption)}</b>\n"
     f"Оценка: {row['score']}/99 · {html.escape(row['channel'])}\n"
     f"Контакт: {html.escape(row['contact'])}\n"
     f"{html.escape(row['body'][:750])}\n\n"
     f"<a href=\"{html.escape(row['url'],quote=True)}\">Первоисточник</a>\n"
     "⚠️ Проверьте заказчика и актуальность перед откликом.")
  try:
   result=telegram("sendMessage",{"chat_id":chat,"text":message,"parse_mode":"HTML","disable_web_page_preview":True},token)
   if result.get("ok"):
    db=conn();db.execute("UPDATE leads SET notified=1 WHERE id=?",(row["id"],));db.commit();db.close()
  except Exception as e:print("Telegram failed:",str(e)[:130],file=sys.stderr)

class Handler(BaseHTTPRequestHandler):
 def log_message(self,fmt,*args):print("%s %s"%(self.log_date_time_string(),fmt%args))
 def json(self,obj,status=200):
  encoded=json.dumps(obj,ensure_ascii=False,default=str).encode("utf8")
  self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(encoded)))
  self.end_headers();self.wfile.write(encoded)
 def readjson(self):
  length=int(self.headers.get("Content-Length","0"))
  if length>8000:raise ValueError("Payload too large")
  return json.loads(self.rfile.read(length) or b"{}")
 def do_GET(self):
  path=urllib.parse.urlsplit(self.path).path
  if path in ("/","/index.html","/contacted","/contacted/","/saved","/saved/","/hidden","/hidden/","/without-email","/without-email/","/platforms","/platforms/"):
   data=(Path(__file__).resolve().parent/"index.html").read_bytes()
   self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
   self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data);return
  if path=="/api/leads":
   q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
   stage=(q.get("stage",["all"])[0]);category=q.get("category",["all"])[0]
   email_only=q.get("email_only",["0"])[0]=="1"
   filters=[];values=[]
   if stage=="contacted":filters.append("contacted=1 AND stage!='dismissed'")
   elif stage=="not_contacted":
    filters.append("""contacted=0 AND stage!='dismissed'
        AND lower(contact) NOT IN
        (SELECT lower(contact) FROM leads WHERE contacted=1 OR stage='dismissed')""")
   elif stage=="saved":filters.append("saved=1 AND stage!='dismissed'")
   elif stage=="dismissed":filters.append("stage='dismissed'")
   elif stage=="without_email":
    filters.append("contacted=0 AND stage!='dismissed' AND contact LIKE '@%' AND lower(contact) NOT IN (SELECT lower(contact) FROM leads WHERE contacted=1 OR stage='dismissed')")
   elif stage=="platform":
    filters.append("channel='workspace-tender' AND contacted=0 AND stage!='dismissed' AND (expires_at='' OR expires_at>=DATE('now'))")
   if email_only:
    filters.append("contact NOT LIKE '@%' AND contact LIKE '%@%.%'")
    filters.append("(expires_at='' OR expires_at>=DATE('now'))")
   if category!="all":filters.append("category=?");values.append(category)
   sql="SELECT * FROM leads"+(" WHERE "+" AND ".join(filters) if filters else "")+" ORDER BY published_at DESC LIMIT 600"
   db=conn();rows=[dict(x) for x in db.execute(sql,values).fetchall()];db.close()
   return self.json({"items":rows})
  if path=="/api/status":
   db=conn()
   counts={
      "new":db.execute("""SELECT COUNT(*) FROM leads WHERE contacted=0 AND stage!='dismissed'
         AND lower(contact) NOT IN
         (SELECT lower(contact) FROM leads WHERE contacted=1 OR stage='dismissed')""").fetchone()[0],
      "contacted":db.execute("SELECT COUNT(*) FROM leads WHERE contacted=1 AND stage!='dismissed'").fetchone()[0],
      "saved":db.execute("SELECT COUNT(*) FROM leads WHERE saved=1 AND stage!='dismissed'").fetchone()[0],
      "dismissed":db.execute("SELECT COUNT(*) FROM leads WHERE stage='dismissed'").fetchone()[0],
      "email_new":db.execute("SELECT COUNT(*) FROM leads WHERE contacted=0 AND stage!='dismissed' AND contact NOT LIKE '@%' AND contact LIKE '%@%.%' AND (expires_at='' OR expires_at>=DATE('now')) AND lower(contact) NOT IN (SELECT lower(contact) FROM leads WHERE contacted=1 OR stage='dismissed')").fetchone()[0],
      "without_email":db.execute("SELECT COUNT(*) FROM leads WHERE contacted=0 AND stage!='dismissed' AND contact LIKE '@%' AND lower(contact) NOT IN (SELECT lower(contact) FROM leads WHERE contacted=1 OR stage='dismissed')").fetchone()[0],
      "platform_new":db.execute("SELECT COUNT(*) FROM leads WHERE channel='workspace-tender' AND contacted=0 AND stage!='dismissed' AND (expires_at='' OR expires_at>=DATE('now'))").fetchone()[0]
   }
   bycat=dict(db.execute("SELECT category,count(*) FROM leads WHERE stage!='dismissed' GROUP BY category").fetchall())
   scan=db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
   total_count=db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
   checks=[dict(x) for x in db.execute("SELECT * FROM email_source_checks ORDER BY source_id").fetchall()]
   db.close()
   return self.json({"running":monitor.active,"interval_seconds":INTERVAL,"sources":len(sources())+len(EMAIL_SOURCES)+len(PLATFORM_SOURCES),
     "email_sources":checks,
     "counts":counts,"total_leads":total_count,"by_category":bycat,"last_scan":dict(scan) if scan else None})
  if path=="/api/sources":
   return self.json({"items":sources()+[row["url"] for row in (*EMAIL_SOURCES,*PLATFORM_SOURCES)],
      "email_sources":[{"id":row["id"],"name":row["title"],"url":row["url"]} for row in (*EMAIL_SOURCES,*PLATFORM_SOURCES)]})
  if path=="/api/settings":
   conf=settings()
   return self.json({"telegram_configured":bool(conf.get("telegram_token")),"telegram_chat_id":conf.get("telegram_chat_id",""),
      "min_alert_score":int(conf.get("min_alert_score",80)),
      "ai_configured":bool(os.environ.get("OPENAI_API_KEY") or conf.get("openai_api_key")),
      "ai_model":os.environ.get("SEARCHORDERS_AI_MODEL",conf.get("ai_model","gpt-4.1-mini"))})
  self.json({"error":"Not found"},404)
 def do_POST(self):
  # The dashboard is intentionally localhost-only by default.
  path=urllib.parse.urlsplit(self.path).path
  if path=="/api/settings":
   origin=self.headers.get("Origin")
   expected="http://"+self.headers.get("Host","127.0.0.1:"+str(PORT))
   if origin and origin!=expected:
    return self.json({"error":"Отклонён запрос с другого сайта"},403)
   content_type=self.headers.get("Content-Type","").split(";")[0].strip().lower()
   if content_type!="application/json":
    return self.json({"error":"Ожидался JSON-запрос из SearchOrders"},415)
  try:data=self.readjson()
  except (ValueError,json.JSONDecodeError) as e:return self.json({"error":str(e)},400)
  if path=="/api/translate":
   ident=str(data.get("id",""))
   lang=str(data.get("target","ru"))
   if not re.fullmatch(r"[a-f0-9]{20}",ident) or lang!="ru":
    return self.json({"error":"Неверный идентификатор или язык"},400)
   # SQLite cache is bound to the exact original body hash. Any new text
   # automatically invalidates an old translation for the same lead.
   with translation_lock:
    db=conn()
    try:
     row=db.execute("SELECT body FROM leads WHERE id=?",(ident,)).fetchone()
     if row is None:return self.json({"error":"Заказ не найден"},404)
     source=row["body"] or ""
     if not looks_english(source):
      return self.json({"error":"Этот текст уже на русском или язык не распознан"},409)
     digest=body_digest(source)
     cached=db.execute("SELECT translated_body FROM translation_cache WHERE lead_id=? AND source_digest=?",
       (ident,digest)).fetchone()
     if cached:return self.json({"ok":True,"translation":cached["translated_body"],
                                   "target":"ru","cached":True})
    finally:db.close()
    try:
     text=translate_to_russian(source)
    except Exception as exc:
     # Never claim success or replace the original text after provider failure.
     print("Translation error:",str(exc)[:200],file=sys.stderr)
     return self.json({"error":"Перевод временно недоступен. Оригинальный текст сохранён, попробуйте ещё раз."},502)
    db=conn()
    try:
     db.execute("""INSERT OR REPLACE INTO translation_cache(lead_id,source_digest,translated_body,translated_at)
        VALUES(?,?,?,?)""",(ident,digest,text,datetime.now(timezone.utc).isoformat()))
     db.commit()
    finally:db.close()
    return self.json({"ok":True,"translation":text,"target":"ru","cached":False})
  if path=="/api/draft":
   ident=str(data.get("id", ""))
   if not re.fullmatch(r"[a-f0-9]{20}",ident):
    return self.json({"error":"Неверный идентификатор проекта"},400)
   with draft_lock:
    db=conn()
    try:
     lead=db.execute("SELECT body, buyer, category, contact, channel FROM leads WHERE id=?",(ident,)).fetchone()
     if lead is None:return self.json({"error":"Проект не найден"},404)
     is_tender=lead["channel"]=="workspace-tender"
     if not is_tender and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}",lead["contact"]):
      return self.json({"error":"У заказчика нет опубликованного email. Отправка письма недоступна."},409)
     past=db.execute("""SELECT content FROM draft_history
       ORDER BY CASE WHEN lead_id=? THEN 0 ELSE 1 END, id DESC LIMIT 30""",(ident,)).fetchall()
     previous=[x["content"] for x in past]
     conf=settings()
     api_key=os.environ.get("OPENAI_API_KEY") or conf.get("openai_api_key","")
     model=os.environ.get("SEARCHORDERS_AI_MODEL") or conf.get("ai_model","gpt-4.1-mini")
     draft,method,brief=create_draft(dict(lead),previous=previous,api_key=api_key,model=model)
     # Make each regeneration different, even without an API key.
     for attempt in range(5):
      if all(draft != earlier for earlier in previous):break
      draft,method,brief=create_draft(dict(lead),previous=previous,api_key="",model=model)
     if draft in previous:
      return self.json({"error":"Не удалось получить новый вариант: повторите попытку"},503)
     db.execute("INSERT INTO draft_history(lead_id,content,method,created_at) VALUES(?,?,?,?)",
      (ident,draft,method,datetime.now(timezone.utc).isoformat()))
     db.commit()
    finally:db.close()
   return self.json({"ok":True,"draft":draft,"subject":subject_for_brief(brief),
       "method":method,"ai_configured":bool(api_key),"facts":brief["facts"][:5],
       "contact":lead["contact"],"application_mode":is_tender,
       "from_address":"cco@imon.agency"})
  if path=="/api/lead/manual":
   address=str(data.get("email") or "").strip().lower()
   url=str(data.get("url") or "").strip()
   body=str(data.get("brief") or "").strip()
   buyer=str(data.get("buyer") or "").strip()
   if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",address):
    return self.json({"error":"Укажите реальный email из объявления"},400)
   parsed=urllib.parse.urlparse(url)
   if parsed.scheme not in ("http","https") or not parsed.hostname or len(url)>1000:
    return self.json({"error":"Добавьте ссылку на первоисточник"},400)
   if len(body)<35 or len(body)>3600:
    return self.json({"error":"Вставьте описание задачи (35–3600 символов)"},400)
   if len(buyer)>150:return self.json({"error":"Слишком длинное имя заказчика"},400)
   from .outreach import analyse_brief
   from .engine import CATEGORIES
   import hashlib
   category_counts={k:len(re.findall(pattern,body,re.I)) for k,(label,pattern) in CATEGORIES.items()}
   category=max(category_counts,key=category_counts.get)
   if category_counts[category]==0:return self.json({"error":"Не удалось определить дизайн-задачу по тексту"},400)
   leadid=hashlib.sha1((url+"|"+address).encode()).hexdigest()[:20]
   db=conn()
   try:
    blocked=db.execute("SELECT 1 FROM leads WHERE lower(contact)=? AND (contacted=1 OR stage='dismissed') LIMIT 1",(address,)).fetchone()
    if blocked:return self.json({"error":"Этот контакт ранее отмечен «Написал» или скрыт. Не добавляем повторно."},409)
    existing=db.execute("SELECT id FROM leads WHERE url=? OR id=? LIMIT 1",(url,leadid)).fetchone()
    if existing:return self.json({"error":"Такой заказ уже есть в базе"},409)
    now=datetime.now(timezone.utc).isoformat()
    db.execute("""INSERT INTO leads(id,url,channel,published_at,discovered_at,body,category,score,contact,buyer,budget,reason,fingerprint)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (leadid,url,"manual-email",now,now,body,category,75,address,buyer,"",
       "Добавлено вручную по ссылке. Дата карточки — время добавления, а не дата публикации.",
       hashlib.sha1((url+"|"+address).encode()).hexdigest()))
    db.commit()
   finally:db.close()
   return self.json({"ok":True,"id":leadid,"message":"Email-заказ добавлен"})
  if path=="/api/scan":
   if monitor.active:return self.json({"ok":True,"message":"Scan already in progress"})
   threading.Thread(target=monitor.scan,args=(send_notifications,),kwargs={"force_email":True},daemon=True).start()
   return self.json({"ok":True})
  if path=="/api/lead":
   ident=str(data.get("id",""))
   field=str(data.get("field",""))
   value=data.get("value")
   if not re.fullmatch(r"[a-f0-9]{20}",ident):
    return self.json({"error":"Invalid lead"},400)
   if field not in ("contacted","saved","hidden") or type(value) is not bool:
    return self.json({"error":"Invalid status update"},400)
   db=conn()
   try:
    if field=="contacted":
     db.execute("UPDATE leads SET contacted=? WHERE id=?",(int(value),ident))
    elif field=="saved":
     db.execute("UPDATE leads SET saved=? WHERE id=?",(int(value),ident))
    else:
     db.execute("UPDATE leads SET stage=? WHERE id=?",("dismissed" if value else "new",ident))
    db.commit()
    row=db.execute("SELECT contacted,saved,stage FROM leads WHERE id=?",(ident,)).fetchone()
   finally: db.close()
   if not row:return self.json({"error":"Project not found"},404)
   return self.json({"ok":True,"lead":{"contacted":row["contacted"],"saved":row["saved"],"stage":row["stage"]}})
  if path=="/api/source":
   url=str(data.get("url","")).strip()
   if not re.fullmatch(r"https://t\.me/s/[A-Za-z0-9_]+",url):return self.json({"error":"Нужна публичная ссылка формата https://t.me/s/channel"},400)
   p=RUNTIME/"extra_sources.json";p.parent.mkdir(parents=True,exist_ok=True)
   existing=json.loads(p.read_text()) if p.exists() else []
   if url not in existing:existing.append(url)
   p.write_text(json.dumps(existing,ensure_ascii=False,indent=2))
   return self.json({"ok":True,"sources":len(sources())+len(EMAIL_SOURCES)})
  if path=="/api/settings":
   c=settings()
   token=data.get("telegram_token")
   if isinstance(token,str) and token.strip():
    if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{25,}",token.strip()):
     return self.json({"error":"Неверный формат токена Telegram"},400)
    c["telegram_token"]=token.strip()
   if "telegram_chat_id" in data:
    chat=str(data.get("telegram_chat_id","")).strip()
    if chat and not re.fullmatch(r"-?\d{4,18}",chat):return self.json({"error":"Chat ID должен содержать цифры"},400)
    c["telegram_chat_id"]=chat
   if "min_alert_score" in data:c["min_alert_score"]=max(60,min(99,int(data["min_alert_score"])))
   if "openai_api_key" in data:
    key=str(data.get("openai_api_key") or "").strip()
    if key and not re.fullmatch(r"sk-[A-Za-z0-9_\-]{15,250}",key):
     return self.json({"error":"Проверьте формат ключа OpenAI API"},400)
    if key:c["openai_api_key"]=key
   if data.get("remove_ai_key") is True:c.pop("openai_api_key",None)
   if "ai_model" in data:
    model=str(data["ai_model"]).strip()
    if not re.fullmatch(r"[a-zA-Z0-9._-]{3,64}",model):return self.json({"error":"Недопустимое имя модели"},400)
    c["ai_model"]=model
   save_settings(c)
   return self.json({"ok":True,"telegram_configured":bool(c.get("telegram_token")),
        "telegram_chat_id":c.get("telegram_chat_id",""),
        "ai_configured":bool(os.environ.get("OPENAI_API_KEY") or c.get("openai_api_key"))})
  if path=="/api/telegram/discover":
   conf=settings();token=conf.get("telegram_token")
   if not token:return self.json({"error":"Сначала сохраните токен бота"},400)
   try:
    res=telegram("getUpdates",{"limit":20},token)
    chats=[str(x.get("message",{}).get("chat",{}).get("id","")) for x in res.get("result",[]) if x.get("message")]
    chats=[x for x in chats if x]
    if not chats:return self.json({"error":"Сначала напишите /start своему боту в Telegram"},409)
    conf["telegram_chat_id"]=chats[-1];save_settings(conf)
    return self.json({"ok":True,"chat_id":chats[-1]})
   except Exception as e:return self.json({"error":"Telegram: "+str(e)[:150]},502)
  if path=="/api/telegram/test":
   conf=settings()
   if not (conf.get("telegram_token") and conf.get("telegram_chat_id")):return self.json({"error":"Бот не подключён"},409)
   try:
    res=telegram("sendMessage",{"chat_id":conf["telegram_chat_id"],"text":"✅ SearchOrders подключён. Новые подходящие заказы будут приходить сюда."},conf["telegram_token"])
    return self.json({"ok":bool(res.get("ok"))})
   except Exception as e:return self.json({"error":"Telegram: "+str(e)[:150]},502)
  return self.json({"error":"Not found"},404)

def main():
 server=ThreadingHTTPServer((HOST,PORT),Handler)
 monitor.start(send_notifications)
 print(f"SearchOrders dashboard: http://{HOST}:{PORT}, Telegram sources: {len(sources())}, public board sources: {len(EMAIL_SOURCES)+len(PLATFORM_SOURCES)}, interval: {INTERVAL}s",flush=True)
 try:server.serve_forever(poll_interval=.4)
 except KeyboardInterrupt:pass
 finally:monitor.stop.set();server.server_close()

if __name__=="__main__":main()
