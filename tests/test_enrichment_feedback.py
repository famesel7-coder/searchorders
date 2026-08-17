from __future__ import annotations
import json,os,tempfile,unittest
from pathlib import Path
from searchorders.catalog import CatalogStore
from searchorders.models import Classification,Lead
from searchorders.normalization import enrich_lead
from searchorders.semantic import refine_with_semantics
class EnrichmentFeedbackTests(unittest.TestCase):
    def test_extracts_budget_deadline_company_and_contact(self):
        lead=enrich_lead(Lead(source="telegram_public",external_id="1",title="Нужен UX/UI",description="Компания: Acme Labs\nБюджет: 120-150 тыс руб\nСрок: до конца месяца\nКонтакт: @acme_pm"))
        self.assertEqual(lead.company_name,"Acme Labs");self.assertEqual(lead.budget_from,120000);self.assertEqual(lead.budget_to,150000);self.assertEqual(lead.currency,"RUB");self.assertEqual(lead.deadline_text,"до конца месяца");self.assertIn("@acme_pm",lead.contacts)
    def test_status_is_persisted_with_feedback_stats(self):
        with tempfile.TemporaryDirectory() as td:
            store=CatalogStore(Path(td)/"db.sqlite")
            with store._connect() as db,db:
                lead_id=int(db.execute("INSERT INTO leads(canonical_hash,title,description,contacts_json,status,classification_json,evaluation_json,first_seen_at,last_seen_at) VALUES('x','t','d','[]','new','{}','{}','2026','2026')").lastrowid)
            store.set_status(lead_id,"contacted");self.assertEqual(store.feedback_stats().get("contacted"),1)
    def test_semantic_refinement_is_structured_and_optional(self):
        old_enabled=os.environ.get("OPENAI_CLASSIFIER_ENABLED");old_model=os.environ.get("OPENAI_CLASSIFIER_MODEL")
        os.environ["OPENAI_CLASSIFIER_ENABLED"]="1";os.environ["OPENAI_CLASSIFIER_MODEL"]="test-model"
        try:
            base=Classification(False,"review",intent="ambiguous",confidence=.4,service_tags=["ux-ui"]);lead=Lead(source="telegram_public",external_id="2",title="Нужен специалист",description="Нужно переделать продуктовый сайт")
            result={"intent":"project_demand","confidence":.93,"service_tags":["ux-ui","product-website"],"industry_tags":[],"company_name":"Example Co","deadline_text":"две недели","reason":"buyer asks for a finite website project"}
            fake=lambda payload:{"output":[{"content":[{"type":"output_text","text":json.dumps(result)}]}]}
            refined_lead,refined=refine_with_semantics(lead,base,fetcher=fake);self.assertEqual(refined.intent,"project_demand");self.assertEqual(refined.decision,"eligible");self.assertEqual(refined_lead.company_name,"Example Co");self.assertEqual(refined_lead.deadline_text,"две недели")
        finally:
            if old_enabled is None:os.environ.pop("OPENAI_CLASSIFIER_ENABLED",None)
            else:os.environ["OPENAI_CLASSIFIER_ENABLED"]=old_enabled
            if old_model is None:os.environ.pop("OPENAI_CLASSIFIER_MODEL",None)
            else:os.environ["OPENAI_CLASSIFIER_MODEL"]=old_model
if __name__=="__main__":unittest.main()
