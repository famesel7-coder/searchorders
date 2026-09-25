from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


SERVICE_GROUPS = {
    "branding": ("branding", "brand identity", "rebrand", "visual identity", "brand strategy"),
    "presentations": ("presentation design", "pitch deck", "sales deck", "investor deck", "powerpoint design"),
    "web": ("website design", "web design", "web development", "digital platform", "landing page"),
    "ux_ui": (
        "ux design",
        "ui design",
        "user experience",
        "user interface",
        "product design",
    ),
    "creative": (
        "graphic design",
        "creative services",
        "marketing materials",
        "communication design",
        "visual communication",
    ),
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _contains_phrase(text: str, phrase: str) -> bool:
    # Word boundaries stop short terms from matching inside unrelated words.
    pattern = r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"
    return re.search(pattern, text.lower()) is not None


def detect_services(lead: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(lead.get(key) or "")
        for key in ("title", "description", "company")
    ).lower()
    return [
        service
        for service, terms in SERVICE_GROUPS.items()
        if any(_contains_phrase(haystack, term) for term in terms)
    ]


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_flatten_strings(item))
        return out
    return [str(value)]


def score_lead(lead: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return a transparent 0-100 score with relevance as a hard gate."""
    score = 0
    reasons: list[str] = []

    services = detect_services(lead)
    configured_cpvs = {str(code) for code in config.get("ted_cpv_codes", [])}
    lead_cpvs = {str(code) for code in _flatten_strings(lead.get("cpv"))}
    cpv_matches = sorted(configured_cpvs.intersection(lead_cpvs))

    if services:
        service_points = min(35, 25 + 5 * (len(services) - 1))
        score += service_points
        reasons.append(f"text service match: {', '.join(services)} (+{service_points})")
    if cpv_matches:
        score += 25
        reasons.append(f"relevant CPV: {', '.join(cpv_matches)} (+25)")

    # Money, freshness and geography must never make an unrelated tender look good.
    if not services and not cpv_matches:
        return {
            **lead,
            "services": [],
            "score": 0,
            "score_reasons": ["no verified service or CPV relevance"],
        }

    country = str(lead.get("country") or "").upper()
    markets = {str(v).upper() for v in config.get("target_markets", [])}
    aliases = {
        "US": "USA", "UNITED STATES": "USA", "UNITED STATES OF AMERICA": "USA",
        "UK": "GBR", "GB": "GBR", "UNITED KINGDOM": "GBR",
        "DE": "DEU", "GERMANY": "DEU",
        "NL": "NLD", "NETHERLANDS": "NLD",
        "CH": "CHE", "SWITZERLAND": "CHE",
    }
    normalized_country = aliases.get(country, country)
    if normalized_country in markets:
        score += 10
        reasons.append("target market (+10)")

    published = _parse_date(str(lead.get("published_at") or ""))
    if published:
        age = max(0, (date.today() - published).days)
        if age <= 3:
            score += 15
            reasons.append("published within 3 days (+15)")
        elif age <= 7:
            score += 10
            reasons.append("published within 7 days (+10)")
        elif age <= int(config.get("lookback_days", 14)):
            score += 5
            reasons.append("recent lead (+5)")

    raw_value = lead.get("value")
    try:
        value = float(raw_value) if raw_value not in (None, "") else None
    except (TypeError, ValueError):
        value = None

    if value is not None:
        if value >= 50_000:
            score += 15
            reasons.append("declared value >= 50k (+15)")
        elif value >= 10_000:
            score += 10
            reasons.append("declared value >= 10k (+10)")
        elif value >= 3_000:
            score += 5
            reasons.append("declared value >= 3k (+5)")

    deadline = _parse_date(str(lead.get("deadline") or ""))
    if deadline:
        days_left = (deadline - date.today()).days
        if days_left >= 14:
            score += 10
            reasons.append("at least 14 days to respond (+10)")
        elif days_left >= 5:
            score += 5
            reasons.append("at least 5 days to respond (+5)")
        elif days_left < 0:
            score -= 25
            reasons.append("deadline passed (-25)")

    if lead.get("url"):
        score += 5
        reasons.append("direct source URL (+5)")

    source = str(lead.get("source") or "")
    if source in {"TED", "SAM.gov"}:
        score += 5
        reasons.append("official procurement source (+5)")

    score = max(0, min(100, score))
    return {
        **lead,
        "services": services,
        "score": score,
        "score_reasons": reasons,
    }
