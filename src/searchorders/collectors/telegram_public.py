from __future__ import annotations
import html,re,socket,time
from contextlib import contextmanager,nullcontext
from dataclasses import dataclass
from datetime import datetime,timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from urllib.robotparser import RobotFileParser
from ..models import Lead
DEFAULT_USER_AGENT="SearchOrders/0.3 (+https://imon.agency/)"; CONTACT_RE=re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)",re.IGNORECASE); CHANNEL_TITLE_RE=re.compile(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"'](?P<value>[^\"']+)[\"']",re.IGNORECASE); MESSAGE_POST_RE=re.compile(r'data-post="(?P<value>[^"]+)"',re.IGNORECASE); DATE_LINK_RE=re.compile(r'<a class="tgme_widget_message_date" href="(?P<href>[^"]+)"[^>]*>.*?<time[^>]+datetime="(?P<datetime>[^"]+)"',re.IGNORECASE|re.DOTALL); TEXT_CONTAINER_RE=re.compile(r'<div class="tgme_widget_message_(?:text|caption)[^"]*"[^>]*>(?P<value>.*?)</div>',re.IGNORECASE|re.DOTALL)
class TelegramPublicCollectorError(RuntimeError):pass
class _TextExtractor(HTMLParser):
    def __init__(self)->None:super().__init__(); self.parts=[]
    def handle_data(self,data:str)->None:
        if data.strip():self.parts.append(data)
    def text(self)->str:return " ".join(" ".join(self.parts).split())
@dataclass(slots=True)
class _ChannelMessage:external_id:str; title:str; description:str; url:str|None; published_at:datetime|None
def _clean_fragment(value:str)->str:p=_TextExtractor(); p.feed(html.unescape(value)); return p.text()
def _normalized(value:str)->str:return value.casefold().replace("ё","е").strip()
def _title_from_text(value:str)->str:
    condensed=" ".join(value.split()); return condensed if len(condensed)<=100 else condensed[:97].rstrip()+"..." if condensed else "Telegram message"
def _parse_datetime(value:str|None)->datetime|None:
    if not value:return None
    try:p=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:return None
    return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
def _channel_name(url:str,page_html:str)->str:
    title=CHANNEL_TITLE_RE.search(page_html)
    if title:return html.unescape(title.group("value")).strip()
    path=urlparse(url).path.strip("/").split("/"); return path[1] if path and path[0]=="s" and len(path)>1 else path[-1] if path else "telegram"
def _normalize_listing_url(value:str)->str:
    parsed=urlparse(value); path=parsed.path.strip("/") if parsed.scheme and parsed.netloc else value.strip().strip("/")
    if not path:raise TelegramPublicCollectorError("Telegram listing URL is empty")
    if path.startswith("s/"):return f"https://t.me/{path}"
    if path.startswith("@"):path=path[1:]
    if "/" not in path:return f"https://t.me/s/{path}"
    if path.startswith("joinchat/") or path.startswith("+"):raise TelegramPublicCollectorError("Private Telegram invite links are not supported")
    return f"https://t.me/{path}"
@contextmanager
def _prefer_ipv4()->Any:
    original=socket.getaddrinfo
    def ipv4_first(host:str,port:int,family:int=0,type:int=0,proto:int=0,flags:int=0)->Any:
        results=original(host,port,family,type,proto,flags); v4=[x for x in results if x[0]==socket.AF_INET]; return v4 or results
    socket.getaddrinfo=ipv4_first
    try:yield
    finally:socket.getaddrinfo=original
