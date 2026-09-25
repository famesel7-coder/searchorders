from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import requests

TED_URL = "https://api.ted.europa.eu/v3/notices/search"
SAM_URL = "https://api.sam.gov/opportunities/v2/search"


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for preferred in ("eng", "en"):
            if preferred in value:
                text = _first_text(value[preferred])
                if text:
                    return text
        for item in value.values():
            text = _first_text(item)
            if text:
                return text
    return ""


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def fetch_ted(config: dict[str, Any]) -> list[dict[str, Any]]:
    if not config.get("ted", {}).get("enabled", True):
        return []

    since = (date.today() - timedelta(days=int(config["lookback_days"]))).strftime("%Y%m%d")
    countries = " ".join(config.get("ted_buyer_countries", []))
    cpvs = " ".join(config.get("ted_cpv_codes", []))
    keywords = config.get("keywords", [])

    signal_parts = []
    if cpvs:
        signal_parts.append(f"classification-cpv IN ({cpvs})")
    signal_parts.extend(f'FT~"{kw}"' for kw in keywords)
    signal_query = " OR ".join(signal_parts) or "OJ=()"

    filters = [f"publication-date>={since}", f"({signal_query})"]
    if countries:
        filters.append(f"buyer-country IN ({countries})")
    query = " AND ".join(filters) + " SORT BY publication-date DESC"

    payload = {
        "query": query,
        "fields": [
            "publication-number",
            "publication-date",
            "notice-title",
            "buyer-name",
            "buyer-country",
            "classification-cpv",
            "estimated-value-proc",
            "estimated-value-cur-proc",
            "deadline",
            "links",
        ],
        "limit": int(config.get("ted", {}).get("limit", 250)),
        "scope": config.get("ted", {}).get("scope", "ACTIVE"),
        "checkQuerySyntax": True,
        "paginationMode": "PAGE_NUMBER",
        "page": 1,
    }

    response = requests.post(TED_URL, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()

    leads: list[dict[str, Any]] = []
    for notice in data.get("notices", []):
        pub_no = str(_scalar(notice.get("publication-number")) or "").strip()
        if not pub_no:
            continue
        leads.append(
            {
                "id": f"ted:{pub_no}",
                "source": "TED",
                "title": _first_text(notice.get("notice-title")),
                "company": _first_text(notice.get("buyer-name")),
                "country": _first_text(notice.get("buyer-country")),
                "published_at": str(_scalar(notice.get("publication-date")) or "")[:10],
                "deadline": str(_scalar(notice.get("deadline")) or "")[:10],
                "value": _scalar(notice.get("estimated-value-proc")),
                "currency": _scalar(notice.get("estimated-value-cur-proc")),
                "cpv": notice.get("classification-cpv") or [],
                "url": f"https://ted.europa.eu/en/notice/-/detail/{pub_no}",
                "raw": notice,
            }
        )
    return leads


def fetch_sam(config: dict[str, Any]) -> list[dict[str, Any]]:
    sam_cfg = config.get("sam", {})
    if not sam_cfg.get("enabled", True):
        return []

    api_key = os.getenv("SAM_API_KEY", "").strip()
    if not api_key:
        return []

    end = date.today()
    start = end - timedelta(days=int(config["lookback_days"]))
    page_size = min(int(sam_cfg.get("page_size", 1000)), 1000)
    max_pages = int(sam_cfg.get("max_pages", 3))
    keywords = [k.lower() for k in config.get("keywords", [])]

    leads: list[dict[str, Any]] = []
    for page in range(max_pages):
        params = {
            "api_key": api_key,
            "postedFrom": start.strftime("%m/%d/%Y"),
            "postedTo": end.strftime("%m/%d/%Y"),
            "limit": page_size,
            "offset": page * page_size,
        }
        response = requests.get(SAM_URL, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()
        rows = data.get("opportunitiesData", [])
        if not rows:
            break

        for row in rows:
            title = str(row.get("title") or "").strip()
            searchable = " ".join(
                str(row.get(k) or "")
                for k in ("title", "type", "baseType", "department", "subTier", "office")
            ).lower()
            if keywords and not any(keyword in searchable for keyword in keywords):
                continue

            notice_id = str(row.get("noticeId") or "").strip()
            if not notice_id:
                continue
            leads.append(
                {
                    "id": f"sam:{notice_id}",
                    "source": "SAM.gov",
                    "title": title,
                    "company": str(row.get("fullParentPathName") or row.get("department") or "").strip(),
                    "country": "USA",
                    "published_at": str(row.get("postedDate") or "")[:10],
                    "deadline": str(row.get("responseDeadLine") or "")[:10],
                    "value": None,
                    "currency": "USD",
                    "cpv": [],
                    "url": str(row.get("uiLink") or "").strip(),
                    "raw": row,
                }
            )

        if len(rows) < page_size:
            break

    return leads
