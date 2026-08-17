from __future__ import annotations
import base64,html,json,os,threading
from pathlib import Path
from typing import Any,Callable
from wsgiref.simple_server import WSGIServer,make_server
from .catalog import CatalogStore
ScanCallback=Callable[[],Any]
class ScanManager:
    def __init__(self,callback:ScanCallback)->None:self.callback=callback; self.lock=threading.Lock(); self.running=False; self.last_error=None
    def start(self)->bool:
        with self.lock:
            if self.running:return False
            self.running=True; self.last_error=None
        threading.Thread(target=self._run,name="searchorders-scan",daemon=True).start(); return True
    def _run(self)->None:
        try:self.callback()
        except Exception as exc:self.last_error=str(exc)
        finally:
            with self.lock:self.running=False
    def status(self)->dict[str,Any]:return {"running":self.running,"last_error":self.last_error}
def _money(lead:dict[str,Any])->str|None:
    low=lead.get("budget_from") or lead.get("salary_from"); high=lead.get("budget_to") or lead.get("salary_to"); cur=str(lead.get("currency") or "").strip()
    if isinstance(low,int) and isinstance(high,int):return f"{low:,}–{high:,} {cur}".replace(","," ").strip()
    if isinstance(low,int):return f"от {low:,} {cur}".replace(","," ").strip()
    if isinstance(high,int):return f"до {high:,} {cur}".replace(","," ").strip()
    return None
