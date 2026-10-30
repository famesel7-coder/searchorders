"""HH official API integration: no private contact guessing or fake dates."""
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from realtime_service import hh_sources as hh
from realtime_service.direct_contacts import is_direct_lead


class HHSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.vacancy = {
            "id": "123456789",
            "alternate_url": "https://hh.ru/vacancy/123456789",
            "name": "Дизайнер презентаций на проект",
            "description": "<p>Нужен дизайнер для разовой задачи: оформить 40 слайдов презентации. "
                           "Работа по договору ГПХ. Оплата за проект, старт на следующей неделе.</p>",
            "published_at": self.now.isoformat(),
            "archived": False,
            "employer": {"name": "Тестовый заказчик"},
            "employment_form": {"id": "PROJECT", "name": "Проектная работа"},
            "contacts": {"email": "design@client.example", "phones": []},
        }

    def test_email_comes_from_the_vacancy_not_employer_or_footer(self):
        row = hh.convert(self.vacancy, self.now)
        self.assertIsNotNone(row)
        self.assertEqual(row["contact"], "design@client.example")
        self.assertEqual(row["category"], "presentations")
        self.assertEqual(row["channel"], "hh-direct")
        self.assertEqual(row["url"], self.vacancy["alternate_url"])
        self.assertTrue(is_direct_lead(row))
        self.assertEqual(row["budget"], "")

    def test_only_phone_from_explicit_contacts_is_allowed(self):
        v = dict(self.vacancy, contacts={
            "email": None, "phones": [{"country": "7", "city": "921", "number": "1234567"}]})
        row = hh.convert(v, self.now)
        self.assertEqual(row["contact"], "+79211234567")
        self.assertTrue(is_direct_lead(row))
        self.assertFalse(is_direct_lead({**row, "url": "https://example.org/vacancy/123456789"}))

    def test_no_contact_is_excluded(self):
        v = dict(self.vacancy, contacts=None)
        self.assertIsNone(hh.convert(v, self.now))
        v["description"] += " info@company.example "
        self.assertIsNone(hh.convert(v, self.now))

    def test_explicit_application_email_in_description(self):
        v = dict(self.vacancy, contacts=None)
        v["description"] += " Присылайте портфолио на design@client.example"
        self.assertEqual(hh.convert(v, self.now)["contact"], "design@client.example")

    def test_full_time_not_project_fresh_only(self):
        v = dict(self.vacancy, name="Графический дизайнер в штат", employment_form={
            "id": "FULL", "name": "Полная занятость"
        })
        self.assertIsNone(hh.convert(v, self.now))
        v = dict(self.vacancy, published_at=(self.now - timedelta(days=5)).isoformat())
        self.assertIsNone(hh.convert(v, self.now))
        v = dict(self.vacancy, archived=True)
        self.assertIsNone(hh.convert(v, self.now))

    def test_no_anonymous_or_invalid_primary_source(self):
        v = dict(self.vacancy, employer={"name": ""})
        self.assertIsNone(hh.convert(v, self.now))
        v = dict(self.vacancy, alternate_url="https://evil.example/vacancy/123456789")
        self.assertIsNone(hh.convert(v, self.now))
        v = dict(self.vacancy, alternate_url="https://hh.ru/vacancy/444444444")
        self.assertIsNone(hh.convert(v, self.now))

    def test_scan_stops_on_403_without_fabricating_leads(self):
        with patch.object(hh, "request_json", side_effect=PermissionError("HH API: 403")) as request:
            checked, rows, errors = hh.scan()
        self.assertEqual(checked, 0)
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["HH API: 403"])
        self.assertEqual(request.call_count, 1)

    def test_scan_uses_official_api_and_deduplicates(self):
        def fake_request(path, params=None):
            if path == hh.API:
                return {"items": [{"id": "123456789"}, {"id": "123456789"}]}
            if path == hh.API + "/123456789":
                return self.vacancy
            raise AssertionError(path)
        with patch.object(hh, "request_json", side_effect=fake_request):
            checked, rows, errors = hh.scan()
        self.assertEqual(checked, 8)  # four terms x two search results
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [])

    def test_http_403_is_not_bypassed(self):
        class Response:
            status_code = 403
        with patch.object(hh.requests, "get", return_value=Response()) as get:
            with self.assertRaises(PermissionError):
                hh.request_json(hh.API)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertEqual(get.call_count, 1)

    def test_source_is_registered_for_monitoring(self):
        self.assertEqual(hh.SOURCES[0]["id"], "hh-direct")
        self.assertIn("hh-direct", hh.FETCHERS)

    def test_existing_outreach_records_without_contacts_do_not_crash_scan(self):
        import tempfile
        from unittest.mock import patch
        from realtime_service import engine
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            (root / "data" / "outreach_status.json").write_text(
                '{"contacted":[{"contact":null},{"contact":"hello@client.example"},{"unexpected":1}]}')
            with patch.object(engine, "ROOT", root):
                self.assertEqual(engine.contacted(), {"hello@client.example"})


if __name__ == "__main__":
    unittest.main()
