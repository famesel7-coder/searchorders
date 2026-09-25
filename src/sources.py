from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

TED_URL = "https://api.ted.europa.eu/v3/notices/search"
SAM_URL = "https://api.sam.gov/opportunities/v2/search"
UK_FTS_URL = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"


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


def _extract_next_cursor(data: dict[str, Any]) -> str | None:
    links = data.get("links")
    next_url = ""
    if isinstance(links, dict):
        next_url = str(links.get("next") or "")
    elif isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and str(link.get("rel") or "").lower() == "next":
                next_url = str(link.get("href") or "")
                break
    if not next_url:
        return None
    values = parse_qs(urlparse(next_url).query).get("cursor")
    return values[0] if values else None


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
            "deadline-receipt-tender-date-lot",
        ],
        "limit": int(config.get("ted", {}).get("limit", 250)),
        "scope": config.get("ted", {}).get("scope", "ACTIVE"),
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
        "page": 1,
        "onlyLatestVersions": True,
    }

    response = requests.post(TED_URL, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()

    if data.get("timedOut"):
        raise RuntimeError("TED search timed out")

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
                "description": "",
                "company": _first_text(notice.get("buyer-name")),
                "country": _first_text(notice.get("buyer-country")),
                "published_at": str(_scalar(notice.get("publication-date")) or "")[:10],
                "deadline": str(_scalar(notice.get("deadline-receipt-tender-date-lot")) or "")[:10],
                "value": _scalar(notice.get("estimated-value-proc")),
                "currency": _scalar(notice.get("estimated-value-cur-proc")),
                "cpv": notice.get("classification-cpv") or [],
                "url": f"https://ted.europa.eu/en/notice/-/detail/{pub_no}",
                "raw": notice,
            }
        )
    return leads


def fetch_uk(config: dict[str, Any]) -> list[dict[str, Any]]:
    uk_cfg = config.get("uk_find_a_tender", {})
    if not uk_cfg.get("enabled", True):
        return []

    end_day = date.today()
    start_day = end_day - timedelta(days=int(config["lookback_days"]))
    updated_from = datetime.combine(start_day, time.min).strftime("%Y-%m-%dT%H:%M:%S")
    updated_to = datetime.combine(end_day, time.max).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    limit = min(int(uk_cfg.get("page_size", 100)), 100)
    max_pages = int(uk_cfg.get("max_pages", 3))

    session = requests.Session()
    cursor: str | None = None
    leads: list[dict[str, Any]] = []

    for _ in range(max_pages):
        params: dict[str, Any] = {
            "updatedFrom": updated_from,
            "updatedTo": updated_to,
            "stages": "tender",
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor

        response = session.get(UK_FTS_URL, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()
        releases = data.get("releases", [])
        if not isinstance(releases, list) or not releases:
            break

        for release in releases:
            if not isinstance(release, dict):
                continue
            tender = release.get("tender") if isinstance(release.get("tender"), dict) else {}
            release_id = str(release.get("id") or "").strip()
            ocid = str(release.get("ocid") or "").strip()
            if not release_id:
                continue

            buyer = release.get("buyer") if isinstance(release.get("buyer"), dict) else {}
            value = tender.get("value") if isinstance(tender.get("value"), dict) else {}
            tender_period = tender.get("tenderPeriod") if isinstance(tender.get("tenderPeriod"), dict) else {}

            cpv_codes: list[str] = []
            classification = tender.get("classification") if isinstance(tender.get("classification"), dict) else {}
            if classification.get("id"):
                cpv_codes.append(str(classification["id"]))
            for item in tender.get("items", []) if isinstance(tender.get("items"), list) else []:
                if not isinstance(item, dict):
                    continue
                item_class = item.get("classification") if isinstance(item.get("classification"), dict) else {}
                if item_class.get("id"):
                    cpv_codes.append(str(item_class["id"]))
                for extra in item.get("additionalClassifications", []) if isinstance(item.get("additionalClassifications"), list) else []:
                    if isinstance(extra, dict) and extra.get("id"):
                        cpv_codes.append(str(extra["id"]))

            leads.append(
                {
                    "id": f"uk:{ocid}:{release_id}",
                    "source": "UK Find a Tender",
                    "title": str(tender.get("title") or release.get("description") or "").strip(),
                    "description": str(tender.get("description") or release.get("description") or "").strip(),
                    "company": str(buyer.get("name") or "").strip(),
                    "country": "GBR",
                    "published_at": str(release.get("date") or "")[:10],
                    "deadline": str(tender_period.get("endDate") or "")[:10],
                    "value": value.get("amount"),
                    "currency": value.get("currency") or "GBP",
                    "cpv": sorted(set(cpv_codes)),
                    "url": f"https://www.find-tender.service.gov.uk/Notice/{release_id}",
                    "raw": release,
                }
            )

        cursor = _extract_next_cursor(data)
        if not cursor:
            break

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

            award = row.get("award") if isinstance(row.get("award"), dict) else {}
            leads.append(
                {
                    "id": f"sam:{notice_id}",
                    "source": "SAM.gov",
                    "title": title,
                    "description": "",
                    "company": str(row.get("fullParentPathName") or row.get("department") or "").strip(),
                    "country": "USA",
                    "published_at": str(row.get("postedDate") or "")[:10],
                    "deadline": str(row.get("responseDeadLine") or "")[:10],
                    "value": award.get("amount"),
                    "currency": "USD",
                    "cpv": [],
                    "url": str(row.get("uiLink") or "").strip(),
                    "description_url": str(row.get("description") or "").strip(),
                    "point_of_contact": row.get("pointOfContact") or [],
                    "raw": row,
                }
            )

        if len(rows) < page_size:
            break

    return leads
