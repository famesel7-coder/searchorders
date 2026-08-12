from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from searchorders.cli import _lead_from_dict
from searchorders.config import load_cases, load_search_profile
from searchorders.pipeline import evaluate_lead, evaluate_leads


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_search_profile("data/search-profile.yaml")
        cls.cases = load_cases("data/cases.yaml")
        with open("tests/fixtures/sample_leads.json", encoding="utf-8") as handle:
            cls.leads = [_lead_from_dict(item) for item in json.load(handle)]
        cls.now = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)

    def test_real_estate_project_is_hot_and_matches_orla(self) -> None:
        result = evaluate_lead(self.leads[0], self.profile, self.cases, now=self.now)
        self.assertEqual(result.score.bucket, "hot")
        self.assertGreaterEqual(result.score.total, 75)
        self.assertIsNotNone(result.matched_case)
        self.assertEqual(result.matched_case.case_id, "orla-dorchester")
        self.assertIn("https://imon.agency/", result.proposal_draft or "")
        self.assertIn("ORLA", result.proposal_draft or "")

    def test_staff_vacancy_is_rejected(self) -> None:
        result = evaluate_lead(self.leads[1], self.profile, self.cases, now=self.now)
        self.assertEqual(result.score.bucket, "rejected")
        self.assertEqual(result.score.total, 0)
        self.assertIsNone(result.proposal_draft)

    def test_results_are_sorted_by_bucket_and_score(self) -> None:
        results = evaluate_leads(self.leads, self.profile, self.cases, now=self.now)
        self.assertEqual(results[0].score.bucket, "hot")
        self.assertEqual(results[-1].score.bucket, "rejected")


if __name__ == "__main__":
    unittest.main()
