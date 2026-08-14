from __future__ import annotations

import html
import re
import socket
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from ..models import Lead


DEFAULT_USER_AGENT = "SearchOrders/0.2 (+https://imon.agency/)"
TAG_RE = re.compile(r"<[^>]+>")
CHANNEL_TITLE_RE = re.compile(
    r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"'](?P<value>[^\"']+)[\"']",
    re.IGNORECASE,
)
MESSAGE_POST_RE = re.compile(r'data-post="(?P<value>[^"]+)"', re.IGNORECASE)
MESSAGE_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<value>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
MESSAGE_CAPTION_RE = re.compile(
    r'<div class="tgme_widget_message_caption[^"]*"[^>]*>(?P<value>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
DATE_LINK_RE = re.compile(
    r'<a class="tgme_widget_message_date" href="(?P<href>[^"]+)"[^>]*>.*?<time[^>]+datetime="(?P<datetime>[^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
CONTACT_RE = re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)


class TelegramPublicCollectorError(RuntimeError):
    pass


@dataclass(slots=True)
class _ChannelMessage:
    external_id: str
    title: str
    description: str
    url: str | None
    published_at: datetime | None


def _clean_fragment(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def _title_from_text(value: str) -> str:
    condensed = " ".join(value.split())
    if len(condensed) <= 100:
        return condensed or "Telegram message"
    return condensed[:97].rstrip() + "..."


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _channel_name(url: str, page_html: str) -> str:
    title = CHANNEL_TITLE_RE.search(page_html)
    if title:
        return _clean_fragment(title.group("value"))
    path = urlparse(url).path.strip("/").split("/")
    if path and path[0] == "s" and len(path) > 1:
        return path[1]
    return path[-1] if path else "telegram"


def _normalize_listing_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.strip("/")
    else:
        path = value.strip().strip("/")
    if not path:
        raise TelegramPublicCollectorError("Telegram listing URL is empty")
    if path.startswith("s/"):
        return f"https://t.me/{path}"
    if path.startswith("@"):
        path = path[1:]
    if "/" not in path:
        return f"https://t.me/s/{path}"
    if path.startswith("joinchat/") or path.startswith("+"):
        raise TelegramPublicCollectorError("Private Telegram invite links are not supported")
    return f"https://t.me/{path}"


@contextmanager
def _prefer_ipv4() -> Any:
    original_getaddrinfo = socket.getaddrinfo

    def _ipv4_first(
        host: str,
        port: int,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        results = original_getaddrinfo(host, port, family, type, proto, flags)
        ipv4_results = [item for item in results if item[0] == socket.AF_INET]
        return ipv4_results or results

    socket.getaddrinfo = _ipv4_first
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _is_network_unreachable(exc: URLError) -> bool:
    reason = exc.reason
    if isinstance(reason, OSError):
        return reason.errno == 101
    return "network is unreachable" in str(reason).casefold()


class TelegramPublicCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        max_details: int = 30,
        request_delay_seconds: float = 0.5,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        fetcher: Any | None = None,
    ) -> None:
        self.listing_urls = [_normalize_listing_url(url) for url in listing_urls]
        self.include_patterns = [_normalized(item) for item in (include_patterns or []) if str(item).strip()]
        self.exclude_patterns = [_normalized(item) for item in (exclude_patterns or []) if str(item).strip()]
        self.max_details = max(1, max_details)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.timeout = timeout
        self.user_agent = user_agent
        self.fetcher = fetcher
        self.warnings: list[str] = []
        self._robots: dict[str, RobotFileParser] = {}

    def _get(self, url: str) -> str:
        if self.fetcher:
            return self.fetcher(url)
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        try:
            return self._read_response(request)
        except HTTPError as exc:
            raise TelegramPublicCollectorError(f"Telegram returned HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            if _is_network_unreachable(exc):
                try:
                    return self._read_response(request, force_ipv4=True)
                except HTTPError as retry_exc:
                    raise TelegramPublicCollectorError(
                        f"Telegram returned HTTP {retry_exc.code}: {url}"
                    ) from retry_exc
                except URLError as retry_exc:
                    raise TelegramPublicCollectorError(
                        f"Could not reach Telegram: {retry_exc.reason}"
                    ) from retry_exc
            raise TelegramPublicCollectorError(f"Could not reach Telegram: {exc.reason}") from exc

    def _read_response(self, request: Request, *, force_ipv4: bool = False) -> str:
        manager = _prefer_ipv4() if force_ipv4 else nullcontext()
        with manager:
            with urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")

    def _allowed(self, url: str) -> bool:
        if self.fetcher:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        robot = self._robots.get(origin)
        if robot is None:
            robot = RobotFileParser()
            robot.set_url(f"{origin}/robots.txt")
            try:
                contents = self._get(f"{origin}/robots.txt")
                robot.parse(contents.splitlines())
            except TelegramPublicCollectorError as exc:
                self.warnings.append(f"robots.txt unavailable: {exc}")
                robot.parse([])
            self._robots[origin] = robot
        return robot.can_fetch(self.user_agent, url)

    def _message_allowed(self, message: _ChannelMessage) -> bool:
        haystack = _normalized("\n".join([message.title, message.description, message.url or ""]))
        if self.exclude_patterns and any(pattern in haystack for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(pattern in haystack for pattern in self.include_patterns)

    @staticmethod
    def parse_listing(html_text: str) -> list[_ChannelMessage]:
        fragments = re.split(r'(?=<div class="tgme_widget_message\b)', html_text, flags=re.IGNORECASE)
        messages: list[_ChannelMessage] = []
        for fragment in fragments:
            post = MESSAGE_POST_RE.search(fragment)
            if not post:
                continue
            raw_text = MESSAGE_TEXT_RE.search(fragment) or MESSAGE_CAPTION_RE.search(fragment)
            date_link = DATE_LINK_RE.search(fragment)
            if not raw_text and not date_link:
                continue
            description = _clean_fragment(raw_text.group("value")) if raw_text else ""
            url = html.unescape(date_link.group("href")) if date_link else None
            published = _parse_datetime(date_link.group("datetime") if date_link else None)
            messages.append(
                _ChannelMessage(
                    external_id=post.group("value"),
                    title=_title_from_text(description),
                    description=description[:30000],
                    url=url,
                    published_at=published,
                )
            )
        return messages

    def collect(self, *, max_results: int | None = None) -> list[Lead]:
        limit = min(self.max_details, max_results or self.max_details)
        leads: list[Lead] = []
        seen: set[tuple[str, str]] = set()
        for listing_url in self.listing_urls:
            if len(leads) >= limit:
                break
            if not self._allowed(listing_url):
                self.warnings.append(f"Blocked by robots.txt: {listing_url}")
                continue
            page_html = self._get(listing_url)
            channel_name = _channel_name(listing_url, page_html)
            for message in self.parse_listing(page_html):
                if not self._message_allowed(message):
                    continue
                key = ("telegram_public", message.external_id)
                if key in seen:
                    continue
                seen.add(key)
                leads.append(
                    Lead(
                        source="telegram_public",
                        external_id=message.external_id,
                        title=message.title,
                        description=message.description,
                        url=message.url,
                        company_name=channel_name,
                        published_at=message.published_at,
                        area="Telegram",
                        employment="Публичный канал",
                        accept_temporary=True,
                        has_direct_contact=bool(CONTACT_RE.search(message.description)),
                        raw={"channel_url": listing_url},
                    )
                )
                if len(leads) >= limit:
                    break
            if self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)
        return leads
