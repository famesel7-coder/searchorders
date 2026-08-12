from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from ..models import Lead


DEFAULT_USER_AGENT = "SearchOrders/0.2 (+https://imon.agency/)"
DETAIL_LINK_RE = re.compile(
    r"href\s*=\s*['\"](?P<href>(?:https://workspace\.ru)?/tenders/[^'\"?#]+-\d+/?)",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
H1_RE = re.compile(r"<h1\b[^>]*>(?P<value>.*?)</h1>", re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title\b[^>]*>(?P<value>.*?)</title>", re.IGNORECASE | re.DOTALL)
MAIN_RE = re.compile(r"<main\b[^>]*>(?P<value>.*?)</main>", re.IGNORECASE | re.DOTALL)
JSON_LD_RE = re.compile(
    r"<script\b[^>]*type=['\"]application/ld\+json['\"][^>]*>(?P<value>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
EXTERNAL_ID_RE = re.compile(r"-(?P<id>\d+)/?(?:\?.*)?$")
BUDGET_RANGE_RE = re.compile(
    r"бюджет\s*:?[\s\u00a0]*(?:от\s+)?(?P<low>\d[\d\s\u00a0]*)"
    r"\s*(?:[-–—]|до)\s*(?P<high>\d[\d\s\u00a0]*)\s*(?:₽|руб)",
    re.IGNORECASE,
)
BUDGET_FROM_RE = re.compile(
    r"бюджет\s*:?[\s\u00a0]*от\s+(?P<value>\d[\d\s\u00a0]*)\s*(?:₽|руб)",
    re.IGNORECASE,
)
BUDGET_TO_RE = re.compile(
    r"бюджет\s*:?[\s\u00a0]*до\s+(?P<value>\d[\d\s\u00a0]*)\s*(?:₽|руб)",
    re.IGNORECASE,
)
PUBLISHED_RE = re.compile(
    r"опубликован(?:о)?\s*:?[\s\u00a0]*(?P<day>\d{1,2})\s+"
    r"(?P<month>[а-яё]+)\s+(?P<year>20\d{2})",
    re.IGNORECASE,
)
RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


class WorkspaceCollectorError(RuntimeError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def _clean_fragment(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    return parser.text()


def _number(value: str) -> int:
    return int(re.sub(r"\D", "", value))


def _first_json_ld(html_text: str) -> dict[str, Any]:
    fallback: dict[str, Any] = {}
    for match in JSON_LD_RE.finditer(html_text):
        try:
            payload = json.loads(html.unescape(match.group("value")).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict):
                fallback = fallback or candidate
                if any(candidate.get(key) for key in ("headline", "description", "datePublished")):
                    return candidate
    return fallback


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def _published_from_text(text: str) -> datetime | None:
    match = PUBLISHED_RE.search(text)
    if not match:
        return None
    month = RU_MONTHS.get(match.group("month").casefold().replace("ё", "е"))
    if month is None:
        return None
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        tzinfo=timezone.utc,
    )


def _budget(text: str) -> tuple[int | None, int | None]:
    match = BUDGET_RANGE_RE.search(text)
    if match:
        return _number(match.group("low")), _number(match.group("high"))
    lower = BUDGET_FROM_RE.search(text)
    upper = BUDGET_TO_RE.search(text)
    return (
        _number(lower.group("value")) if lower else None,
        _number(upper.group("value")) if upper else None,
    )


class WorkspaceCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        max_details: int = 30,
        request_delay_seconds: float = 0.5,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.listing_urls = listing_urls
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
            with urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise WorkspaceCollectorError(f"Workspace returned HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise WorkspaceCollectorError(f"Could not reach Workspace: {exc.reason}") from exc

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
            except WorkspaceCollectorError as exc:
                self.warnings.append(f"robots.txt unavailable: {exc}")
                robot.parse([])
            self._robots[origin] = robot
        return robot.can_fetch(self.user_agent, url)

    @staticmethod
    def listing_links(html_text: str, base_url: str) -> list[str]:
        unique: dict[str, None] = {}
        for match in DETAIL_LINK_RE.finditer(html_text):
            unique.setdefault(urljoin(base_url, match.group("href")), None)
        return list(unique)

    @staticmethod
    def parse_detail(html_text: str, url: str) -> Lead:
        json_ld = _first_json_ld(html_text)
        heading = H1_RE.search(html_text)
        page_title = TITLE_RE.search(html_text)
        title = str(json_ld.get("headline") or json_ld.get("name") or "").strip()
        if not title and heading:
            title = _clean_fragment(heading.group("value"))
        if not title and page_title:
            title = _clean_fragment(page_title.group("value")).split(" - ")[0].strip()

        main = MAIN_RE.search(html_text)
        text = _visible_text(main.group("value") if main else html_text)
        description = str(json_ld.get("description") or "").strip()
        if description:
            description = f"{description}\n{text}"
        else:
            description = text
        description = description[:30000]

        identifier = EXTERNAL_ID_RE.search(url)
        external_id = identifier.group("id") if identifier else url.rstrip("/").rsplit("/", 1)[-1]
        salary_from, salary_to = _budget(text)
        published_at = _parse_datetime(json_ld.get("datePublished")) or _published_from_text(text)

        return Lead(
            source="workspace",
            external_id=external_id,
            title=title or f"Workspace tender {external_id}",
            description=description,
            url=url,
            published_at=published_at,
            area="Россия",
            employment="Проектный тендер",
            accept_temporary=True,
            salary_from=salary_from,
            salary_to=salary_to,
            currency="RUR" if salary_from or salary_to else None,
            has_direct_contact=True,
            raw={"json_ld": json_ld},
        )

    def collect(self, *, max_results: int | None = None) -> list[Lead]:
        limit = min(self.max_details, max_results or self.max_details)
        links: dict[str, None] = {}
        for listing_url in self.listing_urls:
            if not self._allowed(listing_url):
                self.warnings.append(f"Blocked by robots.txt: {listing_url}")
                continue
            listing = self._get(listing_url)
            for link in self.listing_links(listing, listing_url):
                links.setdefault(link, None)
                if len(links) >= limit:
                    break
            if len(links) >= limit:
                break

        leads: list[Lead] = []
        for link in list(links)[:limit]:
            if not self._allowed(link):
                self.warnings.append(f"Blocked by robots.txt: {link}")
                continue
            try:
                details = self._get(link)
                leads.append(self.parse_detail(details, link))
            except WorkspaceCollectorError as exc:
                self.warnings.append(str(exc))
            if self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)
        return leads
