from __future__ import annotations

import unittest

from searchorders.config import load_cases, load_search_profile
from searchorders.models import Lead
from searchorders.pipeline import evaluate_lead
from searchorders.scan import ScanResult
from searchorders.telegram_bot import SearchOrdersBot


class _FakeAPI:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.messages: list[tuple[object, str, object]] = []

    def answer_callback_query(self, callback_query_id: str, **kwargs: object) -> None:
        self.events.append("answer")

    def send_message(self, chat_id: object, text: str, *, reply_markup: object = None) -> None:
        self.events.append("send")
        self.messages.append((chat_id, text, reply_markup))


class TelegramBotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        profile = load_search_profile("data/search-profile.yaml")
        cases = load_cases("data/cases.yaml")
        cls.evaluation = evaluate_lead(
            Lead(
                source="workspace",
                external_id="18857",
                title="Редизайн корпоративного сайта",
                description="Проектная работа: UX/UI, дизайн сайта, готовый бриф и бюджет проекта.",
                url="https://workspace.ru/tenders/example-18857/",
                accept_temporary=True,
                salary_from=500000,
                currency="RUR",
                has_direct_contact=True,
            ),
            profile,
            cases,
        )

    def test_callback_is_answered_before_scan(self) -> None:
        events: list[str] = []
        api = _FakeAPI(events)

        def scan() -> ScanResult:
            events.append("scan")
            return ScanResult(1, 1, [self.evaluation])

        bot = SearchOrdersBot(api, scan, allowed_chat_id="123")
        bot.handle_update(
            {
                "callback_query": {
                    "id": "callback-1",
                    "data": "run_search",
                    "message": {"chat": {"id": 123}},
                }
            }
        )
        self.assertLess(events.index("answer"), events.index("scan"))
        self.assertTrue(any("Поиск завершён" in message[1] for message in api.messages))

    def test_unauthorized_chat_cannot_start_scan(self) -> None:
        events: list[str] = []
        api = _FakeAPI(events)
        bot = SearchOrdersBot(
            api,
            lambda: self.fail("scan must not run"),
            allowed_chat_id="123",
        )
        bot.handle_update(
            {
                "callback_query": {
                    "id": "callback-2",
                    "data": "run_search",
                    "message": {"chat": {"id": 999}},
                }
            }
        )
        self.assertEqual(events, ["answer"])


if __name__ == "__main__":
    unittest.main()

