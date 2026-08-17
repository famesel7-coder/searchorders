from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from .models import Classification, Lead

SERVICE_KEYWORDS={"brand-platform":("бренд-платформ","brand platform","позиционировани"),"brand-identity":("айдентик","брендинг","фирменный стиль","логотип","brand identity","visual identity"),"ux-ui":("ux/ui","ui/ux","ux-дизайн","ui-дизайн","дизайн интерфейс","прототип","figma","ux","ui"),"corporate-website":("корпоративный сайт","сайт компании","corporate website"),"product-website":("сайт продукта","продуктовый сайт","product website"),"promo-website":("лендинг","landing page","landing","промосайт","промо-сайт","микросайт"),"digital-platform":("digital platform","цифровая платформа","спецпроект","интерактивный проект","квиз"),"no-code-development":("tilda","webflow","framer","no-code","nocode","low-code"),"frontend-development":("frontend","front-end","верстка сайта","верстку сайта","разработка сайта"),"presentation-design":("дизайн презентац","презентаци","pitch deck","keynote"),"research":("исследовани","customer research","market research"),"product-audit":("аудит продукта","ux-аудит","ux audit","аудит сайта"),"brand-analytics":("анализ бренда","аналитика бренда","brand audit"),"content-production":("контент-продакшн","content production","съемка","съёмка"),"digital-campaign":("digital-кампан","digital кампан","рекламная кампан","промокампан")}
INDUSTRY_KEYWORDS={"real-estate":("недвижим","застройщик","жилой комплекс","real estate","proptech"),"luxury":("премиум","premium","luxury","элитн"),"automotive":("автомоб","автодилер","automotive","дилерск"),"events":("мероприят","фестивал","конференц","event"),"fintech":("банк","финтех","fintech","финанс"),"aviation":("авиац","airline","aviation"),"technology":("технолог","стартап","saas","it-продукт","digital product"),"sustainability":("энергетик","устойчив","экологи","sustainability","clean energy"),"charity":("благотвор","нко","фонд","charity"),"education":("образован","университет","edtech"),"crypto":("крипто","blockchain","блокчейн","web3"),"agency":("агентство","agency","студия дизайна","design studio")}
RISK_KEYWORDS={"complex-backend":("backend","back-end","django","fastapi","laravel","erp","1с","микросервис"),"native-mobile":("swift","kotlin","react native","flutter","нативное приложение"),"pure-seo":("seo-специалист","seo specialist","поисковое продвижение"),"pure-smm":("smm-менеджер","smm manager","ведение социальных сетей"),"media-buying":("media buyer","медиабаинг","закупка трафика")}
EXTRA_PROJECT_SIGNALS=("фриланс","freelance","разовая задача","разовый проект","проектная работа","проектная занятость","на проект","подряд","договор гпх","договор оказания услуг","дедлайн","техническое задание","готовое тз","фиксированный бюджет","part-time","part time","проектно","срок —","срок -")
EXTRA_EMPLOYMENT_SIGNALS=("ищем в команду","присоединиться к команде","постоянная занятость","полный рабочий день","работа в офисе","офисный формат","испытательный срок","оформление по тк","трудовой договор","5/2","оклад","штат")
DEMAND_SIGNALS=("ищем подрядчика","ищем исполнителя","ищем дизайнера","ищу дизайнера","нужен дизайнер","нужна команда","нужно агентство","ищем агентство","нужен подрядчик","нужен исполнитель","требуется дизайнер","посоветуйте дизайнера","порекомендуйте дизайнера","посоветуйте студию","порекомендуйте студию","есть задача","есть проект","задача:","задача —","задача -","требуется разработать","нужно разработать")
SELF_PROMO_SIGNALS=("открыт для новых проектов","открыта для новых проектов","ищу работу","ищу проекты","мое портфолио","моё портфолио","мои услуги","я дизайнер","я ux","я ui","готов взять проект","готова взять проект")
NEGATED_EMPLOYMENT_PHRASES=("не в штат","не ищем в штат","без оформления в штат","не предполагает трудоустройство")

def _normalize(value:str)->str:return value.casefold().replace("ё","е")
def _matches(text:str,phrase:str)->bool:
    normalized=_normalize(phrase)
    if len(normalized)<=3 and normalized.isascii() and normalized.isalnum(): return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",text))
    return normalized in text
def _find_signals(text:str,phrases:Iterable[str])->list[str]:return sorted({_normalize(p) for p in phrases if _matches(text,p)})
def _tag_text(text:str,mapping:dict[str,tuple[str,...]])->list[str]:return sorted(tag for tag,keywords in mapping.items() if any(_matches(text,k) for k in keywords))

def classify_lead(lead:Lead,profile:dict[str,Any])->Classification:
    text=lead.searchable_text; cfg=profile.get("lead_filters",{})
    project_signals=_find_signals(text,tuple(cfg.get("positive_project_signals",[]))+EXTRA_PROJECT_SIGNALS); employment_signals=_find_signals(text,tuple(cfg.get("hard_reject_signals",[]))+EXTRA_EMPLOYMENT_SIGNALS); demand_signals=_find_signals(text,tuple(cfg.get("demand_signals",[]))+DEMAND_SIGNALS); self_promo=_find_signals(text,SELF_PROMO_SIGNALS)
    if any(p in text for p in NEGATED_EMPLOYMENT_PHRASES): employment_signals=[s for s in employment_signals if s not in {"штат","metadata:full-employment","metadata:full-day"}]
    if _normalize(lead.employment or "") in {"full","полная занятость"}: employment_signals.append("metadata:full-employment")
    if _normalize(lead.schedule or "") in {"fullday","полный день"}: employment_signals.append("metadata:full-day")
    service_tags=_tag_text(text,SERVICE_KEYWORDS); industry_tags=_tag_text(text,INDUSTRY_KEYWORDS); risk_tags=_tag_text(text,RISK_KEYWORDS)
    explicit_project=lead.accept_temporary or bool(project_signals); explicit_demand=bool(demand_signals) or (explicit_project and bool(service_tags)); reasons=[]
    if self_promo and not demand_signals: hard_reject,decision,intent,confidence=True,"reject","self_promo",.95; reasons.append("Публикация похожа на резюме/самопрезентацию, а не на спрос заказчика")
    elif employment_signals and not explicit_project: hard_reject,decision,intent,confidence=True,"reject","employment",.95; reasons.append("Обнаружены признаки постоянной штатной занятости")
    elif not service_tags: hard_reject,decision,intent,confidence=False,"review","ambiguous",.45; reasons.append("Не найдены подтверждённые услуги I’MON")
    elif explicit_project and explicit_demand: hard_reject,decision,intent,confidence=False,"eligible","project_demand",.9; reasons.append("Есть признаки коммерческого проектного спроса")
    elif explicit_demand: hard_reject,decision,intent,confidence=False,"review","demand",.7; reasons.append("Есть спрос на услугу, но проектный формат требует проверки")
    else: hard_reject,decision,intent,confidence=False,"review","ambiguous",.5; reasons.append("Услуга релевантна, но намерение заказчика не подтверждено")
    if employment_signals and explicit_project and not hard_reject: reasons.append("Есть смешанные сигналы проекта и занятости; требуется ручная проверка"); decision="review"; confidence=min(confidence,.65)
    return Classification(hard_reject=hard_reject,decision=decision,intent=intent,confidence=confidence,reasons=reasons,employment_signals=sorted(set(employment_signals)),project_signals=project_signals,demand_signals=demand_signals,service_tags=service_tags,industry_tags=industry_tags,risk_tags=risk_tags)
