"""Keep Telegram and other sources distinct, without claiming Telegram is verified."""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from realtime_service import app, engine
from realtime_service.direct_contacts import source_group, is_telegram_lead, is_direct_lead


class SourceSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.root=root
        self.patches=[
            patch.object(engine,"RUNTIME",root),
            patch.object(engine,"DB",root/"leads.sqlite3"),
            patch.object(app,"conn",engine.conn),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        db=engine.conn()
        now=datetime.now(timezone.utc).isoformat()
        for ident,channel,url,contact,reason in [
            ("a"*20,"zakaz_design","https://t.me/zakaz_design/80001",
             "@designerbuyer123","Контакт опубликован в Telegram; дата поста канала"),
            ("b"*20,"flru-free","https://www.fl.ru/projects/5527271/razrabotat-dizayn.html",
             "https://www.fl.ru/projects/5527271/razrabotat-dizayn.html",
             "FL.ru: объявление прямо помечено «для всех»."),
            ("c"*20,"manual-email","https://sample.example/job/123",
             "hello@example.net","Прямой email из объявления"),
        ]:
            db.execute("""INSERT INTO leads
                (id,url,channel,published_at,discovered_at,body,category,
                 score,contact,buyer,budget,reason,fingerprint)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ident,url,channel,now,now,
                 "Ищем дизайнера на проектную работу по разработке сайта Tilda с адаптивной вёрсткой.",
                 "web",85,contact,"Заказчик","",reason,ident))
        db.commit()
        db.close()
        server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=3)))
        self.base=f"http://127.0.0.1:{server.server_port}"

    def get(self,path):
        with urllib.request.urlopen(self.base+path,timeout=5) as response:
            body=response.read()
            return json.loads(body) if path.startswith("/api/") else body.decode()

    def test_two_lanes_have_separate_leads(self):
        telegram=self.get("/api/leads?stage=not_contacted&source=telegram")["items"]
        other=self.get("/api/leads?stage=not_contacted&source=other")["items"]
        self.assertEqual([x["id"] for x in telegram],["a"*20])
        self.assertEqual({x["id"] for x in other},{"b"*20,"c"*20})
        all_rows=self.get("/api/leads?stage=not_contacted")["items"]
        self.assertEqual(len(all_rows),3)
        status=self.get("/api/status")
        self.assertEqual(status["counts"]["telegram_new"],1)
        self.assertEqual(status["counts"]["other_new"],2)
        self.assertEqual(status["counts"]["free_new"],1)
        self.assertEqual(status["counts"]["email_new"],1)

    def test_telegram_warning_and_contacts_are_not_confused(self):
        telegram=self.get("/api/leads?stage=not_contacted&source=telegram")["items"][0]
        self.assertTrue(is_telegram_lead(telegram))
        self.assertFalse(is_direct_lead(telegram))
        self.assertEqual(source_group(telegram),"telegram")
        self.assertFalse(is_telegram_lead({**telegram,"url":"https://t.me/otherchannel/80001"}))
        self.assertFalse(is_telegram_lead({**telegram,"contact":"@ab"}))
        self.assertFalse(is_telegram_lead({**telegram,"reason":"Контакт подтверждён"}))
        self.assertEqual(source_group({**telegram,"reason":"Контакт подтверждён"}),None)

    def test_fl_for_all_is_on_other_tab_not_email(self):
        fl=self.get("/api/leads?stage=not_contacted&source=other")["items"]
        fl=next(x for x in fl if x["channel"]=="flru-free")
        self.assertEqual(source_group(fl),"other")
        self.assertTrue(is_direct_lead(fl))
        self.assertFalse(is_direct_lead({**fl,"reason":"Отклик за плату"}))
        self.assertNotIn(fl["id"],[r["id"] for r in self.get("/api/leads?stage=not_contacted&email_only=1")["items"]])

    def test_fl_changed_slug_keeps_single_lead_and_shared_contacted(self):
        db=engine.conn()
        source=dict(db.execute("SELECT * FROM leads WHERE id=?",("b"*20,)).fetchone())
        source["id"]="d"*20
        source["url"]="https://www.fl.ru/projects/5527271/new-design-title.html"
        source["contact"]=source["url"]
        source["fingerprint"]="d"*20
        cols=",".join(source)
        params=",".join("?" for _ in source)
        db.execute(f"INSERT INTO leads ({cols}) VALUES ({params})",tuple(source.values()))
        db.commit();db.close()
        rows=self.get("/api/leads?stage=not_contacted&source=other")["items"]
        self.assertEqual(len(rows),2)
        self.assertEqual(self.get("/api/status")["counts"]["other_new"],2)
        req=urllib.request.Request(self.base+"/api/lead",
            data=json.dumps({"id":"b"*20,"field":"contacted","value":True}).encode(),
            method="POST",headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=5) as response:
            self.assertTrue(json.load(response)["ok"])
        rows=self.get("/api/leads?stage=not_contacted&source=other")["items"]
        self.assertEqual([r["channel"] for r in rows],["manual-email"])
        self.assertEqual(self.get("/api/status")["counts"]["other_new"],1)
        db=engine.conn()
        self.assertEqual(db.execute(
            "SELECT SUM(contacted) FROM leads WHERE channel='flru-free'").fetchone()[0],2)
        db.close()

    def test_source_switch_visible_and_manual_sending_only(self):
        html=self.get("/")
        self.assertIn('id="sourceSwitch"',html)
        self.assertIn("switchSource('telegram')",html)
        self.assertIn("switchSource('other')",html)
        self.assertIn("Telegram: контакты взяты из публичных постов.",html)
        self.assertIn("FL.ru · для всех",html)
        self.assertIn("isOnSite(lead)?input.value",html)
        self.assertNotIn("sendMessage(",html)


if __name__=="__main__":
    unittest.main()
