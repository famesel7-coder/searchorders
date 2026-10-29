"""Gmail direct-send: no external delivery in tests, fail-safe duplicate handling."""
import json
import os
import smtplib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from realtime_service import app,engine,gmail_delivery


class GmailSendTests(unittest.TestCase):
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
        con=engine.conn()
        for leadid,contact,stage,contacted in [
            ("a"*20,"client@example.org","new",0),
            ("b"*20,"@telegram_contact","new",0),
            ("c"*20,"contact2@example.org","dismissed",0),
            ("d"*20,"sent@example.org","new",1)]:
            stamp=datetime.now(timezone.utc).isoformat()
            con.execute("""INSERT INTO leads(id,url,channel,published_at,discovered_at,body,
              category,score,contact,buyer,budget,reason,fingerprint,stage,contacted)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (leadid,"https://jobs.example/"+leadid,"test",stamp,stamp,
              "We need a freelance graphic designer for our presentation",
              "branding",91,contact,"Studio","","",leadid,stage,contacted))
        con.commit();con.close()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),self.thread.join(timeout=4)))
        self.base=f"http://127.0.0.1:{self.server.server_port}"
        self.mail={"id":"a"*20,"from":gmail_delivery.GMAIL_ADDRESS,
                   "subject":"Freelance Graphic Designer","body":
                   "Hello, I saw the open freelance opportunity. Portfolio: https://samsel.site"}

    def request(self,method,path,payload=None,headers=None):
        hs={"Content-Type":"application/json"}
        hs.update(headers or {})
        body=json.dumps(payload or {}).encode() if method=="POST" else None
        req=urllib.request.Request(self.base+path,data=body,headers=hs,method=method)
        try:
            with urllib.request.urlopen(req,timeout=5) as res:
                return res.status,json.load(res)
        except urllib.error.HTTPError as e:
            return e.code,json.load(e)

    def configured(self):
        return self.request("POST","/api/settings",
                            {"gmail_app_password":"abcd efgh ijkl mnop"})

    def test_password_config_secrecy_and_permissions(self):
        code,result=self.configured()
        self.assertEqual(code,200)
        self.assertTrue(result["gmail_configured"])
        mode=app.CONFIG.stat().st_mode&0o777
        self.assertEqual(mode,0o600)
        contents=app.CONFIG.read_text()
        self.assertIn("abcdefghijklmnop",contents)
        self.assertNotIn("abcdefghijklmnop",json.dumps(result))
        code,status=self.request("GET","/api/settings")
        self.assertTrue(status["gmail_configured"])
        self.assertNotIn("gmail_app_password",status)
        code,result=self.request("POST","/api/settings",
                       {"remove_gmail_app_password":True})
        self.assertEqual(code,200)
        self.assertFalse(result["gmail_configured"])

    def test_unconfigured_cannot_send(self):
        with patch.object(app,"deliver") as send:
            code,response=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code,409)
            send.assert_not_called()
        self.assertEqual(self.request("GET","/api/leads?stage=not_contacted&email_only=1")[1]["items"][0]["contacted"],0)

    def test_direct_send_once_and_mark_contacted_after_ack(self):
        self.configured()
        with patch.object(app,"deliver",return_value="<provider-confirmed@gmail.com>") as send:
            code,response=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code,200)
            self.assertTrue(response["sent"])
            self.assertEqual(response["to"],"client@example.org")
            self.assertEqual(response["from"],"famesel7@gmail.com")
            self.assertEqual(response["message_id"],"<provider-confirmed@gmail.com>")
            self.assertEqual(send.call_count,1)
            args=send.call_args.args
            self.assertEqual(str(args[0]["To"]),"client@example.org")
            self.assertEqual(str(args[0]["From"]),"famesel7@gmail.com")
            self.assertEqual(args[1],"abcdefghijklmnop")
            code2,result2=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code2,409)
            self.assertEqual(send.call_count,1)
        con=engine.conn()
        self.assertEqual(con.execute("SELECT contacted FROM leads WHERE id=?",("a"*20,)).fetchone()[0],1)
        self.assertEqual(con.execute("SELECT status FROM gmail_sends WHERE lead_id=?",("a"*20,)).fetchone()[0],"sent")
        con.close()

    def test_failed_login_stays_uncontacted_and_is_retryable(self):
        self.configured()
        with patch.object(app,"deliver",side_effect=smtplib.SMTPAuthenticationError(535,b"invalid")):
            code,response=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code,401)
            self.assertNotIn("invalid",response["error"])
        con=engine.conn()
        self.assertEqual(con.execute("SELECT contacted FROM leads WHERE id=?",("a"*20,)).fetchone()[0],0)
        self.assertEqual(con.execute("SELECT status FROM gmail_sends").fetchone()[0],"failed")
        con.close()
        with patch.object(app,"deliver",return_value="<ok@gmail.com>") as send:
            code,_=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code,200)
            send.assert_called_once()

    def test_uncertain_network_delivery_blocks_retries(self):
        self.configured()
        with patch.object(app,"deliver",side_effect=smtplib.SMTPServerDisconnected("lost")) as send:
            code,response=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code,502)
            self.assertIn("Отправленные",response["error"])
            code2,response2=self.request("POST","/api/gmail/send",self.mail)
            self.assertEqual(code2,409)
            self.assertEqual(send.call_count,1)
        con=engine.conn()
        self.assertEqual(con.execute("SELECT status FROM gmail_sends").fetchone()[0],"unknown")
        self.assertEqual(con.execute("SELECT contacted FROM leads WHERE id=?",("a"*20,)).fetchone()[0],0)
        con.close()

    def test_wrong_sender_or_contact_or_hidden_is_blocked(self):
        self.configured()
        with patch.object(app,"deliver") as send:
            for change,expected in [
              ({"from":"cco@imon.agency"},400),
              ({"id":"b"*20},409),
              ({"id":"c"*20},409),
              ({"id":"d"*20},409),
              ({"subject":"Hello\r\nBcc:bad@example.org"},400),
              ({"body":"hi"},400)]:
                data={**self.mail,**change}
                code,_=self.request("POST","/api/gmail/send",data)
                self.assertEqual(code,expected,change)
            send.assert_not_called()

    def test_cross_origin_is_blocked(self):
        self.configured()
        with patch.object(app,"deliver") as send:
            code,data=self.request("POST","/api/gmail/send",self.mail,
                                   headers={"Origin":"https://evil.example"})
            self.assertEqual(code,403)
            send.assert_not_called()

if __name__=="__main__":
    unittest.main()
