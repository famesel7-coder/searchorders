from __future__ import annotations
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any
from .catalog import CatalogStore
from .collectors import RSSFeedCollector,RSSFeedCollectorError,TelegramClientCollector,TelegramClientCollectorError,TelegramPublicCollector,TelegramPublicCollectorError,VkWallCollector,VkWallCollectorError
from .dedupe import group_duplicate_leads
from .models import Lead,LeadEvaluation
from .normalization import enrich_lead
from .pipeline import evaluate_lead
class SourceScanError(RuntimeError):pass
@dataclass(slots=True)
class SourceMetric:source_id:str; collected:int=0; error:str|None=None
@dataclass(slots=True)
class ScanResult:
    collected_count:int; new_count:int; evaluations:list[LeadEvaluation]=field(default_factory=list); warnings:list[str]=field(default_factory=list); new_post_count:int=0; source_metrics:list[SourceMetric]=field(default_factory=list); run_id:int|None=None
def _patterns(source:dict[str,Any],key:str)->list[str]:
    value=source.get(key)
    if value is None:return []
    if not isinstance(value,list):raise SourceScanError(f"Source {source.get('id')} has invalid {key}")
    return [str(x) for x in value]
def _listing_urls(source:dict[str,Any])->list[str]:
    value=source.get("listing_urls")
    if not isinstance(value,list) or not value:raise SourceScanError(f"Source {source.get('id')} has no listing_urls")
    return [str(x) for x in value]
def _rss_feed_collector(source:dict[str,Any])->RSSFeedCollector:return RSSFeedCollector(_listing_urls(source),include_patterns=_patterns(source,"include_patterns"),exclude_patterns=_patterns(source,"exclude_patterns"),area=str(source.get("area") or "Internet"),employment=str(source.get("employment") or "Публичная community-лента"),max_details=int(source.get("max_details",50)))
def _telegram_public_collector(source:dict[str,Any])->TelegramPublicCollector:return TelegramPublicCollector(_listing_urls(source),include_patterns=_patterns(source,"include_patterns"),exclude_patterns=_patterns(source,"exclude_patterns"),max_details=int(source.get("max_details",50)),request_delay_seconds=float(source.get("request_delay_seconds",.3)),source_id=str(source.get("id") or "telegram-public"),source_name=str(source.get("name") or "") or None)
def _telegram_client_collector(source:dict[str,Any])->TelegramClientCollector:return TelegramClientCollector(_listing_urls(source),include_patterns=_patterns(source,"include_patterns"),exclude_patterns=_patterns(source,"exclude_patterns"),history_limit=int(source.get("history_limit",200)),max_details=int(source.get("max_details",50)),api_id_env=str(source.get("api_id_env") or "TELEGRAM_API_ID"),api_hash_env=str(source.get("api_hash_env") or "TELEGRAM_API_HASH"),session_env=str(source.get("session_env") or "TELEGRAM_SESSION"),source_id=str(source.get("id") or "telegram-client"),source_name=str(source.get("name") or "") or None)
def _vk_wall_collector(source:dict[str,Any])->VkWallCollector:return VkWallCollector(_listing_urls(source),include_patterns=_patterns(source,"include_patterns"),exclude_patterns=_patterns(source,"exclude_patterns"),access_token_env=str(source.get("access_token_env") or "VK_ACCESS_TOKEN"),api_version=str(source.get("api_version") or "5.199"),max_details=int(source.get("max_details",50)),source_id=str(source.get("id") or "vk-wall"),source_name=str(source.get("name") or "") or None)
SOURCE_BUILDERS={"rss_feed":_rss_feed_collector,"telegram_public":_telegram_public_collector,"telegram_client":_telegram_client_collector,"vk_wall":_vk_wall_collector}; SOURCE_ERRORS=(SourceScanError,RSSFeedCollectorError,TelegramClientCollectorError,TelegramPublicCollectorError,VkWallCollectorError,ValueError)
def collect_sources(sources:list[dict[str,Any]],*,max_results:int=30,collector_factory:Any|None=None)->tuple[list[Lead],list[str]]:
    leads,warnings,_=_collect_source_batches(sources,max_results=max_results,collector_factory=collector_factory); return leads,warnings
