from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collectors import (
    FreelanceTaskCollector,
    FreelanceTaskCollectorError,
    RSSFeedCollector,
    RSSFeedCollectorError,
    TelegramClientCollector,
    TelegramClientCollectorError,
    TelegramPublicCollector,
    TelegramPublicCollectorError,
    VkWallCollector,
    VkWallCollectorError,
    WorkspaceCollector,
    WorkspaceCollectorError,
)
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


def _freelance_task_collector(source: dict[str, Any]) -> FreelanceTaskCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"Freelance source {source.get('id')} has no listing_urls")
    allowed_categories = source.get("allowed_categories")
    if allowed_categories is not None and not isinstance(allowed_categories, list):
        raise SourceScanError(
            f"Freelance source {source.get('id')} has invalid allowed_categories"
        )
    return FreelanceTaskCollector(
        [str(url) for url in listing_urls],
        allowed_categories=[str(item) for item in (allowed_categories or [])],
        max_details=int(source.get("max_details", 30)),
        request_delay_seconds=float(source.get("request_delay_seconds", 0.5)),
    )


def _rss_feed_collector(source: dict[str, Any]) -> RSSFeedCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"RSS source {source.get('id')} has no listing_urls")
    include_patterns = source.get("include_patterns")
    if include_patterns is not None and not isinstance(include_patterns, list):
        raise SourceScanError(f"RSS source {source.get('id')} has invalid include_patterns")
    exclude_patterns = source.get("exclude_patterns")
    if exclude_patterns is not None and not isinstance(exclude_patterns, list):
        raise SourceScanError(f"RSS source {source.get('id')} has invalid exclude_patterns")
    return RSSFeedCollector(
        [str(url) for url in listing_urls],
        include_patterns=[str(item) for item in (include_patterns or [])],
        exclude_patterns=[str(item) for item in (exclude_patterns or [])],
        area=str(source.get("area") or "Internet"),
        employment=str(source.get("employment") or "Публичная лента"),
        max_details=int(source.get("max_details", 30)),
    )


def _telegram_public_collector(source: dict[str, Any]) -> TelegramPublicCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"Telegram source {source.get('id')} has no listing_urls")
    include_patterns = source.get("include_patterns")
    if include_patterns is not None and not isinstance(include_patterns, list):
        raise SourceScanError(
            f"Telegram source {source.get('id')} has invalid include_patterns"
        )
    exclude_patterns = source.get("exclude_patterns")
    if exclude_patterns is not None and not isinstance(exclude_patterns, list):
        raise SourceScanError(
            f"Telegram source {source.get('id')} has invalid exclude_patterns"
        )
    return TelegramPublicCollector(
        [str(url) for url in listing_urls],
        include_patterns=[str(item) for item in (include_patterns or [])],
        exclude_patterns=[str(item) for item in (exclude_patterns or [])],
        max_details=int(source.get("max_details", 30)),
        request_delay_seconds=float(source.get("request_delay_seconds", 0.5)),
    )


def _telegram_client_collector(source: dict[str, Any]) -> TelegramClientCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"Telegram client source {source.get('id')} has no listing_urls")
    include_patterns = source.get("include_patterns")
    if include_patterns is not None and not isinstance(include_patterns, list):
        raise SourceScanError(
            f"Telegram client source {source.get('id')} has invalid include_patterns"
        )
    exclude_patterns = source.get("exclude_patterns")
    if exclude_patterns is not None and not isinstance(exclude_patterns, list):
        raise SourceScanError(
            f"Telegram client source {source.get('id')} has invalid exclude_patterns"
        )
    history_limit = int(source.get("history_limit", 200))
    api_id_env = str(source.get("api_id_env") or "TELEGRAM_API_ID")
    api_hash_env = str(source.get("api_hash_env") or "TELEGRAM_API_HASH")
    session_env = str(source.get("session_env") or "TELEGRAM_SESSION")
    return TelegramClientCollector(
        [str(url) for url in listing_urls],
        include_patterns=[str(item) for item in (include_patterns or [])],
        exclude_patterns=[str(item) for item in (exclude_patterns or [])],
        history_limit=history_limit,
        max_details=int(source.get("max_details", 30)),
        api_id_env=api_id_env,
        api_hash_env=api_hash_env,
        session_env=session_env,
    )


def _vk_wall_collector(source: dict[str, Any]) -> VkWallCollector:
    listing_urls = source.get("listing_urls")
    if not isinstance(listing_urls, list) or not listing_urls:
        raise SourceScanError(f"VK source {source.get('id')} has no listing_urls")
    include_patterns = source.get("include_patterns")
    if include_patterns is not None and not isinstance(include_patterns, list):
        raise SourceScanError(f"VK source {source.get('id')} has invalid include_patterns")
    exclude_patterns = source.get("exclude_patterns")
    if exclude_patterns is not None and not isinstance(exclude_patterns, list):
        raise SourceScanError(f"VK source {source.get('id')} has invalid exclude_patterns")
    access_token_env = str(source.get("access_token_env") or "VK_ACCESS_TOKEN")
    api_version = str(source.get("api_version") or "5.199")
    return VkWallCollector(
        [str(url) for url in listing_urls],
        include_patterns=[str(item) for item in (include_patterns or [])],
        exclude_patterns=[str(item) for item in (exclude_patterns or [])],
        access_token_env=access_token_env,
        api_version=api_version,
        max_details=int(source.get("max_details", 30)),
    )


SOURCE_BUILDERS: dict[str, Any] = {
    "workspace": _workspace_collector,
    "freelance_task": _freelance_task_collector,
    "rss_feed": _rss_feed_collector,
    "telegram_public": _telegram_public_collector,
    "telegram_client": _telegram_client_collector,
    "vk_wall": _vk_wall_collector,
}


def collect_sources(
    sources: list[dict[str, Any]],
    *,
    max_results: int = 30,
    collector_factory: Any | None = None,
) -> tuple[list[Lead], list[str]]:
    collected: list[Lead] = []
    warnings: list[str] = []
    for source in sources:
        source_type = str(source.get("type", ""))
        builder = SOURCE_BUILDERS.get(source_type)
        if builder is None and collector_factory is None:
            warnings.append(f"Unsupported source type: {source_type}")
            continue
        try:
            if collector_factory:
                collector = collector_factory(source)
            else:
                collector = builder(source)
            remaining = max(0, max_results - len(collected))
            if not remaining:
                break
            collected.extend(collector.collect(max_results=remaining))
            warnings.extend(getattr(collector, "warnings", []))
        except (
            SourceScanError,
            FreelanceTaskCollectorError,
            RSSFeedCollectorError,
            TelegramClientCollectorError,
            TelegramPublicCollectorError,
            VkWallCollectorError,
            WorkspaceCollectorError,
            ValueError,
        ) as exc:
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
