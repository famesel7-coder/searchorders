from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

from ..models import Lead


DEFAULT_USER_AGENT = "SearchOrders/0.2 (+https://imon.agency/)"
TAG_RE = re.compile(r"<[^>]+>")
CONTACT_RE = re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)


class RSSFeedCollectorError(RuntimeError):
    pass


@dataclass(slots=True)
class _FeedEntry:
    external_id: str
    title: str
    description: str
    url: str | None
    published_at: datetime | None


def _clean_fragment(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _tag_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _child_text(node: ET.Element, *names: str) -> str:
    expected = {_normalized(name) for name in names}
    for child in list(node):
        if _normalized(_tag_name(child.tag)) not in expected:
            continue
        text = "".join(child.itertext()).strip()
        if text:
            return _clean_fragment(text)
    return ""


def _atom_link(node: ET.Element) -> str | None:
    for child in list(node):
        if _normalized(_tag_name(child.tag)) != "link":
            continue
        rel = str(child.attrib.get("rel", "alternate")).strip().casefold()
        href = str(child.attrib.get("href", "")).strip()
        if rel in {"", "alternate"} and href:
            return href
    return None


class RSSFeedCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        area: str | None = None,
        employment: str | None = None,
        max_details: int = 30,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        fetcher: Any | None = None,
    ) -> None:
        self.listing_urls = listing_urls
        self.include_patterns = [_normalized(item) for item in (include_patterns or []) if str(item).strip()]
        self.exclude_patterns = [_normalized(item) for item in (exclude_patterns or []) if str(item).strip()]
        self.area = area or "Internet"
        self.employment = employment or "Публичная лента"
        self.max_details = max(1, max_details)
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
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RSSFeedCollectorError(f"Feed returned HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RSSFeedCollectorError(f"Could not reach feed: {exc.reason}") from exc

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
            except RSSFeedCollectorError as exc:
                self.warnings.append(f"robots.txt unavailable: {exc}")
                robot.parse([])
            self._robots[origin] = robot
        return robot.can_fetch(self.user_agent, url)

    def _entry_allowed(self, entry: _FeedEntry) -> bool:
        haystack = _normalized("\n".join([entry.title, entry.description, entry.url or ""]))
        if self.exclude_patterns and any(pattern in haystack for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(pattern in haystack for pattern in self.include_patterns)

    @staticmethod
    def parse_feed(xml_text: str) -> list[_FeedEntry]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise RSSFeedCollectorError(f"Feed XML is invalid: {exc}") from exc

        tag = _normalized(_tag_name(root.tag))
        entries: list[_FeedEntry] = []
        if tag == "rss":
            channel = next((child for child in list(root) if _normalized(_tag_name(child.tag)) == "channel"), None)
            if channel is None:
                return []
            for item in list(channel):
                if _normalized(_tag_name(item.tag)) != "item":
                    continue
                title = _child_text(item, "title")
                description = _child_text(item, "description", "encoded", "content")
                url = _child_text(item, "link") or None
                guid = _child_text(item, "guid")
                published = _parse_datetime(_child_text(item, "pubDate", "date", "updated"))
                external_id = guid or url or title
                if not external_id:
                    continue
                entries.append(
                    _FeedEntry(
                        external_id=_sha1(external_id),
                        title=title or "RSS item",
                        description=description,
                        url=url,
                        published_at=published,
                    )
                )
            return entries

        if tag == "feed":
            for entry in list(root):
                if _normalized(_tag_name(entry.tag)) != "entry":
                    continue
                title = _child_text(entry, "title")
                description = _child_text(entry, "summary", "content", "subtitle")
                url = _atom_link(entry)
                entry_id = _child_text(entry, "id") or url or title
                published = _parse_datetime(
                    _child_text(entry, "published", "updated")
                )
                if not entry_id:
                    continue
                entries.append(
                    _FeedEntry(
                        external_id=_sha1(entry_id),
                        title=title or "Atom entry",
                        description=description,
                        url=url,
                        published_at=published,
                    )
                )
            return entries

        raise RSSFeedCollectorError(f"Unsupported feed format: {root.tag}")

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
            xml_text = self._get(listing_url)
            for entry in self.parse_feed(xml_text):
                if not self._entry_allowed(entry):
                    continue
                key = ("rss_feed", entry.external_id)
                if key in seen:
                    continue
                seen.add(key)
                text = entry.description[:30000]
                leads.append(
                    Lead(
                        source="rss_feed",
                        external_id=entry.external_id,
                        title=entry.title[:300],
                        description=text,
                        url=entry.url,
                        company_name=urlparse(entry.url).netloc if entry.url else None,
                        published_at=entry.published_at,
                        area=self.area,
                        employment=self.employment,
                        accept_temporary=True,
                        has_direct_contact=bool(CONTACT_RE.search(text)),
                        raw={"feed_url": listing_url},
                    )
                )
                if len(leads) >= limit:
                    break
        return leads
