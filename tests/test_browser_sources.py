"""Browser-only external job searches and manual on-platform applications."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from realtime_service import app, engine
from realtime_service.browse_sources import platform_for_url, SEARCHES, PLATFORMS
from realtime_service.direct_contacts import is_direct_lead


BRIEF = ("Ищем дизайнера для проекта: нужно сделать лендинг на Tilda, "
         "адаптивный дизайн, пять экранов, проектная оплата по договору.")


class BrowserSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.patches = [
            patch.object(engine, "RUNTIME", root),
            patch.object(engine, "DB", root / "leads.sqlite3"),
            patch.object(app, "conn", engine.conn),
            patch.object(app, "CONFIG", root / "settings.json"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=3)))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=6) as response:
            body = response.read()
            return json.loads(body) if path.startswith("/api/") else body.decode()

    def post(self, path, value):
        request = urllib.request.Request(self.base + path, data=json.dumps(value).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read())

    def test_only_browser_search_links_no_api(self):
        data = self.get("/api/browse-sources")
        self.assertEqual(len(data["platforms"]), 4)
        self.assertEqual(len(data["searches"]), len(SEARCHES))
        self.assertFalse(data["automatic_collection"])
        self.assertEqual(data["mode"], "manual-browser")
        self.assertEqual({p["name"] for p in data["platforms"]},
                         {"HeadHunter", "FL.ru", "Kwork", "Freelance.ru"})
        self.assertTrue(all(x["url"].startswith("https://") for x in data["searches"]))
        self.assertFalse(any("api.hh.ru" in x["url"] for x in data["searches"]))
        self.assertEqual(self.get("/api/status")["sources"], 3 + len(PLATFORMS))

    def test_exact_vacancy_url_validation(self):
        allowed = [
            "https://hh.ru/vacancy/123456789",
            "https://www.fl.ru/projects/5527271/razrabotat-dizayn/",
            "https://kwork.ru/projects/1234567/view",
            "https://freelance.ru/task/view/11421",
        ]
        rejected = [
            "https://hh.ru/search/vacancy?text=UX",
            "https://hh.ru.evil.example/vacancy/123456789",
            "http://hh.ru/vacancy/123456789",
            "https://hh.ru/vacancy/123456789@example.net",
            "https://www.fl.ru/projects/",
            "https://www.fl.ru/projects/category/dizajn/ui-ux-dizajn/",
            "https://freelance.ru/task",
            "https://kwork.ru/projects",
            "https://workspace.ru/orders/123",
            "https://t.me/s/testchannel/123",
        ]
        for url in allowed:
            with self.subTest(allowed=url):
                self.assertIsNotNone(platform_for_url(url))
        for url in rejected:
            with self.subTest(rejected=url):
                self.assertIsNone(platform_for_url(url))

    def test_add_reply_from_hh_account_and_prepare_text(self):
        url = "https://hh.ru/vacancy/123456789"
        result = self.post("/api/lead/manual", {
            "reply_via": "platform", "url": url, "email": "", "buyer": "Агентство",
            "brief": BRIEF,
        })
        items = self.get("/api/leads?stage=not_contacted")["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["channel"], "manual-platform")
        self.assertEqual(items[0]["contact"], url)
        self.assertTrue(is_direct_lead(items[0]))
        self.assertIn("время сохранения", items[0]["reason"])
        self.assertIn("аккаунт", items[0]["reason"])
        draft = self.post("/api/draft", {"id": result["id"]})
        self.assertTrue(draft["application_mode"])
        self.assertIn("samsel.site", draft["draft"])
        self.assertEqual(draft["contact"], url)
        self.assertFalse(self.get("/api/status")["counts"]["contacted"])
        self.post("/api/lead", {"id":result["id"],"field":"contacted","value":True})
        self.assertEqual(len(self.get("/api/leads?stage=contacted")["items"]), 1)

    def test_manual_fl_platform_is_valid_despite_fl_email_exclusion(self):
        url="https://www.fl.ru/projects/5527271/razrabotat-dizayn/"
        result=self.post("/api/lead/manual", {
            "reply_via":"platform","url":url,"brief":BRIEF})
        self.assertTrue(result["ok"])
        self.assertEqual(self.get("/api/leads?stage=not_contacted")["items"][0]["contact"],url)

    def test_reject_search_home_and_duplicate_without_saving(self):
        for url in ("https://hh.ru/search/vacancy", "https://kwork.ru/projects"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post("/api/lead/manual", {
                    "reply_via":"platform","url":url,"brief":BRIEF})
            self.assertEqual(error.exception.code,400)
        payload={"reply_via":"platform","url":"https://freelance.ru/task/view/11421","brief":BRIEF}
        self.post("/api/lead/manual",payload)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post("/api/lead/manual",payload)
        self.assertEqual(error.exception.code,409)

    def test_no_hh_api_key_in_user_interface_and_manual_mode_present(self):
        page=self.get("/")
        self.assertIn('id="browseSources"',page)
        self.assertIn('id="manualMethod"',page)
        self.assertIn('value="platform"',page)
        self.assertNotIn('id="hhToken"',page)
        self.assertNotIn("api.hh.ru",page)
        self.assertIn("Откликнуться из аккаунта",page)

    def test_outreach_with_no_contact_does_not_break_monitor(self):
        root = Path(self.temp.name)
        (root / "data").mkdir()
        (root / "data" / "outreach_status.json").write_text(
            '{"contacted":[{"contact":null},{"contact":"hello@example.org"},{"unexpected":1}]}')
        with patch.object(engine, "ROOT", root):
            self.assertEqual(engine.contacted(), {"hello@example.org"})


if __name__=="__main__":
    unittest.main()
