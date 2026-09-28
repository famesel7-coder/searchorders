from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


SERVICE_GROUPS = {
    "branding": ("branding", "brand identity", "rebrand", "visual identity", "brand strategy"),
    "presentations": ("presentation design", "pitch deck", "sales deck", "investor deck", "powerpoint design"),
    "web": (
        "website design", "web design", "web development", "digital platform", "landing page",
        "webdesign", "website relaunch", "internet relaunch",
    ),
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
        "grafische vormgeving",
        "vormgevingsdiensten",
        "grafisch ontwerp",
        "grafikdesign",
        "grafische gestaltung",
        "design-dienstleistungen",
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


COLLABORATION_SIGNAL_PHRASES = {
    "international_open": (
        "open to international", "international candidates", "international applicants",
        "worldwide remote", "remote worldwide", "work from anywhere", "anywhere in the world",
        "global, remote", "global remote", "открыты к международным кандидатам",
        "международным кандидатам", "из любой страны", "по всему миру",
    ),
    "remote": ("remote", "удалённ", "удален"),
    "agency_friendly": (
        "agencies welcome", "agency partners welcome", "external design partner",
        "external agency", "design studio partner", "white-label partner", "subcontract partner",
    ),
    "local_only": (
        "canada only", "us only", "u.s. only", "uk only", "united kingdom only",
        "must be based in", "must reside in", "must live in", "only candidates based in",
        "local candidates only", "только кандидаты из", "требуется проживание в",
    ),
    "local_preferred": (
        "local preferred", "local candidates preferred", "preference to candidates",
        "preference for candidates", "prefer candidates based", "предпочтение кандидатам",
        "предпочтение отдают", "желательно из", "предпочтительно",
    ),
    "onsite": (
        "onsite", "on-site", "hybrid", "in-office", "office presence", "studio presence",
        "required presence", "присутствие в", "работа в офисе", "гибрид",
    ),
    "individual_only": (
        "individual freelancer", "individual contractor", "single freelancer", "one designer",
        "hands-on designer", "embedded individual designer", "индивидуального исполнителя",
        "отдельного фрилансера", "отдельного дизайнера", "одного hands-on дизайнера",
        "одного арт-директора",
    ),
}


def _objective_fit_text(lead: dict[str, Any]) -> str:
    fields = (
        "title", "title_ru", "description", "country", "source", "evidence",
        "counter_evidence", "location_scope", "contractor_model", "work_arrangement",
    )
    return " ".join(_flatten_strings({key: lead.get(key) for key in fields})).casefold()


def _has_fit_signal(text: str, group: str) -> bool:
    return any(phrase.casefold() in text for phrase in COLLABORATION_SIGNAL_PHRASES[group])


def collaboration_adjustment(
    lead: dict[str, Any],
    config: dict[str, Any],
) -> tuple[int, list[str]]:
    """Score how realistically I’MON can engage as an international remote studio."""
    weights = {
        "international_open_bonus": 25,
        "remote_bonus": 5,
        "agency_friendly_bonus": 12,
        "local_only_penalty": 45,
        "local_preferred_penalty": 25,
        "onsite_penalty": 20,
        "individual_only_penalty": 15,
    }
    weights.update(config.get("collaboration_fit", {}))
    text = _objective_fit_text(lead)
    adjustment = 0
    reasons: list[str] = []

    if _has_fit_signal(text, "international_open"):
        points = int(weights["international_open_bonus"])
        adjustment += points
        reasons.append(f"international/global remote explicitly allowed (+{points})")

    if _has_fit_signal(text, "remote"):
        points = int(weights["remote_bonus"])
        adjustment += points
        reasons.append(f"remote work supported (+{points})")

    if _has_fit_signal(text, "agency_friendly"):
        points = int(weights["agency_friendly_bonus"])
        adjustment += points
        reasons.append(f"agency/white-label collaboration explicitly supported (+{points})")

    if _has_fit_signal(text, "local_only"):
        points = int(weights["local_only_penalty"])
        adjustment -= points
        reasons.append(f"country/local-only restriction (-{points})")
    elif _has_fit_signal(text, "local_preferred"):
        points = int(weights["local_preferred_penalty"])
        adjustment -= points
        reasons.append(f"local candidates preferred (-{points})")

    if _has_fit_signal(text, "onsite"):
        points = int(weights["onsite_penalty"])
        adjustment -= points
        reasons.append(f"onsite/studio presence requested (-{points})")

    if _has_fit_signal(text, "individual_only"):
        points = int(weights["individual_only_penalty"])
        adjustment -= points
        reasons.append(f"role is oriented to an individual contractor (-{points})")

    return adjustment, reasons


def score_curated_lead(lead: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Adjust analyst confidence by practical international/contractor accessibility."""
    try:
        base_confidence = int(float(lead.get("confidence", 50)))
    except (TypeError, ValueError):
        base_confidence = 50

    fit_adjustment, fit_reasons = collaboration_adjustment(lead, config)
    fit_score = max(0, min(100, base_confidence + fit_adjustment))

    fit_conclusion = "strong" if fit_score >= 75 else "verify_more" if fit_score >= 50 else "reject"
    original_conclusion = str(lead.get("conclusion") or "verify_more")
    levels = {"reject": 0, "verify_more": 1, "strong": 2}
    if original_conclusion not in levels:
        final_conclusion = fit_conclusion
    elif levels[fit_conclusion] < levels[original_conclusion]:
        final_conclusion = fit_conclusion
    else:
        final_conclusion = original_conclusion

    return {
        **lead,
        "base_confidence": base_confidence,
        "fit_adjustment": fit_adjustment,
        "fit_score": fit_score,
        "score": fit_score,
        "fit_reasons": fit_reasons,
        "conclusion": final_conclusion,
    }


def score_lead(lead: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return a transparent 0-100 score with relevance as a hard gate."""
    score = 0
    reasons: list[str] = []

    services = detect_services(lead)
    configured_cpvs = {str(code) for code in config.get("ted_cpv_codes", [])}
    strict_cpvs = {
        str(code)
        for code in config.get("ted_strict_cpv_codes", config.get("ted_cpv_codes", []))
    }
    broad_cpvs = {str(code) for code in config.get("ted_broad_cpv_codes", [])}
    lead_cpvs = {str(code) for code in _flatten_strings(lead.get("cpv"))}
    primary_cpv = str(lead.get("primary_cpv") or "").strip()
    cpv_matches = sorted(configured_cpvs.intersection(lead_cpvs))
    strict_cpv_matches = sorted(strict_cpvs.intersection(lead_cpvs))
    broad_cpv_matches = sorted(broad_cpvs.intersection(lead_cpvs))
    primary_strict_match = primary_cpv if primary_cpv in strict_cpvs else ""

    if services:
        service_points = min(35, 25 + 5 * (len(services) - 1))
        score += service_points
        reasons.append(f"text service match: {', '.join(services)} (+{service_points})")
    if primary_strict_match:
        score += 30
        reasons.append(f"primary graphic/web CPV: {primary_strict_match} (+30)")
    elif strict_cpv_matches and services:
        score += 12
        reasons.append(f"additional design/web CPV backed by text match: {', '.join(strict_cpv_matches)} (+12)")
    elif broad_cpv_matches and services:
        score += 8
        reasons.append(f"broad CPV backed by text match: {', '.join(broad_cpv_matches)} (+8)")

    if not services and not primary_strict_match:
        reason = (
            "design/marketing CPV appears only as secondary context without verified I’MON service match"
            if strict_cpv_matches or broad_cpv_matches
            else "no verified service or primary graphic/web CPV relevance"
        )
        return {
            **lead,
            "services": [],
            "score": 0,
            "score_reasons": [reason],
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
    if source in {"TED", "SAM.gov", "UK Find a Tender"}:
        score += 5
        reasons.append("official procurement source (+5)")

    fit_adjustment, fit_reasons = collaboration_adjustment(lead, config)
    score += fit_adjustment
    reasons.extend(fit_reasons)

    score = max(0, min(100, score))
    return {
        **lead,
        "services": services,
        "score": score,
        "fit_score": score,
        "fit_adjustment": fit_adjustment,
        "fit_reasons": fit_reasons,
        "score_reasons": reasons,
    }
