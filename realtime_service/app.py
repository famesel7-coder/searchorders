"""Local SearchOrders dashboard + API + notification delivery. No automated outreach."""
import json, os, html, re, sys, threading, urllib.request, urllib.parse, subprocess
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .engine import ROOT,RUNTIME,conn,Monitor,sources,INTERVAL
from .outreach import create_draft
PORT=int(os.environ.get("SEARCHORDERS_PORT","8787"))
HOST=os.environ.get("SEARCHORDERS_HOST","127.0.0.1")
CONFIG=RUNTIME/"settings.json"
monitor=Monitor()
draft_lock=threading.Lock()

def settings():
 if not CONFIG.exists():return {}
 try:return json.loads(CONFIG.read_text())
 except (OSError,ValueError):return {}

def save_settings(data):
 RUNTIME.mkdir(exist_ok=True,parents=True)
 file=CONFIG.with_suffix(".tmp")
 file.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf8")
 os.chmod(file,0o600);file.replace(CONFIG)

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
  if (recent-dt).total_seconds()<=25*60 and row["score"]>=int(s.get("min_alert_score",80)):
   eligible.append(row)
 if eligible and sys.platform=="darwin":
  title="SearchOrders: новые кандидаты"
  message=f"Найдено новых релевантных публикаций: {len(eligible)}. Откройте панель на localhost:8787."
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
  if path in ("/","/index.html"):
   data=(Path(__file__).resolve().parent/"index.html").read_bytes()
   self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
   self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data);return
  if path=="/api/leads":
   q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
   stage=(q.get("stage",["all"])[0]);category=q.get("category",["all"])[0]
   filters=[];values=[]
   if stage!="all":filters.append("stage=?");values.append(stage)
   if category!="all":filters.append("category=?");values.append(category)
   sql="SELECT * FROM leads"+(" WHERE "+" AND ".join(filters) if filters else "")+" ORDER BY published_at DESC LIMIT 600"
   db=conn();rows=[dict(x) for x in db.execute(sql,values).fetchall()];db.close()
   return self.json({"items":rows})
  if path=="/api/status":
   db=conn()
   counts=dict(db.execute("SELECT stage,count(*) FROM leads GROUP BY stage").fetchall())
   bycat=dict(db.execute("SELECT category,count(*) FROM leads WHERE stage!='dismissed' GROUP BY category").fetchall())
   scan=db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
   db.close()
   return self.json({"running":monitor.active,"interval_seconds":INTERVAL,"sources":len(sources()),
     "counts":counts,"by_category":bycat,"last_scan":dict(scan) if scan else None})
  if path=="/api/sources":return self.json({"items":sources()})
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
  try:data=self.readjson()
  except (ValueError,json.JSONDecodeError) as e:return self.json({"error":str(e)},400)
  if path=="/api/draft":
   ident=str(data.get("id", ""))
   if not re.fullmatch(r"[a-f0-9]{20}",ident):
    return self.json({"error":"Неверный идентификатор проекта"},400)
   with draft_lock:
    db=conn()
    try:
     lead=db.execute("SELECT body, buyer, category, contact FROM leads WHERE id=?",(ident,)).fetchone()
     if lead is None:return self.json({"error":"Проект не найден"},404)
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
   return self.json({"ok":True,"draft":draft,"method":method,
       "ai_configured":bool(api_key),"facts":brief["facts"][:5],"contact":lead["contact"]})
  if path=="/api/scan":
   if monitor.active:return self.json({"ok":True,"message":"Scan already in progress"})
   threading.Thread(target=monitor.scan,args=(send_notifications,),daemon=True).start()
   return self.json({"ok":True})
  if path=="/api/lead":
   ident=str(data.get("id",""));stage=str(data.get("stage",""))
   if not re.fullmatch(r"[a-f0-9]{20}",ident) or stage not in ("new","saved","contacted","dismissed"):
    return self.json({"error":"Invalid lead/stage"},400)
   db=conn();db.execute("UPDATE leads SET stage=? WHERE id=?",(stage,ident));db.commit();db.close()
   return self.json({"ok":True})
  if path=="/api/source":
   url=str(data.get("url","")).strip()
   if not re.fullmatch(r"https://t\.me/s/[A-Za-z0-9_]+",url):return self.json({"error":"Нужна публичная ссылка формата https://t.me/s/channel"},400)
   p=RUNTIME/"extra_sources.json";p.parent.mkdir(parents=True,exist_ok=True)
   existing=json.loads(p.read_text()) if p.exists() else []
   if url not in existing:existing.append(url)
   p.write_text(json.dumps(existing,ensure_ascii=False,indent=2))
   return self.json({"ok":True,"sources":len(sources())})
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
 print(f"SearchOrders dashboard: http://{HOST}:{PORT}, Telegram sources: {len(sources())}, interval: {INTERVAL}s",flush=True)
 try:server.serve_forever(poll_interval=.4)
 except KeyboardInterrupt:pass
 finally:monitor.stop.set();server.server_close()

if __name__=="__main__":main()