def _is_network_unreachable(exc:URLError)->bool:return(isinstance(exc.reason,OSError) and exc.reason.errno==101) or "network is unreachable" in str(exc.reason).casefold()
class TelegramPublicCollector:
    def __init__(self,listing_urls:list[str],*,include_patterns:list[str]|None=None,exclude_patterns:list[str]|None=None,max_details:int=50,request_delay_seconds:float=.3,timeout:float=20.0,user_agent:str=DEFAULT_USER_AGENT,fetcher:Any|None=None,source_id:str="telegram-public",source_name:str|None=None)->None:
        self.listing_urls=[_normalize_listing_url(x) for x in listing_urls]; self.include_patterns=[_normalized(x) for x in(include_patterns or[]) if str(x).strip()]; self.exclude_patterns=[_normalized(x) for x in(exclude_patterns or[]) if str(x).strip()]; self.max_details=max(1,max_details); self.request_delay_seconds=max(0.0,request_delay_seconds); self.timeout=timeout; self.user_agent=user_agent; self.fetcher=fetcher; self.source_id=source_id; self.configured_source_name=source_name; self.warnings=[]; self._robots={}
    def _read_response(self,request:Request,*,force_ipv4:bool=False)->str:
        manager=_prefer_ipv4() if force_ipv4 else nullcontext()
        with manager:
            with urlopen(request,timeout=self.timeout) as response:return response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace")
    def _get(self,url:str)->str:
        if self.fetcher:return self.fetcher(url)
        request=Request(url,headers={"User-Agent":self.user_agent,"Accept":"text/html,application/xhtml+xml","Accept-Language":"ru,en;q=0.8"})
        try:return self._read_response(request)
        except HTTPError as exc:raise TelegramPublicCollectorError(f"Telegram returned HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            if _is_network_unreachable(exc):
                try:return self._read_response(request,force_ipv4=True)
                except(HTTPError,URLError) as retry:raise TelegramPublicCollectorError(f"Could not reach Telegram: {getattr(retry,'reason',retry)}") from retry
            raise TelegramPublicCollectorError(f"Could not reach Telegram: {exc.reason}") from exc
    def _allowed(self,url:str)->bool:
        if self.fetcher:return True
        parsed=urlparse(url); origin=f"{parsed.scheme}://{parsed.netloc}"; robot=self._robots.get(origin)
        if robot is None:
            robot=RobotFileParser(); robot.set_url(f"{origin}/robots.txt")
            try:robot.parse(self._get(f"{origin}/robots.txt").splitlines())
            except TelegramPublicCollectorError as exc:self.warnings.append(f"robots.txt unavailable: {exc}"); robot.parse([])
            self._robots[origin]=robot
        return robot.can_fetch(self.user_agent,url)
    def _message_allowed(self,message:_ChannelMessage)->bool:
        haystack=_normalized(f"{message.title}\n{message.description}\n{message.url or ''}"); return not(self.exclude_patterns and any(p in haystack for p in self.exclude_patterns))
    @staticmethod
    def parse_listing(html_text:str)->list[_ChannelMessage]:
        messages=[]
        for fragment in re.split(r'(?=<div class="tgme_widget_message\b)',html_text,flags=re.IGNORECASE):
            post=MESSAGE_POST_RE.search(fragment)
            if not post:continue
            text=TEXT_CONTAINER_RE.search(fragment); date=DATE_LINK_RE.search(fragment)
            if not text and not date:continue
            desc=_clean_fragment(text.group("value")) if text else ""; url=html.unescape(date.group("href")) if date else None; published=_parse_datetime(date.group("datetime") if date else None); messages.append(_ChannelMessage(post.group("value"),_title_from_text(desc),desc[:30000],url,published))
        return messages
    def collect(self,*,max_results:int|None=None)->list[Lead]:
        limit=min(self.max_details,max_results or self.max_details); leads=[]; seen=set()
        for listing_url in self.listing_urls:
            if len(leads)>=limit:break
            if not self._allowed(listing_url):self.warnings.append(f"Blocked by robots.txt: {listing_url}"); continue
            page=self._get(listing_url); channel=self.configured_source_name or _channel_name(listing_url,page)
            for message in self.parse_listing(page):
                if not self._message_allowed(message):continue
                key=(self.source_id,message.external_id)
                if key in seen:continue
                seen.add(key); leads.append(Lead(source="telegram_public",source_id=self.source_id,source_name=channel,external_id=message.external_id,title=message.title,description=message.description,url=message.url,published_at=message.published_at,area="Telegram",employment=None,accept_temporary=False,has_direct_contact=bool(CONTACT_RE.search(message.description)),raw={"channel_url":listing_url,"include_hint_match":any(p in _normalized(message.description) for p in self.include_patterns)}))
                if len(leads)>=limit:break
            if self.request_delay_seconds:time.sleep(self.request_delay_seconds)
        return leads
