from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .models import CaseMatch, Classification, Lead, LeadScore

def _clamp(value:int,maximum:int)->int:return max(0,min(value,maximum))
def _freshness_points(lead:Lead,maximum:int,now:datetime)->int:
    if lead.published_at is None:return maximum//2
    published=lead.published_at if lead.published_at.tzinfo else lead.published_at.replace(tzinfo=timezone.utc); hours=max(0.0,(now-published.astimezone(timezone.utc)).total_seconds()/3600)
    if hours<=24:return maximum
    if hours<=48:return round(maximum*.8)
    if hours<=72:return round(maximum*.6)
    if hours<=168:return round(maximum*.3)
    return 0

def score_lead(lead:Lead,classification:Classification,matched_case:CaseMatch|None,profile:dict[str,Any],*,now:datetime|None=None)->LeadScore:
    weights=profile.get("scoring",{}); thresholds=weights.get("thresholds",{}); hot_threshold=int(thresholds.get("hot",75)); review_threshold=int(thresholds.get("review",55)); keys=("service_fit","commercial_fit","project_probability","case_match","client_quality","freshness_urgency","contactability")
    if classification.hard_reject:return LeadScore(total=0,bucket="rejected",breakdown={k:0 for k in keys},reasons=list(classification.reasons))
    priority=set(profile.get("services",{}).get("priority",[])); secondary=set(profile.get("services",{}).get("secondary",[])); priority_hits=priority&set(classification.service_tags); secondary_hits=secondary&set(classification.service_tags); service_max=int(weights.get("service_fit",30)); service_fit=service_max if len(priority_hits)>=2 else round(service_max*.85) if priority_hits else round(service_max*.5) if secondary_hits else 0
    commercial_max=int(weights.get("commercial_fit",20)); commercial=0
    if lead.company_name:commercial+=4
    if lead.effective_budget_from or lead.effective_budget_to:commercial+=7
    if {"luxury","real-estate","automotive","fintech","aviation"}&set(classification.industry_tags):commercial+=4
    if len(lead.description)>=300:commercial+=2
    if lead.has_direct_contact:commercial+=2
    commercial_fit=_clamp(commercial,commercial_max); project_max=int(weights.get("project_probability",15)); project_probability=min(project_max,len(classification.project_signals)*3+len(classification.demand_signals)*3)
    if lead.accept_temporary:project_probability=min(project_max,project_probability+4)
    if classification.intent=="project_demand":project_probability=max(project_probability,round(project_max*.85))
    case_max=int(weights.get("case_match",10)); case_points=0 if matched_case is None else min(case_max,round(3+matched_case.score)); client_max=int(weights.get("client_quality",10)); client_quality=0
    if lead.company_name:client_quality+=4
    if len(lead.description)>=300:client_quality+=2
    if classification.industry_tags:client_quality+=2
    if classification.confidence>=.8:client_quality+=1
    client_quality=_clamp(client_quality,client_max); freshness=_freshness_points(lead,int(weights.get("freshness_urgency",10)),now or datetime.now(timezone.utc)); contactability=_clamp((2 if lead.url else 0)+(3 if lead.has_direct_contact else 0),int(weights.get("contactability",5)))
    breakdown={"service_fit":service_fit,"commercial_fit":commercial_fit,"project_probability":project_probability,"case_match":case_points,"client_quality":client_quality,"freshness_urgency":freshness,"contactability":contactability}; total=sum(breakdown.values()); bucket="hot" if total>=hot_threshold and classification.decision=="eligible" and classification.intent=="project_demand" else "review" if total>=review_threshold else "archive"; reasons=list(classification.reasons)
    if priority_hits:reasons.append(f"Сильное совпадение услуг: {', '.join(sorted(priority_hits))}")
    if lead.effective_budget_from or lead.effective_budget_to:reasons.append("Из публикации извлечён бюджет")
    if matched_case:reasons.append(f"Подобран кейс: {matched_case.name}")
    return LeadScore(total=total,bucket=bucket,breakdown=breakdown,reasons=reasons)
