"""Translation endpoint: original preserved, external call only on click, cache safe."""
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from realtime_service import engine,app,translation

BRIEF=("Transparency International is looking for freelance graphic designers "
       "to create data visualizations for publications and editorial materials. "
       "Candidates should send a portfolio and hourly rates before the deadline.")

class TranslationTests(unittest.TestCase):
    def test_chunking_and_language_recognition(self):
        self.assertTrue(translation.looks_english(BRIEF))
        self.assertFalse(translation.looks_english("Нужен дизайнер для создания презентации из 15 слайдов."))
        self.assertEqual(translation.chunks("   ",850),[])
        text=("Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 100)
        pieces=translation.chunks(text,850)
        self.assertGreater(len(pieces),3)
        self.assertTrue(all(len(x)<=850 for x in pieces))
        self.assertEqual(" ".join(" ".join(pieces).split())," ".join(text.split()))

    def test_external_success_response_and_error(self):
        class FakeResponse:
            def raise_for_status(self):return None
            def json(self):return ["Требуется дизайнер для публикаций."]
        with patch.object(translation.requests,"get",return_value=FakeResponse()) as req:
            result=translation.translate_to_russian(BRIEF)
            self.assertEqual(result,"Требуется дизайнер для публикаций.")
            self.assertEqual(req.call_args.kwargs["params"]["tl"],"ru")
        with patch.object(translation.requests,"get",side_effect=ValueError("blocked")):
            with self.assertRaises(ValueError):
                translation.translate_to_russian(BRIEF)

    def test_empty_or_short_nonenglish_input(self):
        with self.assertRaises(ValueError):
            translation.translate_to_russian("hello")
        with self.assertRaises(ValueError):
            translation.translate_to_russian("a"*translation.MAX_TEXT+"a")

    def test_http_translation_is_cached_and_does_not_modify_original(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder)
            dbfile=runtime/"leads.sqlite3"
            patchers=[patch.object(engine,"RUNTIME",runtime),
                      patch.object(engine,"DB",dbfile),
                      patch.object(app,"conn",engine.conn)]
            for p in patchers:p.start()
            try:
                db=engine.conn()
                ident="1"*20
                now=datetime.now(timezone.utc).isoformat()
                db.execute("""INSERT INTO leads(id,url,channel,published_at,discovered_at,body,category,
                  score,contact,buyer,budget,reason,fingerprint)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ident,"https://example.org/job","pending-agency",now,now,BRIEF,"branding",85,
                   "contact@example.org","International","","",ident))
                db.commit()
                db.close()
                srv=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
                thread=threading.Thread(target=srv.serve_forever,daemon=True)
                thread.start()
                base=f"http://127.0.0.1:{srv.server_port}"
                def post(ident,target="ru"):
                    request=urllib.request.Request(base+"/api/translate",
                      data=json.dumps({"id":ident,"target":target}).encode(),
                      headers={"Content-Type":"application/json"},method="POST")
                    with urllib.request.urlopen(request,timeout=4) as res:return json.load(res)
                try:
                    with patch.object(app,"translate_to_russian",return_value="Международная организация ищет дизайнера.") as translator:
                        a=post(ident)
                        b=post(ident)
                        self.assertEqual(a["translation"],b["translation"])
                        self.assertFalse(a["cached"])
                        self.assertTrue(b["cached"])
                        translator.assert_called_once_with(BRIEF)
                        # A later change invalidates the cached translation.
                        db=engine.conn()
                        changed=BRIEF+" This is a short additional requirement."
                        db.execute("UPDATE leads SET body=? WHERE id=?",(changed,ident));db.commit();db.close()
                        c=post(ident)
                        self.assertFalse(c["cached"])
                        self.assertEqual(translator.call_count,2)
                    db=engine.conn()
                    original=db.execute("SELECT body FROM leads WHERE id=?",(ident,)).fetchone()[0]
                    self.assertEqual(original,changed)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM translation_cache").fetchone()[0],2)
                    db.close()
                    with self.assertRaises(urllib.error.HTTPError) as bad:
                        post(ident,"de")
                    self.assertEqual(bad.exception.code,400)
                    with self.assertRaises(urllib.error.HTTPError) as missing:
                        post("f"*20)
                    self.assertEqual(missing.exception.code,404)
                finally:
                    srv.shutdown();srv.server_close();thread.join(timeout=3)
            finally:
                for p in reversed(patchers):p.stop()

    def test_ui_has_translation_switch_only_for_english(self):
        page=Path(__file__).resolve().parents[1].joinpath("realtime_service/index.html").read_text()
        self.assertIn('function looksEnglish(',page)
        self.assertIn('id="translateRussian"',page)
        self.assertIn("switchTranslation(",page)
        self.assertIn('English</button>',page)
        self.assertIn('Русский</button>',page)
        self.assertIn('id="projectDescription"',page)

if __name__=="__main__":
    unittest.main()
