from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
class ConfigurationError(ValueError):pass
FORBIDDEN_SOURCE_TYPES={"workspace","freelance_task","project_marketplace","marketplace"}; ALLOWED_SOURCE_TYPES={"telegram_public","telegram_client","vk_wall","rss_feed"}
def load_yaml(path:str|Path)->dict[str,Any]:
    resolved=Path(path)
    if not resolved.exists():raise ConfigurationError(f"Configuration file does not exist: {resolved}")
    with resolved.open("r",encoding="utf-8") as handle:data=yaml.safe_load(handle) or {}
    if not isinstance(data,dict):raise ConfigurationError(f"Expected a mapping in {resolved}")
    return data
def load_search_profile(path:str|Path)->dict[str,Any]:
    profile=load_yaml(path); missing=[k for k in ("services","lead_filters","scoring","proposal") if k not in profile]
    if missing:raise ConfigurationError(f"Search profile is missing required sections: {', '.join(missing)}")
    return profile
def load_cases(path:str|Path)->list[dict[str,Any]]:
    cases=load_yaml(path).get("cases")
    if not isinstance(cases,list):raise ConfigurationError("Case catalog must contain a 'cases' list")
    return [c for c in cases if isinstance(c,dict)]
def load_sources(path:str|Path)->list[dict[str,Any]]:
    sources=load_yaml(path).get("sources")
    if not isinstance(sources,list):raise ConfigurationError("Source catalog must contain a 'sources' list")
    enabled=[]; seen=set()
    for source in sources:
        if not isinstance(source,dict) or not source.get("enabled",False):continue
        sid=str(source.get("id") or "").strip(); typ=str(source.get("type") or "").strip()
        if not sid or not typ:raise ConfigurationError("Every enabled source needs 'id' and 'type'")
        if sid in seen:raise ConfigurationError(f"Duplicate source id: {sid}")
        seen.add(sid)
        if typ in FORBIDDEN_SOURCE_TYPES:raise ConfigurationError(f"Source type '{typ}' is forbidden: SearchOrders is social/community-only")
        if typ not in ALLOWED_SOURCE_TYPES:raise ConfigurationError(f"Unsupported source type: {typ}")
        urls=source.get("listing_urls")
        if not isinstance(urls,list) or not urls:raise ConfigurationError(f"Enabled source {sid} needs listing_urls")
        enabled.append(source)
    return enabled
