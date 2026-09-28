from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scoring import collaboration_adjustment, score_curated_lead, score_lead  # noqa: E402


CONFIG = {
    "lookback_days": 14,
    "target_markets": ["USA", "GBR", "DEU", "NLD", "CHE"],
    "ted_cpv_codes": ["79822500", "72413000", "79933000", "79415200", "79340000"],
    "ted_strict_cpv_codes": ["79822500", "72413000"],
    "ted_broad_cpv_codes": ["79340000", "79415200", "79933000"],
}


def lead(**overrides):
    base = {
        "source": "TED",
        "title": "",
        "description": "",
        "company": "Buyer",
        "country": "DEU",
        "published_at": date.today().isoformat(),
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "value": None,
        "currency": "EUR",
        "primary_cpv": "",
        "cpv": [],
        "url": "https://example.com/tender",
    }
    base.update(overrides)
    return base


class ScoringTests(unittest.TestCase):
    def test_primary_graphic_design_cpv_qualifies(self):
        result = score_lead(
            lead(
                title="Design-Dienstleistungen für den NDR",
                primary_cpv="79822500",
                cpv=["79822500"],
            ),
            CONFIG,
        )
        self.assertGreaterEqual(result["score"], 55)

    def test_primary_web_design_cpv_qualifies(self):
        result = score_lead(
            lead(
                title="Internet Relaunch",
                primary_cpv="72413000",
                cpv=["72413000"],
            ),
            CONFIG,
        )
        self.assertGreaterEqual(result["score"], 55)
        self.assertIn("web", result["services"])

    def test_secondary_technical_design_codes_do_not_qualify(self):
        result = score_lead(
            lead(
                source="UK Find a Tender",
                title="Mechanical and Electrical Design Consultant Services",
                description="M&E design services for construction and maintenance projects.",
                country="GBR",
                primary_cpv="71320000",
                cpv=["71320000", "79415200", "79933000"],
            ),
            CONFIG,
        )
        self.assertEqual(result["score"], 0)

    def test_backup_solution_with_design_support_code_does_not_qualify(self):
        result = score_lead(
            lead(
                source="UK Find a Tender",
                title="Backup & Recovery Solution",
                description="SaaS enterprise backup and recovery platform.",
                country="GBR",
                primary_cpv="72322000",
                cpv=["72322000", "79933000"],
            ),
            CONFIG,
        )
        self.assertEqual(result["score"], 0)

    def test_broad_marketing_code_alone_does_not_qualify(self):
        result = score_lead(
            lead(
                title="Advertising and marketing services",
                primary_cpv="79340000",
                cpv=["79340000"],
            ),
            CONFIG,
        )
        self.assertEqual(result["score"], 0)

    def test_broad_marketing_code_with_branding_text_can_qualify(self):
        result = score_lead(
            lead(
                title="Brand identity and visual identity refresh",
                primary_cpv="79340000",
                cpv=["79340000"],
            ),
            CONFIG,
        )
        self.assertGreater(result["score"], 0)
        self.assertIn("branding", result["services"])

    def test_dutch_graphic_design_phrase_is_detected(self):
        result = score_lead(
            lead(
                title="Grafische vormgeving",
                primary_cpv="79800000",
                cpv=["79800000", "79822500"],
                country="NLD",
            ),
            CONFIG,
        )
        self.assertGreater(result["score"], 0)
        self.assertIn("creative", result["services"])


    def test_international_remote_is_boosted(self):
        adjustment, reasons = collaboration_adjustment(
            {
                "title": "Freelance designer",
                "evidence": ["Remote. We are open to international candidates."],
            },
            CONFIG,
        )
        self.assertGreater(adjustment, 0)
        self.assertTrue(any("international/global" in reason for reason in reasons))

    def test_local_preference_and_individual_role_are_penalized(self):
        adjustment, reasons = collaboration_adjustment(
            {
                "title": "Freelance designer",
                "evidence": ["Remote contract role."],
                "counter_evidence": [
                    "Есть предпочтение кандидатам из Alberta или British Columbia.",
                    "Вакансия ориентирована на отдельного фрилансера.",
                ],
            },
            CONFIG,
        )
        self.assertLess(adjustment, 0)
        self.assertTrue(any("local candidates preferred" in reason for reason in reasons))
        self.assertTrue(any("individual contractor" in reason for reason in reasons))

    def test_country_only_rule_overrides_remote_bonus(self):
        adjustment, _ = collaboration_adjustment(
            {
                "description": "Fully remote. Applicants must be based in the United States.",
            },
            CONFIG,
        )
        self.assertLess(adjustment, 0)

    def test_curated_lead_is_downgraded_when_access_is_poor(self):
        result = score_curated_lead(
            {
                "confidence": 91,
                "conclusion": "strong",
                "title_ru": "Проектная поддержка по дизайну",
                "evidence": ["Freelance / Contract, Project-Based, Remote."],
                "counter_evidence": [
                    "Есть предпочтение кандидатам из Alberta или British Columbia.",
                    "Формулировка вакансии ориентирована скорее на отдельного фрилансера.",
                ],
            },
            CONFIG,
        )
        self.assertLess(result["fit_score"], 75)
        self.assertEqual(result["conclusion"], "verify_more")
        self.assertEqual(result["base_confidence"], 91)

    def test_curated_international_role_keeps_strong_status(self):
        result = score_curated_lead(
            {
                "confidence": 90,
                "conclusion": "strong",
                "title_ru": "Freelance art direction",
                "evidence": ["Remote. Открыты к международным кандидатам."],
                "counter_evidence": ["Может требоваться личная вовлечённость одного арт-директора."],
            },
            CONFIG,
        )
        self.assertGreaterEqual(result["fit_score"], 75)
        self.assertEqual(result["conclusion"], "strong")


if __name__ == "__main__":
    unittest.main()
