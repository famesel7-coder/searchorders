"""Email-only lead selection, accurate draft fields, safe send workflow."""
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from lxml import html
from realtime_service import app, engine
from realtime_service.outreach import create_draft, subject_for_brief, analyse_brief

class EmailWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"leads.sqlite3"
        self.patchers=[patch.object(engine,"RUNTIME",self.root),patch.object(engine,"DB",self.db),
                       patch.object(app,"conn",engine.conn),patch.object(app,"CONFIG",self.root/"settings.json")]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
        conn=engine.conn()
        now=datetime.now(timezone.utc).isoformat()
        for leadid,contact,stage,contacted in [
         ("a"*20,"@telegram_person","new",0),
         ("b"*20,"designer.hiring@example.org","new",0),
         ("c"*20,"applied@company.example","new",1),
         ("d"*20,"hidden@company.example","dismissed",0)]:
            conn.execute("""INSERT INTO leads(id,url,channel,published_at,discovered_at,body,category,score,contact,
                buyer,budget,reason,fingerprint,stage,contacted,saved)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (leadid,("https://t.me/s/fictional/"+leadid if contact.startswith("@") else "https://example.org/open-request/"+leadid),
                ("unit" if contact.startswith("@") else "manual-email"),now,now,
                "Ищем дизайнера для лендинга на Tilda, 6–9 блоков, проектная работа",
                "web",85,contact,"","","",leadid,stage,contacted,0))
        conn.commit();conn.close()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),thread.join(timeout=3)))
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def get(self,path):
        with urllib.request.urlopen(self.base+path,timeout=5) as r:
            data=r.read()
            return json.loads(data) if path.startswith("/api/") else data.decode()

    def post(self,path,data):
        request=urllib.request.Request(self.base+path,data=json.dumps(data).encode(),
          headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(request,timeout=7) as r:return r.status,json.loads(r.read())

    def test_email_only_inbox_ignores_telegram_and_archives(self):
        leads=self.get("/api/leads?stage=not_contacted&email_only=1")["items"]
        self.assertEqual([x["contact"] for x in leads],["designer.hiring@example.org"])
        leads=self.get("/api/leads?stage=without_email")["items"]
        self.assertEqual(leads,[])
        status=self.get("/api/status")
        self.assertEqual(status["counts"]["email_new"],1)
        self.assertEqual(status["counts"]["without_email"],0)

    def test_draft_email_fields_and_no_contacted_side_effect(self):
        status,data=self.post("/api/draft",{"id":"b"*20})
        self.assertEqual(status,200)
        self.assertEqual(data["contact"],"designer.hiring@example.org")
        self.assertEqual(data["from_address"],"cco@imon.agency")
        self.assertIn("Tilda",data["subject"])
        self.assertIn("https://samsel.site",data["draft"])
        after=self.get("/api/leads?stage=not_contacted&email_only=1")["items"]
        self.assertEqual(after[0]["contacted"],0)

    def test_telegram_only_record_cannot_generate_email(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/draft",{"id":"a"*20})
        self.assertEqual(ctx.exception.code,409)

    def test_email_contact_preferred_to_telegram(self):
        node=html.fromstring("<div><a href='mailto:brief@example.net'>Send brief</a> <a href='https://t.me/personname'>Message</a></div>")
        item=engine.classify(
         "Ищем дизайнера для лендинга Tilda. Проектная работа, пишите @personname или email brief@example.net",
         "https://t.me/s/sourced/898",node,"sourced",datetime.now(timezone.utc))
        self.assertIsNotNone(item)
        self.assertEqual(item["contact"],"brief@example.net")

    def test_manual_email_lead_enters_inbox_and_preserves_original(self):
        brief="Ищем дизайнера на разовый проект для создания сайта на Tilda, нужно сверстать семь блоков и мобильную версию."
        status,response=self.post("/api/lead/manual",{
            "buyer":"Тестовая студия","email":"new.client@example.org",
            "url":"https://example.org/open-request/123","brief":brief})
        self.assertEqual(status,200)
        rows=self.get("/api/leads?stage=not_contacted&email_only=1")["items"]
        matches=[r for r in rows if r["contact"]=="new.client@example.org"]
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["url"],"https://example.org/open-request/123")
        self.assertEqual(matches[0]["channel"],"manual-email")
        self.assertIn("время сохранения",matches[0]["reason"])
        status,draft=self.post("/api/draft",{"id":response["id"]})
        self.assertEqual(status,200)
        self.assertIn("samsel.site",draft["draft"])
        with self.assertRaises(urllib.error.HTTPError) as duplicate:
            self.post("/api/lead/manual",{
                "buyer":"","email":"new.client@example.org",
                "url":"https://example.org/open-request/123","brief":brief})
        self.assertEqual(duplicate.exception.code,409)

    def test_manual_submission_rejects_fake_telegram_contact(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post("/api/lead/manual",{
                "email":"@telegram_contact","url":"https://example.org/brief",
                "brief":"Ищем дизайнера для оформления презентации на десять слайдов."})
        self.assertEqual(error.exception.code,400)

    def test_mail_ui_does_not_auto_send_or_fake_from_address(self):
        page=self.get("/")
        self.assertNotIn('href="/without-email"',page)
        self.assertIn('id="emailSubject"',page)
        self.assertIn("mailto:",page)
        self.assertIn("cco@imon.agency",page)
        self.assertNotIn("window.open(url,'_blank')",page)
        self.assertIn("Gmail откроется с заполненными адресатом",page)
        self.assertIn('id="emailFrom"',page)
        self.assertIn("famesel7@gmail.com",page)
        self.assertNotIn('href="/without-email"',page)
        self.assertNotIn('id="channelSwitch"',page)

if __name__=="__main__":
    unittest.main()