def _collect_source_batches(sources:list[dict[str,Any]],*,max_results:int,collector_factory:Any|None=None)->tuple[list[Lead],list[str],list[SourceMetric]]:
    collected=[]; warnings=[]; metrics=[]
    for source in sources:
        sid=str(source.get("id") or source.get("type") or "unknown"); typ=str(source.get("type") or ""); builder=SOURCE_BUILDERS.get(typ)
        if builder is None and collector_factory is None:msg=f"Unsupported or forbidden source type: {typ}"; warnings.append(f"{sid}: {msg}"); metrics.append(SourceMetric(sid,error=msg)); continue
        try:
            collector=collector_factory(source) if collector_factory else builder(source); limit=max(1,int(source.get("max_details",max_results))); batch=[enrich_lead(x) for x in collector.collect(max_results=limit)]; collected.extend(batch); warnings.extend(f"{sid}: {x}" for x in getattr(collector,"warnings",[])); metrics.append(SourceMetric(sid,collected=len(batch)))
        except SOURCE_ERRORS as exc:warnings.append(f"{sid}: {exc}"); metrics.append(SourceMetric(sid,error=str(exc)))
    exact={}
    for lead in collected:exact.setdefault((lead.source_id or lead.source,lead.source,lead.external_id),lead)
    return list(exact.values()),warnings,metrics
def scan_sources(profile:dict[str,Any],cases:list[dict[str,Any]],sources:list[dict[str,Any]],*,state_path:str|Path,max_results:int=30,collector_factory:Any|None=None)->ScanResult:
    store=CatalogStore(state_path); run_id=store.begin_run(); collected=[]; warnings=[]
    try:
        for source in sources:store.register_source(source)
        collected,warnings,metrics=_collect_source_batches(sources,max_results=max_results,collector_factory=collector_factory); mm={m.source_id:m for m in metrics}
        for source in sources:
            sid=str(source.get("id") or source.get("type") or "unknown"); m=mm.get(sid) or SourceMetric(sid); store.record_source_result(sid,posts_seen=m.collected,error=m.error)
        new_posts=[]
        for lead in collected:
            pid,is_new=store.upsert_post(lead,run_id)
            if is_new:new_posts.append((lead,pid))
        ids={(lead.source_id or lead.source,lead.external_id):pid for lead,pid in new_posts}; evaluations=[]; new_count=0; by_source={}
        for group in group_duplicate_leads([lead for lead,_ in new_posts]):
            ev=evaluate_lead(group.canonical,profile,cases); pids=[ids[(m.source_id or m.source,m.external_id)] for m in group.members]; catalog_id,created=store.save_group(group,ev,pids); ev.catalog_id=catalog_id
            if created:
                evaluations.append(ev); new_count+=1
                for m in group.members:
                    sid=m.source_id or m.source; by_source[sid]=by_source.get(sid,0)+1
        for sid,count in by_source.items():store.record_source_result(sid,posts_seen=0,leads_found=count)
        order={"hot":0,"review":1,"archive":2,"rejected":3}; evaluations.sort(key=lambda x:(order.get(x.score.bucket,9),-x.score.total)); visible=evaluations[:max(1,max_results)]; store.finish_run(run_id,status="success",collected_count=len(collected),new_post_count=len(new_posts),new_lead_count=new_count,warnings=warnings); return ScanResult(len(collected),new_count,visible,warnings,len(new_posts),metrics,run_id)
    except Exception as exc:
        warnings.append(f"scan failed: {exc}"); store.finish_run(run_id,status="error",collected_count=len(collected),new_post_count=0,new_lead_count=0,warnings=warnings); raise
