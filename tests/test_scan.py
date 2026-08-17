from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from searchorders.config import load_cases, load_search_profile
from searchorders.models import Lead
from searchorders.scan import scan_sources


class _FakeCollector:
    warnings: list[str] = []

    def collect(self, *, max_results: int) -> list[Lead]:
        return [
            Lead(
                source="workspace",
                external_id="18857",
                title="Редизайн корпоративного сайта",
                description="Проектный тендер. Нужны UX/UI, дизайн сайта и разработка. Есть бриф и бюджет проекта.",
                url="https://workspace.ru/tenders/example-18857/",
                accept_temporary=True,
                salary_from=500000,
                currency="RUR",
                has_direct_contact=True,
            )
        ][:max_results]


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_search_profile("data/search-profile.yaml")
        cls.cases = load_cases("data/cases.yaml")
        cls.sources = [{"id": "workspace", "type": "workspace", "listing_urls": ["x"]}]

    def test_second_scan_has_no_new_leads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.db"
            factory = lambda source: _FakeCollector()
            first = scan_sources(
                self.profile,
                self.cases,
                self.sources,
                state_path=state,
                collector_factory=factory,
            )
            second = scan_sources(
                self.profile,
                self.cases,
                self.sources,
                state_path=state,
                collector_factory=factory,
            )
            self.assertEqual(first.new_count, 1)
            self.assertEqual(len(first.evaluations), 1)
            self.assertEqual(second.new_count, 0)
            self.assertEqual(second.evaluations, [])


if __name__ == "__main__":
    unittest.main()

