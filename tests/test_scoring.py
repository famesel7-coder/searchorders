from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scoring import score_lead  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
