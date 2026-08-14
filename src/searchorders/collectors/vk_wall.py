from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from ..models import Lead


DEFAULT_USER_AGENT = "SearchOrders/0.2 (+https://imon.agency/)"
CONTACT_RE = re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)


class VkWallCollectorError(RuntimeError):
    pass


@dataclass(slots=True)
class _VkPost:
    external_id: str
    title: str
    description: str
    url: str
    published_at: datetime | None
    domain: str


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def _domain_from_listing_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.strip("/")
    else:
        path = value.strip().strip("/")
    if not path:
        raise VkWallCollectorError("VK listing URL is empty")
    return path.split("/", 1)[0]


def _title_from_text(value: str, fallback: str) -> str:
    condensed = " ".join(value.split())
    if not condensed:
        return fallback
    if len(condensed) <= 100:
        return condensed
    return condensed[:97].rstrip() + "..."


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


class VkWallCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        access_token_env: str = "VK_ACCESS_TOKEN",
        api_version: str = "5.199",
        max_details: int = 30,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        fetcher: Any | None = None,
    ) -> None:
        self.domains = [_domain_from_listing_url(url) for url in listing_urls]
        self.include_patterns = [_normalized(item) for item in (include_patterns or []) if str(item).strip()]
        self.exclude_patterns = [_normalized(item) for item in (exclude_patterns or []) if str(item).strip()]
        self.access_token_env = access_token_env
        self.api_version = api_version
        self.max_details = max(1, max_details)
        self.timeout = timeout
        self.user_agent = user_agent
        self.fetcher = fetcher
        self.warnings: list[str] = []

    def _access_token(self) -> str:
        token = os.getenv(self.access_token_env, "").strip()
        if not token:
            raise VkWallCollectorError(
                f"VK access token is not configured in env var {self.access_token_env}"
            )
        return token

    def _get_json(self, domain: str, count: int) -> dict[str, Any]:
        if self.fetcher:
            return self.fetcher(domain, count)
        params = urlencode(
            {
                "domain": domain,
                "count": count,
                "filter": "owner",
                "access_token": self._access_token(),
                "v": self.api_version,
            }
        )
        request = Request(
            f"https://api.vk.com/method/wall.get?{params}",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                payload = json.loads(response.read().decode(charset, errors="replace"))
        except HTTPError as exc:
            raise VkWallCollectorError(f"VK returned HTTP {exc.code} for {domain}") from exc
        except URLError as exc:
            raise VkWallCollectorError(f"Could not reach VK: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise VkWallCollectorError("VK returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise VkWallCollectorError("VK returned invalid payload")
        return payload

    def _post_allowed(self, post: _VkPost) -> bool:
        haystack = _normalized("\n".join([post.title, post.description, post.domain, post.url]))
        if self.exclude_patterns and any(pattern in haystack for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(pattern in haystack for pattern in self.include_patterns)

    @staticmethod
    def parse_posts(payload: dict[str, Any], *, domain: str) -> list[_VkPost]:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("error_msg") or "unknown VK API error")
            raise VkWallCollectorError(f"VK API error for {domain}: {message}")
        response = payload.get("response")
        if not isinstance(response, dict):
            raise VkWallCollectorError(f"VK payload for {domain} has no response object")
        items = response.get("items")
        if not isinstance(items, list):
            return []
        posts: list[_VkPost] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            post_id = item.get("id")
            owner_id = item.get("owner_id")
            if not isinstance(post_id, int) or not isinstance(owner_id, int):
                continue
            text = str(item.get("text") or "").strip()
            title = _title_from_text(text, f"VK post {domain}/{post_id}")
            url = f"https://vk.com/wall{owner_id}_{post_id}"
            posts.append(
                _VkPost(
                    external_id=f"{owner_id}_{post_id}",
                    title=title,
                    description=text[:30000],
                    url=url,
                    published_at=_parse_datetime(item.get("date")),
                    domain=domain,
                )
            )
        return posts

    def collect(self, *, max_results: int | None = None) -> list[Lead]:
        limit = min(self.max_details, max_results or self.max_details)
        leads: list[Lead] = []
        seen: set[tuple[str, str]] = set()
        per_domain = max(1, limit)
        for domain in self.domains:
            if len(leads) >= limit:
                break
            payload = self._get_json(domain, per_domain)
            for post in self.parse_posts(payload, domain=domain):
                if not self._post_allowed(post):
                    continue
                key = ("vk_wall", post.external_id)
                if key in seen:
                    continue
                seen.add(key)
                leads.append(
                    Lead(
                        source="vk_wall",
                        external_id=post.external_id,
                        title=post.title,
                        description=post.description,
                        url=post.url,
                        company_name=post.domain,
                        published_at=post.published_at,
                        area="VK",
                        employment="Публичная стена",
                        accept_temporary=True,
                        has_direct_contact=bool(CONTACT_RE.search(post.description)),
                        raw={"domain": post.domain},
                    )
                )
                if len(leads) >= limit:
                    break
        return leads
