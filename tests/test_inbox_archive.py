"""Inbox, replied archive and rescan exclusion acceptance tests."""
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from datetime import datetime, timezone
from realtime_service import app, engine


def seed(db, identity, contact, contacted=0, stage="new", saved=0):
    db.execute("""INSERT INTO leads(id, url, channel, published_at, discovered_at,
        body, category, score, contact, buyer, budget, reason, fingerprint, stage,
        notified, contacted, saved)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (identity,"https://t.me/fake/"+identity, "fake", datetime.now(timezone.utc).isoformat(),
        datetime.now(timezone.utc).isoformat(),"Нужен дизайнер для сайта", "web",82,
        contact,"","","",identity,stage,0,contacted,saved))

class InboxArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.dbpath=self.root/"leads.sqlite3"
        patcher1=patch.object(engine,"RUNTIME",self.root)
        patcher2=patch.object(engine,"DB",self.dbpath)
        patcher3=patch.object(app,"conn",engine.conn)
        for p in (patcher1,patcher2,patcher3):
            p.start();self.addCleanup(p.stop)
        db=engine.conn()
        seed(db,"a"*20,"@contact_a",0)
        seed(db,"b"*20,"@contact_b",1)
        seed(db,"c"*20,"@contact_c",0,"dismissed")
        seed(db,"d"*20,"@contact_d",0)
        # New posting by the same customer must not be shown as a fresh lead.
        seed(db,"e"*20,"@contact_b",0)
        seed(db,"f"*20,"@contact_c",0)
        db.commit();db.close()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),thread.join(timeout=3)))
        self.url="http://127.0.0.1:"+str(self.server.server_port)

    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=5) as reply:
            data=reply.read()
            if path.startswith("/api/"):return json.loads(data)
            return reply.status,data.decode("utf-8")

    def post(self,path,data):
        request=urllib.request.Request(self.url+path,data=json.dumps(data).encode(),
          headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(request,timeout=5) as response:
            return json.load(response)

    def test_archive_page_route_and_main_page_are_available(self):
        for path in ("/", "/contacted", "/contacted/", "/saved", "/hidden"):
            status,body=self.get(path)
            self.assertEqual(status,200,path)
            self.assertIn("pageView",body)
            self.assertIn('href="/contacted"',body)
            self.assertIn("Новый поиск заказов",body)

    def test_main_inbox_excludes_contacted_hidden_and_their_reposts(self):
        main=self.get("/api/leads?stage=not_contacted")["items"]
        self.assertEqual({r["id"] for r in main},{"a"*20,"d"*20})
        sent=self.get("/api/leads?stage=contacted")["items"]
        self.assertEqual({r["id"] for r in sent},{"b"*20})
        hidden=self.get("/api/leads?stage=dismissed")["items"]
        self.assertEqual({r["id"] for r in hidden},{"c"*20})
        status=self.get("/api/status")
        self.assertEqual(status["counts"]["new"],2)
        self.assertEqual(status["counts"]["contacted"],1)

    def test_contacted_action_moves_lead_to_archive_and_back(self):
        id="a"*20
        x=self.post("/api/lead",{"id":id,"field":"contacted","value":True})
        self.assertEqual(x["lead"]["contacted"],1)
        inbox=self.get("/api/leads?stage=not_contacted")["items"]
        self.assertNotIn(id,{l["id"] for l in inbox})
        sent=self.get("/api/leads?stage=contacted")["items"]
        self.assertIn(id,{l["id"] for l in sent})
        x=self.post("/api/lead",{"id":id,"field":"contacted","value":False})
        self.assertEqual(x["lead"]["contacted"],0)
        inbox=self.get("/api/leads?stage=not_contacted")["items"]
        self.assertIn(id,{l["id"] for l in inbox})

    def test_hidden_action_hides_until_explicit_restore(self):
        id="d"*20
        self.post("/api/lead",{"id":id,"field":"hidden","value":True})
        self.assertNotIn(id,{r["id"] for r in self.get("/api/leads?stage=not_contacted")["items"]})
        self.assertIn(id,{r["id"] for r in self.get("/api/leads?stage=dismissed")["items"]})
        self.post("/api/lead",{"id":id,"field":"hidden","value":False})
        self.assertIn(id,{r["id"] for r in self.get("/api/leads?stage=not_contacted")["items"]})

    def test_rescan_never_reintroduces_processed_contact(self):
        def item(identifier,contact):
            return {"id":identifier,"url":"https://t.me/fake/"+identifier,
                    "channel":"fake","published_at":datetime.now(timezone.utc).isoformat(),
                    "discovered_at":datetime.now(timezone.utc).isoformat(),
                    "body":"Нужен дизайнер","category":"web","score":88,
                    "contact":contact,"buyer":"","budget":"","reason":"","fingerprint":identifier}
        candidates=[item("g"*20,"@contact_b"),item("h"*20,"@contact_c"),
                    item("i"*20,"@contact_fresh")]
        with patch.object(engine,"sources",return_value=["https://t.me/s/fake"]), \
             patch.object(engine,"fetch",return_value=(3,candidates)), \
             patch.object(engine,"contacted",return_value=set()):
            result=engine.Monitor().scan()
        self.assertEqual(result["new"],1)
        available=self.get("/api/leads?stage=not_contacted")["items"]
        self.assertIn("i"*20,{r["id"] for r in available})
        self.assertNotIn("g"*20,{r["id"] for r in available})
        self.assertNotIn("h"*20,{r["id"] for r in available})

if __name__=="__main__":unittest.main()
