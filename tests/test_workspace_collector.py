from __future__ import annotations

import unittest
from pathlib import Path

from searchorders.collectors.workspace import WorkspaceCollector


FIXTURES = Path("tests/fixtures")


class WorkspaceCollectorTests(unittest.TestCase):
    def test_extracts_unique_tender_links(self) -> None:
        html = (FIXTURES / "workspace_listing.html").read_text(encoding="utf-8")
        links = WorkspaceCollector.listing_links(html, "https://workspace.ru/tenders/")
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0].endswith("-18857/"))

    def test_parses_tender_into_lead(self) -> None:
        html = (FIXTURES / "workspace_detail.html").read_text(encoding="utf-8")
        lead = WorkspaceCollector.parse_detail(
            html,
            "https://workspace.ru/tenders/pererabotka-sayta-teatra-18857/",
        )
        self.assertEqual(lead.external_id, "18857")
        self.assertEqual(lead.title, "Переработка сайта театра")
        self.assertEqual(lead.salary_from, 200000)
        self.assertEqual(lead.salary_to, 800000)
        self.assertEqual(lead.currency, "RUR")
        self.assertTrue(lead.accept_temporary)
        self.assertIsNotNone(lead.published_at)

    def test_collects_with_injected_public_pages(self) -> None:
        listing = (FIXTURES / "workspace_listing.html").read_text(encoding="utf-8")
        detail = (FIXTURES / "workspace_detail.html").read_text(encoding="utf-8")

        def fetcher(url: str) -> str:
            return listing if url.endswith("/tenders/") else detail

        collector = WorkspaceCollector(
            ["https://workspace.ru/tenders/"],
            max_details=1,
            request_delay_seconds=0,
            fetcher=fetcher,
        )
        leads = collector.collect()
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].source, "workspace")


if __name__ == "__main__":
    unittest.main()

