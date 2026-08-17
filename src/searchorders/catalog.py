from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .dedupe import DedupGroup
from .models import Lead, LeadEvaluation
from .normalization import contact_set, content_fingerprint, normalize_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CatalogStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._initialize()
    def _connect(self) -> sqlite3.Connection:
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row; db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA foreign_keys=ON"); return db
    def _initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS scan_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL DEFAULT 'running',collected_count INTEGER NOT NULL DEFAULT 0,new_post_count INTEGER NOT NULL DEFAULT 0,new_lead_count INTEGER NOT NULL DEFAULT 0,warning_count INTEGER NOT NULL DEFAULT 0,warnings_json TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_name TEXT,source_url TEXT,priority TEXT,enabled INTEGER NOT NULL DEFAULT 1,last_scan_at TEXT,last_success_at TEXT,last_error TEXT,posts_seen INTEGER NOT NULL DEFAULT 0,leads_found INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL,platform TEXT NOT NULL,external_id TEXT NOT NULL,source_name TEXT,title TEXT NOT NULL,description TEXT NOT NULL,url TEXT,author_name TEXT,published_at TEXT,discovered_at TEXT NOT NULL,content_hash TEXT NOT NULL,raw_json TEXT NOT NULL DEFAULT '{}',first_run_id INTEGER,last_run_id INTEGER,UNIQUE(source_id,external_id),FOREIGN KEY(source_id) REFERENCES sources(source_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_hash TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,company_name TEXT,company_url TEXT,budget_from INTEGER,budget_to INTEGER,currency TEXT,contacts_json TEXT NOT NULL DEFAULT '[]',status TEXT NOT NULL DEFAULT 'new',bucket TEXT,score INTEGER,classification_json TEXT NOT NULL DEFAULT '{}',evaluation_json TEXT NOT NULL DEFAULT '{}',first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads(last_seen_at DESC); CREATE INDEX IF NOT EXISTS idx_leads_bucket ON leads(bucket);
            CREATE TABLE IF NOT EXISTS lead_posts(lead_id INTEGER NOT NULL,post_id INTEGER NOT NULL,PRIMARY KEY(lead_id,post_id),FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE,FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS lead_status_history(id INTEGER PRIMARY KEY AUTOINCREMENT,lead_id INTEGER NOT NULL,status TEXT NOT NULL,changed_at TEXT NOT NULL,FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE);
            """)
    def begin_run(self)->int:
        with closing(self._connect()) as db, db:return int(db.execute("INSERT INTO scan_runs(started_at) VALUES (?)",(_now(),)).lastrowid)
    def finish_run(self,run_id:int,*,status:str,collected_count:int,new_post_count:int,new_lead_count:int,warnings:list[str])->None:
        with closing(self._connect()) as db, db:db.execute("UPDATE scan_runs SET finished_at=?,status=?,collected_count=?,new_post_count=?,new_lead_count=?,warning_count=?,warnings_json=? WHERE id=?",(_now(),status,collected_count,new_post_count,new_lead_count,len(warnings),json.dumps(warnings,ensure_ascii=False),run_id))
    def register_source(self,source:dict[str,Any])->None:
        sid=str(source.get("id") or source.get("type") or "unknown"); urls=source.get("listing_urls") or []; first=str(urls[0]) if isinstance(urls,list) and urls else None
        with closing(self._connect()) as db, db:db.execute("INSERT INTO sources(source_id,source_type,source_name,source_url,priority,enabled) VALUES(?,?,?,?,?,1) ON CONFLICT(source_id) DO UPDATE SET source_type=excluded.source_type,source_name=excluded.source_name,source_url=excluded.source_url,priority=excluded.priority,enabled=1",(sid,str(source.get("type") or "unknown"),source.get("name"),first,source.get("priority")))
    def record_source_result(self,source_id:str,*,posts_seen:int,leads_found:int=0,error:str|None=None)->None:
        now=_now()
        with closing(self._connect()) as db, db:db.execute("UPDATE sources SET last_scan_at=?,last_success_at=CASE WHEN ? IS NULL THEN ? ELSE last_success_at END,last_error=?,posts_seen=posts_seen+?,leads_found=leads_found+? WHERE source_id=?",(now,error,now,error,posts_seen,leads_found,source_id))
    def upsert_post(self,lead:Lead,run_id:int)->tuple[int,bool]:
        sid=lead.source_id or lead.source
        with closing(self._connect()) as db, db:
            row=db.execute("SELECT id FROM posts WHERE source_id=? AND external_id=?",(sid,lead.external_id)).fetchone()
            if row:
                pid=int(row["id"]); db.execute("UPDATE posts SET last_run_id=? WHERE id=?",(run_id,pid)); return pid,False
            cur=db.execute("INSERT INTO posts(source_id,platform,external_id,source_name,title,description,url,author_name,published_at,discovered_at,content_hash,raw_json,first_run_id,last_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sid,lead.source,lead.external_id,lead.source_name,lead.title,lead.description,lead.url,lead.author_name,lead.published_at.isoformat() if lead.published_at else None,lead.discovered_at.isoformat(),content_fingerprint(lead),json.dumps(lead.raw,ensure_ascii=False,default=str),run_id,run_id)); return int(cur.lastrowid),True
    @staticmethod
    def _similar_text(left:str,right:str)->float:return SequenceMatcher(None,normalize_text(left)[:6000],normalize_text(right)[:6000],autojunk=False).ratio()
    def _find_similar_lead(self,db:sqlite3.Connection,lead:Lead)->int|None:
        new_contacts=contact_set(lead); new_text=f"{lead.title} {lead.description}"
        for row in db.execute("SELECT id,title,description,contacts_json FROM leads ORDER BY last_seen_at DESC LIMIT 500").fetchall():
            old_contacts={str(x).casefold() for x in json.loads(row["contacts_json"] or "[]")}; score=self._similar_text(new_text,f"{row['title']} {row['description']}")
            if score>=.94 or (new_contacts&old_contacts and score>=.78):return int(row["id"])
        return None
    def save_group(self,group:DedupGroup,evaluation:LeadEvaluation,post_ids:list[int])->tuple[int,bool]:
        lead=evaluation.lead; now=_now()
        with closing(self._connect()) as db, db:
            lead_id=self._find_similar_lead(db,lead); created=lead_id is None
            if created:
                cur=db.execute("INSERT INTO leads(canonical_hash,title,description,company_name,company_url,budget_from,budget_to,currency,contacts_json,status,bucket,score,classification_json,evaluation_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,'new',?,?,?,?,?,?)",(content_fingerprint(lead),lead.title,lead.description,lead.company_name,lead.company_url,lead.effective_budget_from,lead.effective_budget_to,lead.currency,json.dumps(lead.contacts,ensure_ascii=False),evaluation.score.bucket,evaluation.score.total,json.dumps(evaluation.classification.to_dict(),ensure_ascii=False),json.dumps(evaluation.to_dict(),ensure_ascii=False,default=str),now,now)); lead_id=int(cur.lastrowid); db.execute("INSERT INTO lead_status_history(lead_id,status,changed_at) VALUES(?,'new',?)",(lead_id,now))
            else:db.execute("UPDATE leads SET last_seen_at=?,bucket=?,score=?,classification_json=?,evaluation_json=? WHERE id=?",(now,evaluation.score.bucket,evaluation.score.total,json.dumps(evaluation.classification.to_dict(),ensure_ascii=False),json.dumps(evaluation.to_dict(),ensure_ascii=False,default=str),lead_id))
            for pid in post_ids:db.execute("INSERT OR IGNORE INTO lead_posts(lead_id,post_id) VALUES(?,?)",(lead_id,pid))
            return int(lead_id),created
    def set_status(self,lead_id:int,status:str)->None:
        allowed={"new","interesting","review","rejected","contacted","replied","meeting","won","lost","ignored"}
        if status not in allowed:raise ValueError(f"Unsupported lead status: {status}")
        now=_now()
        with closing(self._connect()) as db, db:db.execute("UPDATE leads SET status=? WHERE id=?",(status,lead_id)); db.execute("INSERT INTO lead_status_history(lead_id,status,changed_at) VALUES(?,?,?)",(lead_id,status,now))
    def catalog_payload(self,*,limit:int=200)->dict[str,Any]:
        with closing(self._connect()) as db:
            rows=db.execute("SELECT l.*,COUNT(lp.post_id) AS source_count FROM leads l LEFT JOIN lead_posts lp ON lp.lead_id=l.id GROUP BY l.id ORDER BY CASE l.bucket WHEN 'hot' THEN 0 WHEN 'review' THEN 1 WHEN 'archive' THEN 2 ELSE 3 END,l.score DESC,l.last_seen_at DESC LIMIT ?",(max(1,limit),)).fetchall(); items=[]; counts={"hot":0,"review":0,"archive":0,"rejected":0}
            for row in rows:
                if row["bucket"] in counts:counts[row["bucket"]]+=1
                ev=json.loads(row["evaluation_json"] or "{}"); ev["catalog_id"]=int(row["id"]); ev["catalog_status"]=row["status"]; ev["source_count"]=int(row["source_count"] or 0); items.append(ev)
            total=int(db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]); return {"generated_at":_now(),"summary":{"total":total,**counts},"items":items}
    def source_stats(self)->list[dict[str,Any]]:
        with closing(self._connect()) as db:return [dict(row) for row in db.execute("SELECT * FROM sources ORDER BY priority,source_id").fetchall()]
    def latest_run(self)->dict[str,Any]|None:
        with closing(self._connect()) as db:
            row=db.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone(); return dict(row) if row else None
