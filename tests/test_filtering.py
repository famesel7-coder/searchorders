from __future__ import annotations

import unittest

from searchorders.config import load_search_profile
from searchorders.filtering import classify_lead
from searchorders.models import Lead


class FilteringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_search_profile("data/search-profile.yaml")

    def test_rejects_full_time_vacancy(self) -> None:
        lead = Lead(
            source="test",
            external_id="1",
            title="UX/UI дизайнер в штат",
            description="Ищем в команду на полный рабочий день, оформление по ТК и оклад.",
            employment="Полная занятость",
            schedule="Полный день",
        )
        result = classify_lead(lead, self.profile)
        self.assertTrue(result.hard_reject)
        self.assertEqual(result.decision, "reject")
        self.assertIn("ux-ui", result.service_tags)

    def test_keeps_explicit_temporary_project_for_review(self) -> None:
        lead = Lead(
            source="test",
            external_id="2",
            title="UX/UI проект",
            description="Проектная работа, есть бриф и фиксированный бюджет.",
            employment="Полная занятость",
            accept_temporary=True,
        )
        result = classify_lead(lead, self.profile)
        self.assertFalse(result.hard_reject)
        self.assertEqual(result.decision, "review")

    def test_does_not_reject_negated_staff_phrase(self) -> None:
        lead = Lead(
            source="test",
            external_id="3",
            title="Разработка лендинга",
            description="Не ищем в штат. Нужен подрядчик на разовую задачу с готовым ТЗ.",
        )
        result = classify_lead(lead, self.profile)
        self.assertFalse(result.hard_reject)
        self.assertIn("promo-website", result.service_tags)


if __name__ == "__main__":
    unittest.main()

