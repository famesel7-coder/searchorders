"""Public Workspace tender discovery and on-platform response safety."""
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from lxml import html
from realtime_service import platform_sources as ws

MONTHS=("", "января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря")
def ru_date(d):return f"{d.day:02d} {MONTHS[d.month]} {d.year}"

class WorkspaceTests(unittest.TestCase):
 def source(self):return ws.SOURCES[1]
 def detail_html(self,desc="Нужен дизайн сайта на Тильде и адаптивные макеты. Проектный формат, бюджет согласуем."):
  return html.fromstring(f'<html><body><p>Чтобы участвовать в тендере войдите/зарегистрируйтесь как digital-агентство или специалист.</p><div class="tendercard__desc">{desc}</div></body></html>')
 def listing_html(self,open=True,deadline=None):
  now=datetime.now(timezone.utc).date()
  deadline=deadline or now+timedelta(days=6)
  stamp=now-timedelta(days=2)
  state="open" if open else "close"
  return html.fromstring(f"""<html><body><div data-tender-card>
  <div data-change-status-text="{state}">Идет прием заявок</div><span>Публичный</span>
  <a href="/tenders/redizayn-sayta-mebelnoy-fabriki-19087/">Редизайн сайта мебельной фабрики</a>
  <p>100 000 - 400 000</p><p>Опубликован {ru_date(stamp)}</p>
  <p>Крайний срок приема заявок: {ru_date(deadline)}</p>
  <p>Заказчик указал корпоративный e-mail.</p></div></body></html>""")
 def test_open_project_provides_platform_link_not_email(self):
  with patch.object(ws,"fetch",side_effect=[self.listing_html(),self.detail_html()]):
   rows=ws.list_candidates(self.source())
   self.assertEqual(len(rows),1)
   self.assertEqual(rows[0]["budget"],"100 000 - 400 000")
   lead=ws.candidate_to_lead(rows[0],self.source())
  self.assertEqual(lead["channel"],"workspace-tender")
  self.assertEqual(lead["category"],"web")
  self.assertIn("не является прямым email",lead["reason"])
  self.assertTrue(lead["contact"].startswith("https://workspace.ru/tenders/"))
  self.assertEqual(lead["expires_at"],rows[0]["deadline"].isoformat())
 def test_closed_expired_excluded(self):
  with patch.object(ws,"fetch",return_value=self.listing_html(open=False)):
   self.assertEqual(ws.list_candidates(self.source()),[])
  with patch.object(ws,"fetch",return_value=self.listing_html(deadline=datetime.now(timezone.utc).date()-timedelta(days=1))):
   self.assertEqual(ws.list_candidates(self.source()),[])
 def test_unverified_application_route_not_eligible(self):
  with patch.object(ws,"fetch",return_value=html.fromstring(
    '<html><body><div class="tendercard__desc">Нужно разработать лендинг на Тильде, бюджет согласуем.</div></body></html>')):
   result=ws.candidate_to_lead({
      "url":"https://workspace.ru/tenders/redizayn-sayta-mebelnoy-fabriki-19087/",
      "title":"Редизайн сайта","published":datetime.now(timezone.utc).date(),
      "deadline":datetime.now(timezone.utc).date()+timedelta(days=2),
      "budget":"до 100 000","corporate_email":False},self.source())
   self.assertIsNone(result)
 def test_cross_domain_fetch_blocked(self):
  for url in ["http://workspace.ru/tenders/x/","https://evil.example/tenders/anything/","https://workspace.ru/admin"]:
   with self.assertRaises(ValueError):ws.fetch(url)
if __name__=="__main__":unittest.main()
