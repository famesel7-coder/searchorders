from __future__ import annotations

from .models import CaseMatch, Classification, Lead


SERVICE_LABELS = {
    "brand-platform": "бренд-платформой",
    "brand-identity": "айдентикой и фирменным стилем",
    "ux-ui": "UX/UI-дизайном",
    "corporate-website": "корпоративным сайтом",
    "product-website": "сайтом продукта",
    "promo-website": "промосайтом или лендингом",
    "digital-platform": "digital-платформой",
    "no-code-development": "дизайном и no-code разработкой",
    "frontend-development": "дизайном и web-разработкой",
    "presentation-design": "бизнес-презентацией",
}

WEBSITE_TAGS = (
    "corporate-website",
    "product-website",
    "promo-website",
    "no-code-development",
    "frontend-development",
    "ux-ui",
)


def _primary_service(lead: Lead, classification: Classification) -> str:
    tags = set(classification.service_tags)
    title = lead.title.casefold()
    if "презентац" in title or "presentation" in title:
        if "presentation-design" in tags:
            return "presentation-design"
    if any(word in title for word in ("сайт", "лендинг", "landing", "web")):
        for tag in WEBSITE_TAGS:
            if tag in tags:
                return tag
    for tag in SERVICE_LABELS:
        if tag in tags:
            return tag
    return classification.service_tags[0]


def create_proposal_draft(
    lead: Lead,
    classification: Classification,
    matched_case: CaseMatch | None,
    *,
    site_url: str,
) -> str | None:
    if classification.hard_reject or not classification.service_tags:
        return None

    primary_tag = _primary_service(lead, classification)
    service = SERVICE_LABELS.get(primary_tag, "digital-дизайном и реализацией")
    company = f" для {lead.company_name}" if lead.company_name else ""

    lines = [
        f"Здравствуйте! Увидели вашу задачу «{lead.title}»{company}.",
        f"I’MON может помочь с {service}: уточнить задачу, собрать визуальную концепцию и довести решение до запуска без разрыва между дизайном и реализацией.",
    ]
    if matched_case:
        lines.append(
            f"Близкий по характеру кейс — {matched_case.name}: {matched_case.url}"
        )
    lines.extend(
        [
            f"О студии и другие проекты: {site_url}",
            "Если задача ещё актуальна, можем быстро изучить бриф и предложить состав работ и следующий шаг.",
        ]
    )
    return "\n\n".join(lines)
