"""Ensure correspondence and bookmarking are two independent persisted flags."""
import sqlite3
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from realtime_service import engine, app

class StatusMigrationTests(unittest.TestCase):
    def test_migrate_existing_contacted_and_saved_without_loss(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            dbfile=root/"leads.sqlite3"
            db=sqlite3.connect(dbfile)
            db.executescript("""
                CREATE TABLE leads(
                  id TEXT PRIMARY KEY,url TEXT UNIQUE,channel TEXT,published_at TEXT,discovered_at TEXT,
                  body TEXT,category TEXT,score INTEGER,contact TEXT,buyer TEXT,budget TEXT,
                  reason TEXT,fingerprint TEXT,stage TEXT DEFAULT 'new',notified INTEGER DEFAULT 0
                );
                INSERT INTO leads(id,stage) VALUES('a','contacted');
                INSERT INTO leads(id,stage) VALUES('b','saved');
                INSERT INTO leads(id,stage) VALUES('c','new');
            """)
            db.close()
            with patch.object(engine,"RUNTIME",root),patch.object(engine,"DB",dbfile):
                con=engine.conn()
                self.assertEqual(tuple(con.execute("SELECT contacted,saved,stage FROM leads WHERE id='a'").fetchone()),(1,0,"new"))
                self.assertEqual(tuple(con.execute("SELECT contacted,saved,stage FROM leads WHERE id='b'").fetchone()),(0,1,"new"))
                self.assertEqual(tuple(con.execute("SELECT contacted,saved,stage FROM leads WHERE id='c'").fetchone()),(0,0,"new"))
                con.execute("UPDATE leads SET contacted=0,saved=1 WHERE id='a'")
                con.commit();con.close()
                # Reopening must not restore outdated contacted states.
                con=engine.conn()
                self.assertEqual(tuple(con.execute("SELECT contacted,saved FROM leads WHERE id='a'").fetchone()),(0,1))
                # Both statuses may coexist independently.
                con.execute("UPDATE leads SET contacted=1 WHERE id='b'")
                con.commit()
                self.assertEqual(tuple(con.execute("SELECT contacted,saved FROM leads WHERE id='b'").fetchone()),(1,1))
                con.close()

    def test_http_api_independent_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(engine,"RUNTIME",root),patch.object(engine,"DB",root/"leads.sqlite3"):
                db=engine.conn()
                id="a"*20
                db.execute("INSERT INTO leads(id,stage,saved,contacted) VALUES(?,?,?,?)",(id,"new",0,0))
                db.commit();db.close()
                server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
                t=threading.Thread(target=server.serve_forever,daemon=True)
                t.start()
                url=f"http://127.0.0.1:{server.server_port}/api/lead"
                try:
                    def update(field,value):
                        request=urllib.request.Request(url,data=json.dumps({"id":id,"field":field,"value":value}).encode(),
                          headers={"Content-Type":"application/json"},method="POST")
                        with urllib.request.urlopen(request,timeout=3) as response:
                            return json.load(response)["lead"]
                    self.assertEqual(update("saved",True)["saved"],1)
                    row=update("contacted",True)
                    self.assertEqual((row["saved"],row["contacted"]),(1,1))
                    row=update("contacted",False)
                    self.assertEqual((row["saved"],row["contacted"]),(1,0))
                    self.assertEqual(update("saved",False)["saved"],0)
                finally:
                    server.shutdown()
                    server.server_close()
                    t.join(timeout=3)

if __name__=="__main__":
    unittest.main()
