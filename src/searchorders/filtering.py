from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .models import Classification, Lead


SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "brand-platform": ("бренд-платформ", "brand platform", "позиционировани"),
    "brand-identity": (
        "айдентик",
        "брендинг",
        "фирменный стиль",
        "логотип",
        "brand identity",
        "visual identity",
    ),
    "ux-ui": (
        "ux/ui",
        "ui/ux",
        "ux-дизайн",
        "ui-дизайн",
        "дизайн интерфейс",
        "прототип",
        "figma",
        "ux",
        "ui",
    ),
    "corporate-website": ("корпоративный сайт", "сайт компании", "corporate website"),
    "product-website": ("сайт продукта", "продуктовый сайт", "product website"),
    "promo-website": (
        "лендинг",
        "landing page",
        "landing",
        "промосайт",
        "промо-сайт",
        "микросайт",
    ),
    "digital-platform": (
        "digital platform",
        "цифровая платформа",
        "спецпроект",
        "интерактивный проект",
        "квиз",
    ),
    "no-code-development": ("tilda", "webflow", "framer", "no-code", "nocode", "low-code"),
    "frontend-development": (
        "frontend",
        "front-end",
        "верстка сайта",
        "верстку сайта",
        "разработка сайта",
    ),
    "presentation-design": ("дизайн презентац", "презентаци", "pitch deck", "keynote"),
    "research": ("исследовани", "customer research", "market research"),
    "product-audit": ("аудит продукта", "ux-аудит", "ux audit", "аудит сайта"),
    "brand-analytics": ("анализ бренда", "аналитика бренда", "brand audit"),
    "content-production": ("контент-продакшн", "content production", "съемка", "съёмка"),
    "digital-campaign": ("digital-кампан", "digital кампан", "рекламная кампан", "промокампан"),
}

INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "real-estate": ("недвижим", "застройщик", "жилой комплекс", "real estate", "proptech"),
    "luxury": ("премиум", "premium", "luxury", "элитн"),
    "automotive": ("автомоб", "автодилер", "automotive", "дилерск"),
    "events": ("мероприят", "фестивал", "конференц", "event"),
    "fintech": ("банк", "финтех", "fintech", "финанс"),
    "aviation": ("авиац", "airline", "aviation"),
    "technology": ("технолог", "стартап", "saas", "it-продукт", "digital product"),
    "sustainability": ("энергетик", "устойчив", "экологи", "sustainability", "clean energy"),
    "charity": ("благотвор", "нко", "фонд", "charity"),
    "education": ("образован", "университет", "edtech"),
    "crypto": ("крипто", "blockchain", "блокчейн", "web3"),
    "agency": ("агентство", "agency", "студия дизайна", "design studio"),
}

RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "complex-backend": (
        "backend",
        "back-end",
        "django",
        "fastapi",
        "laravel",
        "erp",
        "1с",
        "микросервис",
    ),
    "native-mobile": ("swift", "kotlin", "react native", "flutter", "нативное приложение"),
    "pure-seo": ("seo-специалист", "seo specialist", "поисковое продвижение"),
    "pure-smm": ("smm-менеджер", "smm manager", "ведение социальных сетей"),
    "media-buying": ("media buyer", "медиабаинг", "закупка трафика"),
}

EXTRA_PROJECT_SIGNALS = (
    "фриланс",
    "freelance",
    "разовая задача",
    "разовый проект",
    "проектная работа",
    "проектная занятость",
    "на проект",
    "подряд",
    "договор гпх",
    "договор оказания услуг",
    "дедлайн",
    "техническое задание",
    "готовое тз",
    "фиксированный бюджет",
)

EXTRA_EMPLOYMENT_SIGNALS = (
    "ищем в команду",
    "присоединиться к команде",
    "постоянная занятость",
    "полный рабочий день",
    "работа в офисе",
    "офисный формат",
    "испытательный срок",
    "оформление по тк",
    "трудовой договор",
)

NEGATED_EMPLOYMENT_PHRASES = (
    "не в штат",
    "не ищем в штат",
    "без оформления в штат",
    "не предполагает трудоустройство",
)


def _normalize(value: str) -> str:
    return value.casefold().replace("ё", "е")


def _matches(text: str, phrase: str) -> bool:
    normalized = _normalize(phrase)
    if len(normalized) <= 3 and normalized.isascii() and normalized.isalnum():
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text))
    return normalized in text


def _find_signals(text: str, phrases: Iterable[str]) -> list[str]:
    return sorted({_normalize(phrase) for phrase in phrases if _matches(text, phrase)})


def _tag_text(text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(
        tag for tag, keywords in mapping.items() if any(_matches(text, keyword) for keyword in keywords)
    )


def classify_lead(lead: Lead, profile: dict[str, Any]) -> Classification:
    text = lead.searchable_text
    filter_config = profile.get("lead_filters", {})

    project_phrases = tuple(filter_config.get("positive_project_signals", [])) + EXTRA_PROJECT_SIGNALS
    employment_phrases = tuple(filter_config.get("hard_reject_signals", [])) + EXTRA_EMPLOYMENT_SIGNALS

    project_signals = _find_signals(text, project_phrases)
    employment_signals = _find_signals(text, employment_phrases)
    if any(phrase in text for phrase in NEGATED_EMPLOYMENT_PHRASES):
        employment_signals = [signal for signal in employment_signals if signal != "штат"]

    employment_value = _normalize(lead.employment or "")
    schedule_value = _normalize(lead.schedule or "")
    full_employment = employment_value in {"full", "полная занятость"}
    full_schedule = schedule_value in {"fullDay".casefold(), "полный день"}
    if full_employment:
        employment_signals.append("metadata:full-employment")
    if full_schedule:
        employment_signals.append("metadata:full-day")

    service_tags = _tag_text(text, SERVICE_KEYWORDS)
    industry_tags = _tag_text(text, INDUSTRY_KEYWORDS)
    risk_tags = _tag_text(text, RISK_KEYWORDS)

    explicit_project = lead.accept_temporary or len(project_signals) >= 2
    hard_reject = bool(employment_signals) and not explicit_project
    reasons: list[str] = []

    if hard_reject:
        decision = "reject"
        reasons.append("Обнаружены признаки постоянной штатной занятости")
    elif not service_tags:
        decision = "review"
        reasons.append("Не найдены подтверждённые услуги I’MON")
    elif explicit_project:
        decision = "eligible"
        reasons.append("Есть явные признаки проектной или временной задачи")
    else:
        decision = "review"
        reasons.append("Дизайн-задача подходит по услугам, но проектный формат не подтверждён")

    if employment_signals and explicit_project:
        reasons.append("Есть смешанные сигналы занятости; требуется ручная проверка")
        decision = "review"
    if "complex-backend" in risk_tags and not service_tags:
        reasons.append("Запрос преимущественно связан со сложным backend")

    return Classification(
        hard_reject=hard_reject,
        decision=decision,
        reasons=reasons,
        employment_signals=sorted(set(employment_signals)),
        project_signals=project_signals,
        service_tags=service_tags,
        industry_tags=industry_tags,
        risk_tags=risk_tags,
    )
