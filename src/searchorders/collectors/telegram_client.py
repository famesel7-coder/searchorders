from __future__ import annotations
import asyncio,re
from datetime import datetime,timezone
from typing import Any
from urllib.parse import urlparse
from ..models import Lead
from ..telegram_client_api import TelegramClientSetupError,create_telegram_client
CONTACT_RE=re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)",re.IGNORECASE)
class TelegramClientCollectorError(RuntimeError):pass
def _normalized(value:str)->str:return value.casefold().replace("ё","е").strip()
def _title_from_text(value:str)->str:
    condensed=" ".join(value.split()); return condensed if len(condensed)<=100 else condensed[:97].rstrip()+"..." if condensed else "Telegram message"
def _normalize_entity_ref(value:str)->str:
    parsed=urlparse(value)
    if parsed.scheme and parsed.netloc:
        path=parsed.path.strip("/"); path=path[2:] if path.startswith("s/") else path; return f"@{path}" if path and not path.startswith(("+","joinchat/")) else value
    raw=value.strip(); raw=raw[2:] if raw.startswith("s/") else raw
    if raw.startswith("@") or raw.startswith(("+","-")):return raw
    return f"@{raw}" if raw and not raw.isdigit() else raw
def _message_url(entity:Any,message:Any)->str|None:
    username=getattr(entity,"username",None); message_id=getattr(message,"id",None); return f"https://t.me/{username}/{message_id}" if username and message_id is not None else None
def _message_datetime(value:Any)->datetime|None:
    if not isinstance(value,datetime):return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
class TelegramClientCollector:
    def __init__(self,listing_urls:list[str],*,include_patterns:list[str]|None=None,exclude_patterns:list[str]|None=None,history_limit:int=200,max_details:int=50,api_id_env:str="TELEGRAM_API_ID",api_hash_env:str="TELEGRAM_API_HASH",session_env:str="TELEGRAM_SESSION",client_factory:Any|None=None,source_id:str="telegram-client",source_name:str|None=None)->None:
        self.entity_refs=[_normalize_entity_ref(x) for x in listing_urls]; self.include_patterns=[_normalized(x) for x in (include_patterns or []) if str(x).strip()]; self.exclude_patterns=[_normalized(x) for x in (exclude_patterns or []) if str(x).strip()]; self.history_limit=max(1,history_limit); self.max_details=max(1,max_details); self.api_id_env=api_id_env; self.api_hash_env=api_hash_env; self.session_env=session_env; self.client_factory=client_factory; self.source_id=source_id; self.configured_source_name=source_name; self.warnings=[]
    def _build_client(self)->Any:
        if self.client_factory:return self.client_factory(api_id_env=self.api_id_env,api_hash_env=self.api_hash_env,session_env=self.session_env)
        return create_telegram_client(api_id_env=self.api_id_env,api_hash_env=self.api_hash_env,session_env=self.session_env,require_session=True)
    def _message_allowed(self,title:str,description:str,source_name:str,url:str|None)->bool:
        haystack=_normalized("\n".join([title,description,source_name,url or ""])); return not(self.exclude_patterns and any(p in haystack for p in self.exclude_patterns))
    async def _collect_async(self,*,max_results:int|None=None)->list[Lead]:
        limit=min(self.max_details,max_results or self.max_details); client=self._build_client(); leads=[]; seen=set()
        try:
            async with client:
                for entity_ref in self.entity_refs:
                    if len(leads)>=limit:break
                    try:entity=await client.get_entity(entity_ref)
                    except Exception as exc:self.warnings.append(f"{entity_ref}: {exc}"); continue
                    source_name=self.configured_source_name or str(getattr(entity,"title",None) or getattr(entity,"username",None) or entity_ref)
                    async for message in client.iter_messages(entity,limit=self.history_limit):
                        text=str(getattr(message,"message",None) or getattr(message,"text",None) or "").strip()
                        if not text:continue
                        title=_title_from_text(text); url=_message_url(entity,message)
                        if not self._message_allowed(title,text,source_name,url):continue
                        message_id=getattr(message,"id",None)
                        if message_id is None:continue
                        external_id=f"{getattr(entity,'id',entity_ref)}:{message_id}"; key=(self.source_id,external_id)
                        if key in seen:continue
                        seen.add(key); leads.append(Lead(source="telegram_client",source_id=self.source_id,source_name=source_name,external_id=external_id,title=title,description=text[:30000],url=url,published_at=_message_datetime(getattr(message,"date",None)),area="Telegram",employment=None,accept_temporary=False,has_direct_contact=bool(CONTACT_RE.search(text)),raw={"entity_ref":entity_ref,"include_hint_match":any(p in _normalized(text) for p in self.include_patterns)}))
                        if len(leads)>=limit:break
        except TelegramClientSetupError as exc:raise TelegramClientCollectorError(str(exc)) from exc
        return leads
    def collect(self,*,max_results:int|None=None)->list[Lead]:return asyncio.run(self._collect_async(max_results=max_results))
