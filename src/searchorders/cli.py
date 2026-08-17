from __future__ import annotations
import argparse,json,os,sys
from datetime import datetime
from pathlib import Path
from typing import Any
from .catalog import CatalogStore
from .config import ConfigurationError,load_cases,load_search_profile,load_sources
from .models import Lead
from .normalization import enrich_lead
from .pipeline import evaluate_leads
from .results_store import write_results
from .scan import scan_sources
from .telegram_bot import SearchOrdersBot,TelegramBotError,api_from_environment
from .telegram_client_api import TelegramClientSetupError,create_telegram_session_sync,list_telegram_dialogs_sync
from .web import serve_web
def _parse_datetime(value:Any)->datetime|None:
    if not isinstance(value,str) or not value:return None
    try:return datetime.fromisoformat(value)
    except ValueError:return None
def _lead_from_dict(data:dict[str,Any])->Lead:
    return enrich_lead(Lead(source=str(data.get("source","fixture")),source_id=data.get("source_id"),source_name=data.get("source_name"),author_name=data.get("author_name"),external_id=str(data.get("external_id",data.get("id","unknown"))),title=str(data.get("title","")),description=str(data.get("description","")),url=data.get("url"),company_name=data.get("company_name"),company_url=data.get("company_url"),published_at=_parse_datetime(data.get("published_at")),area=data.get("area"),employment=data.get("employment"),schedule=data.get("schedule"),accept_temporary=bool(data.get("accept_temporary",False)),salary_from=data.get("salary_from"),salary_to=data.get("salary_to"),budget_from=data.get("budget_from"),budget_to=data.get("budget_to"),currency=data.get("currency"),has_direct_contact=bool(data.get("has_direct_contact",False)),contacts=[str(x) for x in data.get("contacts",[]) if str(x).strip()] if isinstance(data.get("contacts",[]),list) else [],raw=data.get("raw",{}) if isinstance(data.get("raw",{}),dict) else {}))
def _read_leads(path:Path)->list[Lead]:
    payload=json.loads(path.read_text(encoding="utf-8")); payload=payload.get("leads",payload.get("items",[])) if isinstance(payload,dict) else payload
    if not isinstance(payload,list):raise ValueError("Input JSON must be a list or contain a 'leads'/'items' list")
    return [_lead_from_dict(x) for x in payload if isinstance(x,dict)]
def _common_paths(p:argparse.ArgumentParser)->None:p.add_argument("--profile",default="data/search-profile.yaml",type=Path);p.add_argument("--cases",default="data/cases.yaml",type=Path);p.add_argument("--output",default="output/leads.json",type=Path)
def _scan_paths(p:argparse.ArgumentParser)->None:_common_paths(p);p.add_argument("--sources",default="data/sources.yaml",type=Path);p.add_argument("--state",default="state/searchorders.db",type=Path);p.add_argument("--max-results",type=int,default=30)
def _telegram_credentials_args(p:argparse.ArgumentParser)->None:p.add_argument("--api-id",type=int);p.add_argument("--api-hash")
def build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="search-orders",description="Social/community demand intelligence for I’MON Digital Agency"); s=p.add_subparsers(dest="command",required=True)
    e=s.add_parser("evaluate");_common_paths(e);e.add_argument("input",type=Path)
    scan=s.add_parser("scan");_scan_paths(scan)
    web=s.add_parser("web");_scan_paths(web);web.add_argument("--host",default="127.0.0.1");web.add_argument("--port",type=int,default=8080);web.add_argument("--title",default="I’MON Search Orders")
    bot=s.add_parser("bot");_scan_paths(bot);bot.add_argument("--max-leads-per-run",type=int,default=7)
    cat=s.add_parser("catalog");cat.add_argument("--state",default="state/searchorders.db",type=Path);cat.add_argument("--limit",type=int,default=200);cat.add_argument("--output",type=Path)
    ss=s.add_parser("sources-status");ss.add_argument("--state",default="state/searchorders.db",type=Path)
    ta=s.add_parser("telegram-auth");_telegram_credentials_args(ta);ta.add_argument("--phone");ta.add_argument("--env-file",type=Path,default=Path(".env"));ta.add_argument("--print-only",action="store_true")
    td=s.add_parser("telegram-dialogs");_telegram_credentials_args(td);td.add_argument("--session");td.add_argument("--limit",type=int,default=100);return p
