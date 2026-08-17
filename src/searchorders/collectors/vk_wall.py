from __future__ import annotations
import json,os,re
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Any
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from ..models import Lead
DEFAULT_USER_AGENT="SearchOrders/0.3 (+https://imon.agency/)"; CONTACT_RE=re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)",re.IGNORECASE)
class VkWallCollectorError(RuntimeError):pass
@dataclass(slots=True)
class _VkPost:external_id:str; title:str; description:str; url:str; published_at:datetime|None; domain:str
def _normalized(value:str)->str:return value.casefold().replace("ё","е").strip()
def _domain_from_listing_url(value:str)->str:
    parsed=urlparse(value); path=parsed.path.strip("/") if parsed.scheme and parsed.netloc else value.strip().strip("/")
    if not path:raise VkWallCollectorError("VK listing URL is empty")
    return path.split("/",1)[0]
def _title_from_text(value:str,fallback:str)->str:
    condensed=" ".join(value.split()); return fallback if not condensed else condensed if len(condensed)<=100 else condensed[:97].rstrip()+"..."
def _parse_datetime(value:Any)->datetime|None:return datetime.fromtimestamp(value,tz=timezone.utc) if isinstance(value,int) else None
class VkWallCollector:
    def __init__(self,listing_urls:list[str],*,include_patterns:list[str]|None=None,exclude_patterns:list[str]|None=None,access_token_env:str="VK_ACCESS_TOKEN",api_version:str="5.199",max_details:int=50,timeout:float=20.0,user_agent:str=DEFAULT_USER_AGENT,fetcher:Any|None=None,source_id:str="vk-wall",source_name:str|None=None)->None:
        self.domains=[_domain_from_listing_url(x) for x in listing_urls]; self.include_patterns=[_normalized(x) for x in (include_patterns or []) if str(x).strip()]; self.exclude_patterns=[_normalized(x) for x in (exclude_patterns or []) if str(x).strip()]; self.access_token_env=access_token_env; self.api_version=api_version; self.max_details=max(1,max_details); self.timeout=timeout; self.user_agent=user_agent; self.fetcher=fetcher; self.source_id=source_id; self.configured_source_name=source_name; self.warnings=[]
    def _access_token(self)->str:
        token=os.getenv(self.access_token_env,"").strip()
        if not token:raise VkWallCollectorError(f"VK access token is not configured in env var {self.access_token_env}")
        return token
    def _get_json(self,domain:str,count:int)->dict[str,Any]:
        if self.fetcher:return self.fetcher(domain,count)
        params=urlencode({"domain":domain,"count":count,"filter":"owner","access_token":self._access_token(),"v":self.api_version}); request=Request(f"https://api.vk.com/method/wall.get?{params}",headers={"User-Agent":self.user_agent,"Accept":"application/json","Accept-Language":"ru,en;q=0.8"})
        try:
            with urlopen(request,timeout=self.timeout) as response:payload=json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace"))
        except HTTPError as exc:raise VkWallCollectorError(f"VK returned HTTP {exc.code} for {domain}") from exc
        except URLError as exc:raise VkWallCollectorError(f"Could not reach VK: {exc.reason}") from exc
        except json.JSONDecodeError as exc:raise VkWallCollectorError("VK returned invalid JSON") from exc
        if not isinstance(payload,dict):raise VkWallCollectorError("VK returned invalid payload")
        return payload
    def _post_allowed(self,post:_VkPost)->bool:
        haystack=_normalized(f"{post.title}\n{post.description}\n{post.domain}\n{post.url}"); return not(self.exclude_patterns and any(p in haystack for p in self.exclude_patterns))
    @staticmethod
    def parse_posts(payload:dict[str,Any],*,domain:str)->list[_VkPost]:
        error=payload.get("error")
        if isinstance(error,dict):raise VkWallCollectorError(f"VK API error for {domain}: {error.get('error_msg') or 'unknown VK API error'}")
        response=payload.get("response")
        if not isinstance(response,dict):raise VkWallCollectorError(f"VK payload for {domain} has no response object")
        items=response.get("items")
        if not isinstance(items,list):return []
        posts=[]
        for item in items:
            if not isinstance(item,dict):continue
            post_id=item.get("id"); owner_id=item.get("owner_id")
            if not isinstance(post_id,int) or not isinstance(owner_id,int):continue
            text=str(item.get("text") or "").strip(); url=f"https://vk.com/wall{owner_id}_{post_id}"; posts.append(_VkPost(f"{owner_id}_{post_id}",_title_from_text(text,f"VK post {domain}/{post_id}"),text[:30000],url,_parse_datetime(item.get("date")),domain))
        return posts
    def collect(self,*,max_results:int|None=None)->list[Lead]:
        limit=min(self.max_details,max_results or self.max_details); leads=[]; seen=set()
        for domain in self.domains:
            if len(leads)>=limit:break
            source_name=self.configured_source_name or domain
            for post in self.parse_posts(self._get_json(domain,max(1,limit)),domain=domain):
                if not self._post_allowed(post):continue
                key=(self.source_id,post.external_id)
                if key in seen:continue
                seen.add(key); leads.append(Lead(source="vk_wall",source_id=self.source_id,source_name=source_name,external_id=post.external_id,title=post.title,description=post.description,url=post.url,published_at=post.published_at,area="VK",employment=None,accept_temporary=False,has_direct_contact=bool(CONTACT_RE.search(post.description)),raw={"domain":post.domain,"include_hint_match":any(p in _normalized(post.description) for p in self.include_patterns)}))
                if len(leads)>=limit:break
        return leads