class SearchOrdersWebApp:
    def __init__(self,scan_callback:ScanCallback,*,state_path:Path,title:str,auth_token:str|None=None)->None:self.store=CatalogStore(state_path); self.manager=ScanManager(scan_callback); self.title=title; self.auth_token=(auth_token or "").strip()
    def _authorized(self,environ:dict[str,Any])->bool:
        if not self.auth_token:return True
        header=str(environ.get("HTTP_AUTHORIZATION") or "")
        if not header.startswith("Basic "):return False
        try:decoded=base64.b64decode(header[6:]).decode("utf-8")
        except Exception:return False
        _,_,password=decoded.partition(":"); return password==self.auth_token
    def __call__(self,environ:dict[str,Any],start_response:Callable[...,Any])->list[bytes]:
        path=str(environ.get("PATH_INFO","/"))
        if path=="/healthz":return self._text(start_response,"ok")
        if not self._authorized(environ):
            payload=b"Authentication required"; start_response("401 Unauthorized",[("WWW-Authenticate",'Basic realm="SearchOrders"'),("Content-Type","text/plain; charset=utf-8"),("Content-Length",str(len(payload)))]); return [payload]
        method=str(environ.get("REQUEST_METHOD","GET")).upper()
        if path=="/" and method in {"GET","HEAD"}:return self._html(start_response,self._render(),head=method=="HEAD")
        if path=="/scan" and method=="POST":
            started=self.manager.start(); return self._json(start_response,{"started":started,**self.manager.status()},status="202 Accepted" if started else "409 Conflict")
        if path in {"/results.json","/catalog.json"} and method in {"GET","HEAD"}:return self._json(start_response,self.store.catalog_payload(limit=500),head=method=="HEAD")
        if path=="/sources.json" and method in {"GET","HEAD"}:return self._json(start_response,{"sources":self.store.source_stats()},head=method=="HEAD")
        if path=="/status.json" and method in {"GET","HEAD"}:return self._json(start_response,{**self.manager.status(),"latest_run":self.store.latest_run()},head=method=="HEAD")
        return self._text(start_response,"Not found",status="404 Not Found")
    def _render(self)->str:
        payload=self.store.catalog_payload(limit=100); summary=payload["summary"]; cards=[]
        for item in payload["items"]:
            lead=item.get("lead",{}); score=item.get("score",{}); cls=item.get("classification",{}); budget=_money(lead); refs=int(item.get("source_count") or 0); source=html.escape(str(lead.get("source_name") or lead.get("source") or "unknown")); title=html.escape(str(lead.get("title") or "Без названия")); desc=html.escape(str(lead.get("description") or "")[:500]); url=html.escape(str(lead.get("url") or "")); bucket=html.escape(str(score.get("bucket") or "archive")); intent=html.escape(str(cls.get("intent") or "ambiguous")); budget_markup=f'<p class="budget">{html.escape(budget)}</p>' if budget else ""; link=f'<a href="{url}" target="_blank" rel="noreferrer">Открыть источник</a>' if url else ""; cards.append(f'<article><div class="top"><b>{bucket.upper()}</b><span>{score.get("total",0)}/100</span></div><h3>{title}</h3><p class="meta">{source} · {intent} · источников: {refs}</p>{budget_markup}<p>{desc}</p>{link}</article>')
        scan_label="Сканирование идёт…" if self.manager.running else "Запустить сканирование"
        return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(self.title)}</title><style>body{{font-family:system-ui,sans-serif;margin:0;background:#f4f4f1;color:#171717}}main{{max-width:1180px;margin:auto;padding:24px}}header{{background:#111;color:white;padding:28px;border-radius:22px}}h1{{margin:0 0 8px}}button{{padding:12px 18px;border:0;border-radius:999px;font-weight:700;cursor:pointer}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}.stats div,article{{background:white;border:1px solid #ddd;border-radius:18px;padding:18px}}section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}.top{{display:flex;justify-content:space-between}}.meta{{color:#666;font-size:13px}}.budget{{font-weight:800}}a{{color:#075ea8}}@media(max-width:700px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}</style></head><body><main><header><h1>{html.escape(self.title)}</h1><p>Постоянный каталог спроса из Telegram, VK и других community-источников. Биржи исключены.</p><button id="scan">{scan_label}</button></header><div class="stats"><div><b>{summary['total']}</b><br>Всего</div><div><b>{summary['hot']}</b><br>Hot</div><div><b>{summary['review']}</b><br>Review</div><div><b>{summary['archive']}</b><br>Archive</div></div><section>{''.join(cards) or '<article>Каталог пока пуст.</article>'}</section></main><script>document.getElementById('scan').onclick=async()=>{{let r=await fetch('/scan',{{method:'POST'}});document.getElementById('scan').textContent=r.ok?'Сканирование запущено':'Уже выполняется';setTimeout(()=>location.reload(),2500)}};</script></body></html>'''
    @staticmethod
    def _html(start_response:Callable[...,Any],body:str,*,head:bool=False)->list[bytes]:
        payload=body.encode(); start_response("200 OK",[("Content-Type","text/html; charset=utf-8"),("Cache-Control","no-store"),("Content-Length",str(len(payload)))]); return [] if head else [payload]
    @staticmethod
    def _json(start_response:Callable[...,Any],body:Any,*,status:str="200 OK",head:bool=False)->list[bytes]:
        payload=json.dumps(body,ensure_ascii=False,indent=2,default=str).encode(); start_response(status,[("Content-Type","application/json; charset=utf-8"),("Cache-Control","no-store"),("Content-Length",str(len(payload)))]); return [] if head else [payload]
    @staticmethod
    def _text(start_response:Callable[...,Any],body:str,*,status:str="200 OK")->list[bytes]:
        payload=body.encode(); start_response(status,[("Content-Type","text/plain; charset=utf-8"),("Content-Length",str(len(payload)))]); return [payload]
def serve_web(scan_callback:ScanCallback,*,state_path:Path,host:str,port:int,title:str,auth_token:str|None=None)->WSGIServer:
    token=(auth_token if auth_token is not None else os.getenv("WEB_AUTH_TOKEN","")).strip()
    if host not in {"127.0.0.1","localhost","::1"} and not token:raise ValueError("WEB_AUTH_TOKEN is required when web UI listens on a public interface")
    app=SearchOrdersWebApp(scan_callback,state_path=state_path,title=title,auth_token=token); httpd=make_server(host,port,app); print(f"Serving Search Orders web UI on http://{host}:{port}"); return httpd