def _scan_once(args:argparse.Namespace,profile:dict[str,Any],cases:list[dict[str,Any]])->Any:return scan_sources(profile,cases,load_sources(args.sources),state_path=args.state,max_results=max(1,args.max_results))
def run_evaluate(args,profile,cases)->int:
    ev=evaluate_leads(_read_leads(args.input),profile,cases);write_results(args.output,ev);print(f"Saved {len(ev)} evaluated leads to {args.output}");return 0
def run_scan(args,profile,cases)->int:
    r=_scan_once(args,profile,cases);write_results(args.output,r.evaluations);print(f"Collected {r.collected_count}; new posts {r.new_post_count}; new canonical leads {r.new_count}; run #{r.run_id}");[print(f"Warning: {w}",file=sys.stderr) for w in r.warnings];return 0
def run_bot(args,profile,cases)->int:SearchOrdersBot(api_from_environment(),lambda:_scan_once(args,profile,cases),allowed_chat_id=os.getenv("TELEGRAM_CHAT_ID"),max_leads_per_run=max(1,args.max_leads_per_run)).run_forever();return 0
def run_web(args,profile,cases)->int:
    server=serve_web(lambda:_scan_once(args,profile,cases),state_path=args.state,host=args.host,port=args.port,title=args.title)
    try:server.serve_forever()
    except KeyboardInterrupt:print("Stopping web UI...")
    finally:server.server_close()
    return 0
def run_catalog(args)->int:
    text=json.dumps(CatalogStore(args.state).catalog_payload(limit=max(1,args.limit)),ensure_ascii=False,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text+"\n",encoding="utf-8")
    else:print(text)
    return 0
def run_sources_status(args)->int:
    for row in CatalogStore(args.state).source_stats():print(f"{row['source_id']}\t{row['source_type']}\tposts={row['posts_seen']}\tleads={row['leads_found']}\terror={row['last_error'] or '-'}")
    return 0
def _upsert_env_file(path:Path,updates:dict[str,str])->None:
    lines=path.read_text(encoding="utf-8").splitlines() if path.exists() else [];remaining=dict(updates);out=[]
    for line in lines:
        stripped=line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:out.append(line);continue
        key,_,_=line.partition("=");out.append(f"{key}={remaining.pop(key)}" if key in remaining else line)
    out.extend(f"{k}={v}" for k,v in remaining.items());path.write_text("\n".join(out)+"\n",encoding="utf-8")
def run_telegram_auth(args)->int:
    phone=str(args.phone or "").strip() or input("Telegram phone number: ").strip()
    if not phone:raise TelegramClientSetupError("Phone number is required for Telegram login")
    session=create_telegram_session_sync(api_id=args.api_id,api_hash=args.api_hash,phone=phone)
    if args.print_only:print(session);return 0
    updates={"TELEGRAM_SESSION":session}
    if args.api_id is not None:updates["TELEGRAM_API_ID"]=str(args.api_id)
    if args.api_hash:updates["TELEGRAM_API_HASH"]=str(args.api_hash)
    _upsert_env_file(args.env_file,updates);return 0
def run_telegram_dialogs(args)->int:
    rows=list_telegram_dialogs_sync(api_id=args.api_id,api_hash=args.api_hash,session_string=args.session,limit=args.limit)
    for row in rows:print(f"{row['type']}\t{row['ref']}\t{row['name']}{' @'+row['username'] if row.get('username') else ''}")
    return 0
def main(argv:list[str]|None=None)->int:
    p=build_parser();args=p.parse_args(argv)
    try:
        if args.command=="telegram-auth":return run_telegram_auth(args)
        if args.command=="telegram-dialogs":return run_telegram_dialogs(args)
        if args.command=="catalog":return run_catalog(args)
        if args.command=="sources-status":return run_sources_status(args)
        profile=load_search_profile(args.profile);cases=load_cases(args.cases)
        if args.command=="evaluate":return run_evaluate(args,profile,cases)
        if args.command=="scan":return run_scan(args,profile,cases)
        if args.command=="web":return run_web(args,profile,cases)
        if args.command=="bot":return run_bot(args,profile,cases)
    except(ConfigurationError,OSError,TelegramBotError,TelegramClientSetupError,ValueError) as exc:print(f"Error: {exc}",file=sys.stderr);return 1
    return 2
if __name__=="__main__":raise SystemExit(main())
