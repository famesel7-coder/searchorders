from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from ..models import Lead


DEFAULT_USER_AGENT = "SearchOrders/0.2 (+https://imon.agency/)"
TASK_CARD_RE = re.compile(r"<article class=\"task-card\">(?P<value>.*?)</article>", re.IGNORECASE | re.DOTALL)
LINK_RE = re.compile(
    r"<a class=\"task-card__title-link\" href=\"(?P<href>/task/view/(?P<id>\d+))\"[^>]*title=\"(?P<title>[^\"]+)\"",
    re.IGNORECASE,
)
DESCRIPTION_RE = re.compile(r"<p class=\"task-card__desc\">(?P<value>.*?)</p>", re.IGNORECASE | re.DOTALL)
CATEGORY_RE = re.compile(
    r"<span class=\"task-chip task-chip--cat\">(?P<value>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
PUBLISHED_RE = re.compile(
    r"<span class=\"task-card__foot-item\" title=\"(?P<value>\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\">",
    re.IGNORECASE,
)
BUDGET_RE = re.compile(
    r"<div class=\"task-card__budget(?:\s+task-card__budget--soft)?\">(?P<value>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
DETAIL_DESCRIPTION_RE = re.compile(r"</h1>\s*(?P<value>.*?)\s*<div class=\"tv-hero__meta\">", re.IGNORECASE | re.DOTALL)
DETAIL_BUDGET_RE = re.compile(
    r"<div class=\"tv-meta-item__lbl\">Гонорар</div>\s*<div class=\"tv-meta-item__val(?:\s+tv-meta-item__val--budget)?\">(?P<value>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
DETAIL_CUSTOMER_RE = re.compile(r"<div class=\"cust__name\">(?P<value>.*?)</div>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
BUDGET_RANGE_RE = re.compile(
    r"(?P<low>\d[\d\s\u00a0]*)\s*(?:[-–—]|до)\s*(?P<high>\d[\d\s\u00a0]*)",
    re.IGNORECASE,
)
BUDGET_SINGLE_RE = re.compile(r"(?P<value>\d[\d\s\u00a0]*)")
MOSCOW_TZ = timezone(timedelta(hours=3))


class FreelanceTaskCollectorError(RuntimeError):
    pass


@dataclass(slots=True)
class _TaskCard:
    url: str
    external_id: str
    title: str
    description: str
    category: str | None
    published_at: datetime | None
    salary_from: int | None
    salary_to: int | None


def _clean_fragment(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def _number(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _budget(value: str) -> tuple[int | None, int | None]:
    cleaned = _clean_fragment(value)
    budget_range = BUDGET_RANGE_RE.search(cleaned)
    if budget_range:
        return _number(budget_range.group("low")), _number(budget_range.group("high"))
    budget_single = BUDGET_SINGLE_RE.search(cleaned)
    amount = _number(budget_single.group("value")) if budget_single else None
    return (amount, None) if amount else (None, None)


def _parse_listing_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y %H:%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=MOSCOW_TZ)


class FreelanceTaskCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        allowed_categories: list[str] | None = None,
        max_details: int = 30,
        request_delay_seconds: float = 0.5,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        fetcher: Any | None = None,
    ) -> None:
        self.listing_urls = listing_urls
        self.allowed_categories = [_normalized(item) for item in (allowed_categories or [])]
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
            raise FreelanceTaskCollectorError(f"Freelance returned HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise FreelanceTaskCollectorError(f"Could not reach Freelance: {exc.reason}") from exc

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
            except FreelanceTaskCollectorError as exc:
                self.warnings.append(f"robots.txt unavailable: {exc}")
                robot.parse([])
            self._robots[origin] = robot
        return robot.can_fetch(self.user_agent, url)

    def _category_allowed(self, category: str | None) -> bool:
        if not self.allowed_categories:
            return True
        if not category:
            return False
        return _normalized(category) in self.allowed_categories

    @staticmethod
    def listing_cards(html_text: str, base_url: str) -> list[_TaskCard]:
        cards: list[_TaskCard] = []
        for match in TASK_CARD_RE.finditer(html_text):
            fragment = match.group("value")
            link = LINK_RE.search(fragment)
            if not link:
                continue
            description = DESCRIPTION_RE.search(fragment)
            category = CATEGORY_RE.search(fragment)
            published = PUBLISHED_RE.search(fragment)
            budget = BUDGET_RE.search(fragment)
            low, high = _budget(budget.group("value")) if budget else (None, None)
            cards.append(
                _TaskCard(
                    url=urljoin(base_url, link.group("href")),
                    external_id=link.group("id"),
                    title=_clean_fragment(link.group("title")),
                    description=_clean_fragment(description.group("value")) if description else "",
                    category=_clean_fragment(category.group("value")) if category else None,
                    published_at=_parse_listing_datetime(published.group("value")) if published else None,
                    salary_from=low,
                    salary_to=high,
                )
            )
        return cards

    @staticmethod
    def parse_detail(html_text: str, seed: _TaskCard) -> Lead:
        description = DETAIL_DESCRIPTION_RE.search(html_text)
        category = CATEGORY_RE.search(html_text)
        budget = DETAIL_BUDGET_RE.search(html_text)
        customer = DETAIL_CUSTOMER_RE.search(html_text)
        low, high = _budget(budget.group("value")) if budget else (seed.salary_from, seed.salary_to)
        description_text = _clean_fragment(description.group("value")) if description else seed.description
        category_text = _clean_fragment(category.group("value")) if category else seed.category
        return Lead(
            source="freelance_task",
            external_id=seed.external_id,
            title=seed.title,
            description=description_text[:30000],
            url=seed.url,
            company_name=_clean_fragment(customer.group("value")) if customer else None,
            published_at=seed.published_at,
            area="Россия",
            employment="Проектный фриланс",
            accept_temporary=True,
            salary_from=low,
            salary_to=high,
            currency="RUR" if low or high else None,
            has_direct_contact=bool(re.search(r"(telegram|whatsapp|t\.me|@[\w_]{4,})", description_text, re.IGNORECASE)),
            raw={"category": category_text or seed.category},
        )

    def collect(self, *, max_results: int | None = None) -> list[Lead]:
        limit = min(self.max_details, max_results or self.max_details)
        cards: dict[str, _TaskCard] = {}
        for listing_url in self.listing_urls:
            if not self._allowed(listing_url):
                self.warnings.append(f"Blocked by robots.txt: {listing_url}")
                continue
            listing = self._get(listing_url)
            for card in self.listing_cards(listing, listing_url):
                if not self._category_allowed(card.category):
                    continue
                cards.setdefault(card.url, card)
                if len(cards) >= limit:
                    break
            if len(cards) >= limit:
                break

        leads: list[Lead] = []
        for card in list(cards.values())[:limit]:
            if not self._allowed(card.url):
                self.warnings.append(f"Blocked by robots.txt: {card.url}")
                continue
            try:
                details = self._get(card.url)
                leads.append(self.parse_detail(details, card))
            except FreelanceTaskCollectorError as exc:
                self.warnings.append(str(exc))
            if self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)
        return leads
