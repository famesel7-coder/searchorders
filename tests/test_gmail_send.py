"""Regression: Gmail sends only via a user-confirmed prefilled browser draft."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from realtime_service import app,engine


class GmailDraftOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.patchers=[
          patch.object(engine,"RUNTIME",root),
          patch.object(engine,"DB",root/"leads.sqlite3"),
          patch.object(app,"conn",engine.conn),
          patch.object(app,"CONFIG",root/"settings.json")
        ]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),thread.join(timeout=3)))
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def get(self,path):
        with urllib.request.urlopen(self.base+path,timeout=4) as res:
            return json.load(res) if path.startswith("/api/") else res.read().decode()

    def post(self,path,data):
        request=urllib.request.Request(self.base+path,data=json.dumps(data).encode(),
                     headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=4) as r:
                return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            return e.code,json.load(e)

    def test_no_direct_sending_endpoint(self):
        code,data=self.post("/api/gmail/send",{"id":"a"*20,"from":"famesel7@gmail.com",
           "subject":"Test","body":"Do not send automatically"})
        self.assertEqual(code,404)
        self.assertEqual(data["error"],"Not found")

    def test_no_gmail_password_configuration_required(self):
        settings=self.get("/api/settings")
        self.assertNotIn("gmail_configured",settings)
        self.assertNotIn("gmail_app_password",settings)
        code,response=self.post("/api/settings",{"min_alert_score":80})
        self.assertEqual(code,200)
        self.assertNotIn("gmail_configured",response)

    def test_browser_composition_is_only_send_flow(self):
        html=self.get("/")
        self.assertIn("gmailComposeUrl(",html)
        self.assertIn("https://mail.google.com/mail/?",html)
        self.assertNotIn("/api/gmail/send",html)
        self.assertNotIn("gmailAppPassword",html)
        self.assertIn("onclick=\"sendDraft()\"",html)
        self.assertIn("Готовое письмо",html)

if __name__=="__main__":unittest.main()
