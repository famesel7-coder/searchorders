from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import Lead


HH_API_BASE = "https://api.hh.ru"
DEFAULT_USER_AGENT = "SearchOrders/0.1 (info@imon.agency)"
TAG_RE = re.compile(r"<[^>]+>")


class HHCollectorError(RuntimeError):
    pass


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    without_tags = TAG_RE.sub(" ", value)
    return " ".join(html.unescape(without_tags).split())


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class HHCollector:
    def __init__(self, *, user_agent: str | None = None, timeout: float = 20.0) -> None:
        self.user_agent = user_agent or os.getenv("HH_USER_AGENT", DEFAULT_USER_AGENT)
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params or {}, doseq=True)}" if params else ""
        request = Request(
            f"{HH_API_BASE}{path}{query}",
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise HHCollectorError(f"HH.ru API returned HTTP {exc.code} for {path}") from exc
        except URLError as exc:
            raise HHCollectorError(f"Could not reach HH.ru API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise HHCollectorError("HH.ru API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HHCollectorError("HH.ru API returned an unexpected response")
        return payload

    def search(
        self,
        query: str,
        *,
        date_from: datetime,
        areas: list[str] | None = None,
        per_page: int = 50,
        max_pages: int = 2,
    ) -> list[Lead]:
        leads: list[Lead] = []
        for page in range(max_pages):
            params: dict[str, Any] = {
                "text": query,
                "date_from": date_from.astimezone(timezone.utc).isoformat(),
                "order_by": "publication_time",
                "page": page,
                "per_page": max(1, min(per_page, 100)),
            }
            if areas:
                params["area"] = areas
            payload = self._get("/vacancies", params)
            items = payload.get("items", [])
            if not isinstance(items, list):
                break
            leads.extend(self._lead_from_payload(item) for item in items if isinstance(item, dict))
            pages = int(payload.get("pages", 0) or 0)
            if page + 1 >= pages:
                break
        return leads

    def collect(
        self,
        queries: list[str],
        *,
        hours: int = 72,
        areas: list[str] | None = None,
        max_results: int = 100,
    ) -> list[Lead]:
        date_from = datetime.now(timezone.utc) - timedelta(hours=hours)
        unique: dict[str, Lead] = {}
        per_query = max(10, min(50, max_results))
        for query in queries:
            for lead in self.search(
                query,
                date_from=date_from,
                areas=areas,
                per_page=per_query,
                max_pages=2,
            ):
                unique.setdefault(lead.external_id, lead)
                if len(unique) >= max_results:
                    return list(unique.values())
        return list(unique.values())

    def enrich(self, lead: Lead) -> Lead:
        payload = self._get(f"/vacancies/{lead.external_id}")
        return self._lead_from_payload(payload)

    @staticmethod
    def _lead_from_payload(payload: dict[str, Any]) -> Lead:
        snippet = payload.get("snippet") or {}
        description_parts = [
            _strip_html(payload.get("description")),
            _strip_html(snippet.get("requirement") if isinstance(snippet, dict) else None),
            _strip_html(snippet.get("responsibility") if isinstance(snippet, dict) else None),
        ]
        key_skills = payload.get("key_skills") or []
        if isinstance(key_skills, list):
            description_parts.extend(
                str(item.get("name"))
                for item in key_skills
                if isinstance(item, dict) and item.get("name")
            )

        employer = payload.get("employer") or {}
        salary = payload.get("salary") or {}
        employment = payload.get("employment") or {}
        schedule = payload.get("schedule") or {}
        area = payload.get("area") or {}

        external_id = str(payload.get("id", ""))
        return Lead(
            source="hh-ru",
            external_id=external_id,
            title=str(payload.get("name", "")),
            description="\n".join(part for part in description_parts if part),
            url=payload.get("alternate_url") or payload.get("apply_alternate_url"),
            company_name=employer.get("name") if isinstance(employer, dict) else None,
            company_url=employer.get("alternate_url") if isinstance(employer, dict) else None,
            published_at=_parse_datetime(payload.get("published_at")),
            area=area.get("name") if isinstance(area, dict) else None,
            employment=(employment.get("name") or employment.get("id"))
            if isinstance(employment, dict)
            else None,
            schedule=(schedule.get("name") or schedule.get("id"))
            if isinstance(schedule, dict)
            else None,
            accept_temporary=bool(payload.get("accept_temporary", False)),
            salary_from=salary.get("from") if isinstance(salary, dict) else None,
            salary_to=salary.get("to") if isinstance(salary, dict) else None,
            currency=salary.get("currency") if isinstance(salary, dict) else None,
            has_direct_contact=bool(payload.get("contacts")),
            raw=payload,
        )

