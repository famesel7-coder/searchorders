from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collectors import WorkspaceCollector, WorkspaceCollectorError
from .models import Lead, LeadEvaluation
from .pipeline import evaluate_leads
from .state import SeenLeadStore


class SourceScanError(RuntimeError):
    pass


@dataclass(slots=True)
class ScanResult:
    collected_count: int
    new_count: int
    evaluations: list[LeadEvaluation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _workspace_collector(source: dict[str, Any]) -> WorkspaceCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"Workspace source {source.get('id')} has no listing_urls")
    return WorkspaceCollector(
        [str(url) for url in listing_urls],
        max_details=int(source.get("max_details", 30)),
        request_delay_seconds=float(source.get("request_delay_seconds", 0.5)),
    )


def collect_sources(
    sources: list[dict[str, Any]],
    *,
    max_results: int = 30,
    collector_factory: Any | None = None,
) -> tuple[list[Lead], list[str]]:
    collected: list[Lead] = []
    warnings: list[str] = []
    factory = collector_factory or _workspace_collector
    for source in sources:
        source_type = str(source.get("type", ""))
        if source_type != "workspace":
            warnings.append(f"Unsupported source type: {source_type}")
            continue
        try:
            collector = factory(source)
            remaining = max(0, max_results - len(collected))
            if not remaining:
                break
            collected.extend(collector.collect(max_results=remaining))
            warnings.extend(getattr(collector, "warnings", []))
        except (SourceScanError, WorkspaceCollectorError, ValueError) as exc:
            warnings.append(f"{source.get('id', source_type)}: {exc}")
    unique: dict[tuple[str, str], Lead] = {}
    for lead in collected:
        unique.setdefault((lead.source, lead.external_id), lead)
    return list(unique.values()), warnings


def scan_sources(
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    *,
    state_path: str | Path,
    max_results: int = 30,
    collector_factory: Any | None = None,
) -> ScanResult:
    collected, warnings = collect_sources(
        sources,
        max_results=max_results,
        collector_factory=collector_factory,
    )
    store = SeenLeadStore(state_path)
    new_leads = store.only_new(collected)
    evaluations = evaluate_leads(new_leads, profile, cases)
    store.mark_seen(new_leads)
    return ScanResult(
        collected_count=len(collected),
        new_count=len(new_leads),
        evaluations=evaluations,
        warnings=warnings,
    )

