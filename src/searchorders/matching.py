from __future__ import annotations

from typing import Any

from .models import CaseMatch, Classification, Lead


def _normalize_tag(value: str) -> str:
    return value.casefold().replace("_", "-").strip()


def _case_tags(case: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("services", "industries", "best_for"):
        raw = case.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return {_normalize_tag(value) for value in values}


SERVICE_EQUIVALENTS: dict[str, set[str]] = {
    "brand-identity": {"identity", "brand-design", "graphic-design", "event-branding"},
    "promo-website": {"web-design", "development", "campaign-platform", "event-website"},
    "corporate-website": {"corporate-platform", "web-design", "development"},
    "product-website": {"web-design", "development", "interactive-product-site"},
    "frontend-development": {"development", "web-design"},
    "no-code-development": {"development", "web-design"},
    "digital-platform": {"digital-product", "interactive-platform", "campaign-platform"},
    "presentation-design": {"presentation", "corporate-presentation"},
}

INDUSTRY_EQUIVALENTS: dict[str, set[str]] = {
    "real-estate": {"premium-real-estate", "proptech"},
    "aviation": {"private-aviation"},
    "technology": {"vr", "clean-energy", "crypto"},
    "events": {"entertainment"},
}


def _expand(tags: set[str], equivalents: dict[str, set[str]]) -> set[str]:
    expanded = set(tags)
    for tag in tags:
        expanded.update(equivalents.get(tag, set()))
    return expanded


def match_case(
    lead: Lead,
    classification: Classification,
    cases: list[dict[str, Any]],
) -> CaseMatch | None:
    service_tags = _expand(set(classification.service_tags), SERVICE_EQUIVALENTS)
    industry_tags = _expand(set(classification.industry_tags), INDUSTRY_EQUIVALENTS)

    best: CaseMatch | None = None
    for case in cases:
        url = case.get("url")
        if not isinstance(url, str) or not url:
            continue

        tags = _case_tags(case)
        service_overlap = service_tags & tags
        industry_overlap = industry_tags & tags
        score = len(service_overlap) * 3.0 + len(industry_overlap) * 2.0

        evidence_level = case.get("evidence_level")
        if evidence_level == "high":
            score += 0.75
        elif evidence_level == "medium":
            score += 0.25

        title = lead.title.casefold()
        if "презентац" in title and "presentation-design" in tags:
            score += 2.0
        if "сайт" in title and {"web-design", "development"} & tags:
            score += 1.0

        if score <= 0:
            continue

        candidate = CaseMatch(
            case_id=str(case.get("id", "unknown")),
            name=str(case.get("name", case.get("id", "Unknown case"))),
            url=url,
            score=round(score, 2),
            matched_tags=sorted(service_overlap | industry_overlap),
        )
        if best is None or candidate.score > best.score:
            best = candidate

    return best

