from __future__ import annotations
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from .filtering import classify_lead
from .matching import match_case
from .models import Lead, LeadEvaluation
from .proposal import create_proposal_draft
from .scoring import score_lead

def evaluate_lead(lead:Lead,profile:dict[str,Any],cases:list[dict[str,Any]],*,now:datetime|None=None)->LeadEvaluation:
    classification=classify_lead(lead,profile); matched_case=None if classification.hard_reject else match_case(lead,classification,cases); score=score_lead(lead,classification,matched_case,profile,now=now); proposal=None
    if score.bucket in {"hot","review"}:proposal=create_proposal_draft(lead,classification,matched_case,site_url=str(profile.get("proposal",{}).get("site_url","https://imon.agency/")))
    return LeadEvaluation(lead=lead,classification=classification,score=score,matched_case=matched_case,proposal_draft=proposal)
def evaluate_leads(leads:Iterable[Lead],profile:dict[str,Any],cases:list[dict[str,Any]],*,now:datetime|None=None)->list[LeadEvaluation]:
    evaluations=[evaluate_lead(lead,profile,cases,now=now) for lead in leads]; order={"hot":0,"review":1,"archive":2,"rejected":3}; return sorted(evaluations,key=lambda item:(order.get(item.score.bucket,9),-item.score.total))
