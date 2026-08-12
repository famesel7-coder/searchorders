from __future__ import annotations

import unittest

from searchorders.collectors.hh import HHCollector


class HHCollectorTests(unittest.TestCase):
    def test_maps_hh_payload_to_lead(self) -> None:
        payload = {
            "id": "123",
            "name": "Проектный UX/UI дизайнер",
            "description": "<p>Разовая <b>проектная работа</b> в Figma</p>",
            "alternate_url": "https://hh.ru/vacancy/123",
            "published_at": "2026-08-12T10:00:00+0300",
            "accept_temporary": True,
            "employer": {"name": "Example", "alternate_url": "https://hh.ru/employer/1"},
            "employment": {"id": "project", "name": "Проектная работа"},
            "schedule": {"id": "remote", "name": "Удаленная работа"},
            "area": {"id": "1", "name": "Москва"},
            "salary": {"from": 150000, "to": 250000, "currency": "RUR"},
            "key_skills": [{"name": "Figma"}, {"name": "UX"}],
        }
        lead = HHCollector._lead_from_payload(payload)
        self.assertEqual(lead.external_id, "123")
        self.assertEqual(lead.company_name, "Example")
        self.assertTrue(lead.accept_temporary)
        self.assertIn("Разовая проектная работа", lead.description)
        self.assertIn("Figma", lead.description)


if __name__ == "__main__":
    unittest.main()

