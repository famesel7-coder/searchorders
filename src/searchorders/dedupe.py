from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from .models import Lead
from .normalization import compact_source_refs, contact_set, content_fingerprint, normalize_text


@dataclass(slots=True)
class DedupGroup:
    canonical: Lead
    members: list[Lead]


def similarity(a: Lead, b: Lead) -> float:
    left = normalize_text(f"{a.title} {a.description}"); right = normalize_text(f"{b.title} {b.description}")
    if not left or not right: return 0.0
    return SequenceMatcher(None, left[:6000], right[:6000], autojunk=False).ratio()


def are_duplicates(a: Lead, b: Lead) -> bool:
    if content_fingerprint(a) == content_fingerprint(b): return True
    score = similarity(a, b); shared_contacts = contact_set(a) & contact_set(b)
    if shared_contacts and score >= 0.78: return True
    return score >= 0.94


def _richness(lead: Lead) -> tuple[int, int, int, int]:
    return (len(lead.description), int(bool(lead.company_name)), int(bool(lead.contacts)), int(bool(lead.effective_budget_from or lead.effective_budget_to)))


def _canonical(members: list[Lead]) -> Lead:
    best = max(members, key=_richness); raw = dict(best.raw); raw["source_refs"] = compact_source_refs(members)
    return replace(best, raw=raw)


def group_duplicate_leads(leads: list[Lead]) -> list[DedupGroup]:
    groups: list[list[Lead]] = []
    for lead in leads:
        for members in groups:
            if are_duplicates(lead, members[0]): members.append(lead); break
        else: groups.append([lead])
    return [DedupGroup(canonical=_canonical(members), members=members) for members in groups]
