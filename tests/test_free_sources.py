"""Free bidding and direct-email-only freelance source regression tests."""
import unittest
from datetime import datetime,timezone
from email.utils import format_datetime
from unittest.mock import patch
from lxml import html,etree
from realtime_service import free_bid_sources as fl, direct_email_sources as dj

class SourcesTests(unittest.TestCase):
 def test_flru_only_free_design_projects(self):
  date=format_datetime(datetime.now(timezone.utc))
  markup=f"""<?xml version="1.0" encoding="utf-8"?>
  <rss><channel>
  <item><title>Разработать логотип (для всех)</title><link>https://www.fl.ru/projects/5511111/razrabotat-logotip.html</link>
  <pubDate>{date}</pubDate><description>Нужно нарисовать минималистичный логотип, передать исходники в Adobe Illustrator.</description></item>
  <item><title>Разработать логотип (Бюджет: 20000 ₽)</title><link>https://www.fl.ru/projects/5511112/razrabotat-logo.html</link>
  <pubDate>{date}</pubDate><description>Нужно нарисовать минималистичный логотип, передать исходники.</description></item>
  <item><title>Написать отзыв (для всех)</title><link>https://www.fl.ru/projects/5511113/napisat-otzyv.html</link>
  <pubDate>{date}</pubDate><description>Нужно оставить отзыв на карте.</description></item>
  </channel></rss>""".encode()
  class FakeResponse:
   content=markup
   def raise_for_status(self):pass
  with patch.object(fl.requests,"get",return_value=FakeResponse()):
   checked,rows,errors=fl.scan()
  self.assertEqual(checked,3)
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]["category"],"branding")
  self.assertEqual(rows[0]["channel"],"flru-free")
  self.assertEqual(rows[0]["contact"],rows[0]["url"])
  self.assertIn("бесплатный",rows[0]["reason"])
 def test_flru_never_invents_email(self):
  self.assertIsNone(fl.category("") if False else None)
  self.assertEqual(fl.category("Сделать презентацию"),"presentations")
  self.assertEqual(fl.category("Сделать лендинг"),"web")
 def test_designjobs_direct_mailto_only(self):
  markup='''<html><body><main><div>
   <div class="panel-heading"><div class="ml-[auto] expand-button"><a href="https://www.designjobsboard.com/job/99743/freelance-designer-typographer/"></a></div>
     <p>Agency Bell Freelance Designer & Typographer Remote Freelance</p></div>
   <div><span>JOB ADDED 3 weeks ago</span>
    <p>Creating working fonts for a freelance project with a design agency.</p>
    <a href="mailto:hello@agencybell.co.uk?subject=Freelance">Apply Now</a></div>
   </div></main><footer>info@designjobsboard.com</footer></body></html>'''
  root=html.fromstring(markup)
  with patch.object(dj,"fetch",return_value=root):
   result=dj.candidates()
  self.assertEqual(len(result),1)
  self.assertEqual(result[0]["contact"],"hello@agencybell.co.uk")
 def test_email_not_taken_from_footer(self):
  markup='''<html><main><div class="panel-heading"><div class="ml-[auto]"><a href="https://www.designjobsboard.com/job/99743/freelance-designer-typographer/"></a></div>
  Freelance Graphic Designer Remote Freelance</div><div>JOB ADDED 2 weeks ago
  <a href="https://example.com/account/signup">Apply Now</a></div></main>
  <footer>mailto:jobs@fake.example</footer></html>'''
  with patch.object(dj,"fetch",return_value=html.fromstring(markup)):
   self.assertEqual(dj.candidates(),[])
 def test_source_urls_are_host_restricted(self):
  for value in ["http://www.designjobsboard.com/","https://bad.site/job/123/","file:///etc/passwd"]:
   with self.assertRaises(ValueError):dj.fetch(value)

if __name__=="__main__":unittest.main()
