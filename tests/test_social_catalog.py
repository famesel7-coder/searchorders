from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from searchorders.catalog import CatalogStore
from searchorders.dedupe import group_duplicate_leads
from searchorders.filtering import classify_lead
from searchorders.models import Lead
from searchorders.normalization import enrich_lead
from searchorders.scan import scan_sources
PROFILE={"services":{"priority":["ux-ui","promo-website","corporate-website","brand-identity"],"secondary":[]},"lead_filters":{"hard_reject_signals":["штат","полная занятость"],"positive_project_signals":["проект","подряд"],"demand_signals":["ищем дизайнера","нужен дизайнер"]},"scoring":{"service_fit":30,"commercial_fit":20,"project_probability":15,"case_match":10,"client_quality":10,"freshness_urgency":10,"contactability":5,"thresholds":{"hot":75,"review":55}},"proposal":{"site_url":"https://imon.agency/"}}
class SocialCatalogTests(unittest.TestCase):
    def test_telegram_does_not_imply_project(self):
        r=classify_lead(Lead(source="telegram_public",source_id="tg",external_id="1",title="UX/UI дизайнер в штат",description="Ищем дизайнера в команду, полная занятость, 5/2."),PROFILE); self.assertTrue(r.hard_reject); self.assertEqual(r.intent,"employment")
    def test_self_promo_is_not_demand(self):
        r=classify_lead(Lead(source="telegram_public",external_id="2",title="UX/UI дизайнер",description="Я дизайнер, открыта для новых проектов. Моё портфолио по ссылке."),PROFILE); self.assertTrue(r.hard_reject); self.assertEqual(r.intent,"self_promo")
    def test_cross_source_repost_dedupe(self):
        a=enrich_lead(Lead(source="telegram_public",source_id="a",external_id="1",title="Нужен дизайнер",description="Нужен UX/UI дизайнер на проект. Бюджет 120 тыс руб. @client_name")); b=enrich_lead(Lead(source="telegram_public",source_id="b",external_id="9",title="Ищем дизайнера",description="Нужен UX/UI дизайнер на проект. Бюджет 120 тыс руб. @client_name")); groups=group_duplicate_leads([a,b]); self.assertEqual(len(groups),1); self.assertEqual(len(groups[0].members),2)
    def test_all_sources_run_before_output_limit(self):
        sources=[{"id":"first","type":"telegram_public","listing_urls":["@a"],"max_details":1},{"id":"second","type":"telegram_public","listing_urls":["@b"],"max_details":1}]
        class Collector:
            warnings=[]
            def __init__(self,source):self.source=source
            def collect(self,*,max_results):
                sid=self.source["id"]; return [Lead(source="telegram_public",source_id=sid,source_name=sid,external_id="1",title=f"Нужен UX/UI дизайнер на проект {sid}",description=f"Ищем дизайнера на проект для лендинга. Бюджет 150 тыс руб. Контакт @{sid}_client")]
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"catalog.db"; factory=lambda source:Collector(source); first=scan_sources(PROFILE,[],sources,state_path=db,max_results=1,collector_factory=factory); self.assertEqual(first.collected_count,2); self.assertEqual(first.new_post_count,2); self.assertEqual(CatalogStore(db).catalog_payload()["summary"]["total"],2); second=scan_sources(PROFILE,[],sources,state_path=db,max_results=1,collector_factory=factory); self.assertEqual(second.new_post_count,0); self.assertEqual(second.new_count,0)
if __name__=="__main__":unittest.main()
