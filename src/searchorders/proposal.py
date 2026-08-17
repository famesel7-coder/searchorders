from __future__ import annotations
from .models import CaseMatch, Classification, Lead
SERVICE_LABELS={"brand-platform":"бренд-платформой","brand-identity":"айдентикой и фирменным стилем","ux-ui":"UX/UI-дизайном","corporate-website":"корпоративным сайтом","product-website":"сайтом продукта","promo-website":"промосайтом или лендингом","digital-platform":"digital-платформой","no-code-development":"дизайном и no-code разработкой","frontend-development":"дизайном и web-разработкой","presentation-design":"бизнес-презентацией"}
WEBSITE_TAGS=("corporate-website","product-website","promo-website","no-code-development","frontend-development","ux-ui")
def _primary_service(lead:Lead,classification:Classification)->str:
    tags=set(classification.service_tags); title=lead.title.casefold()
    if "презентац" in title and "presentation-design" in tags:return "presentation-design"
    if any(w in title for w in ("сайт","лендинг","landing","web")):
        for tag in WEBSITE_TAGS:
            if tag in tags:return tag
    for tag in SERVICE_LABELS:
        if tag in tags:return tag
    return classification.service_tags[0]
def _budget_line(lead:Lead)->str|None:
    low,high=lead.effective_budget_from,lead.effective_budget_to
    if not low and not high:return None
    currency=lead.currency or "RUB"
    if low and high:return f"Вижу обозначенный бюджет {low:,}–{high:,} {currency}; состав работ стоит собрать под него без лишнего объёма.".replace(","," ")
    if low:return f"Вижу ориентир бюджета от {low:,} {currency}; можно сразу предложить реалистичный состав работ.".replace(","," ")
    return f"Вижу верхний ориентир бюджета до {high:,} {currency}; можно приоритизировать обязательный объём.".replace(","," ")
def create_proposal_draft(lead:Lead,classification:Classification,matched_case:CaseMatch|None,*,site_url:str)->str|None:
    if classification.hard_reject or not classification.service_tags:return None
    service=SERVICE_LABELS.get(_primary_service(lead,classification),"digital-дизайном и реализацией"); company=f" для {lead.company_name}" if lead.company_name else ""; lines=[f"Здравствуйте! Увидели вашу задачу «{lead.title}»{company}.",f"По описанию здесь важен не просто визуал, а понятный проектный результат. I’MON может помочь с {service}: быстро уточнить цели и ограничения, собрать концепцию и довести её до запуска."]
    if lead.deadline_text:lines.append(f"Учитывая срок «{lead.deadline_text}», на старте лучше быстро зафиксировать обязательный объём и контрольные точки.")
    budget=_budget_line(lead)
    if budget:lines.append(budget)
    if matched_case:lines.append(f"Из близкого по характеру опыта — {matched_case.name}: {matched_case.url}")
    lines.extend([f"О студии и другие проекты: {site_url}","Если задача ещё актуальна, пришлите бриф/вводные — вернёмся с предложением по составу работ и следующему шагу."])
    return "\n\n".join(lines)
