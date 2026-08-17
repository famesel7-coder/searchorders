from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Lead:
    source: str
    external_id: str
    title: str
    description: str = ""
    url: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    author_name: str | None = None
    company_name: str | None = None
    company_url: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime = field(default_factory=utc_now)
    area: str | None = None
    employment: str | None = None
    schedule: str | None = None
    accept_temporary: bool = False
    salary_from: int | None = None
    salary_to: int | None = None
    budget_from: int | None = None
    budget_to: int | None = None
    currency: str | None = None
    has_direct_contact: bool = False
    contacts: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def searchable_text(self) -> str:
        values = (self.title, self.description, self.company_name or "", self.author_name or "", self.employment or "", self.schedule or "")
        return "\n".join(values).casefold().replace("ё", "е")

    @property
    def effective_budget_from(self) -> int | None:
        return self.budget_from if self.budget_from is not None else self.salary_from

    @property
    def effective_budget_to(self) -> int | None:
        return self.budget_to if self.budget_to is not None else self.salary_to

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("published_at", "discovered_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value else None
        if not include_raw:
            payload.pop("raw", None)
        return payload


@dataclass(slots=True)
class Classification:
    hard_reject: bool
    decision: str
    intent: str = "ambiguous"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    employment_signals: list[str] = field(default_factory=list)
    project_signals: list[str] = field(default_factory=list)
    demand_signals: list[str] = field(default_factory=list)
    service_tags: list[str] = field(default_factory=list)
    industry_tags: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaseMatch:
    case_id: str
    name: str
    url: str
    score: float
    matched_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LeadScore:
    total: int
    bucket: str
    breakdown: dict[str, int]
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LeadEvaluation:
    lead: Lead
    classification: Classification
    score: LeadScore
    matched_case: CaseMatch | None = None
    proposal_draft: str | None = None
    catalog_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"catalog_id": self.catalog_id, "lead": self.lead.to_dict(), "classification": self.classification.to_dict(), "score": self.score.to_dict(), "matched_case": self.matched_case.to_dict() if self.matched_case else None, "proposal_draft": self.proposal_draft}
