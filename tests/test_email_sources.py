"""Tests for the two publicly verified email-source connectors."""
import tempfile
import unittest
from datetime import date,timedelta,datetime,timezone
from unittest.mock import patch

from lxml import html
from realtime_service import email_sources as src


class EmailSourcesTests(unittest.TestCase):
    def test_pending_detail_with_direct_application_email_and_deadline(self):
        markup="""<html><main><h1>Freelance Graphic Designer</h1>
         <p>Gig / Single Project. International applicants welcome.</p>
         <p>We are seeking a freelance graphic designer for visual identity and presentation design
         on a 2-week client brief. Send your CV and portfolio to hire@example.org.</p>
         <p>Apply by · 2026-11-08</p>
         <p>Project dates · 2026-11-15 – 2026-12-01</p>
         </main></html>"""
        with patch.object(src,"fetch_html",return_value=html.fromstring(markup)):
            item=src.pending_detail("https://agency.thepending.com/jobs/job/12345678-1234-1234-1234-123456789abc/")
        self.assertEqual(item["contact"],"hire@example.org")
        self.assertEqual(item["expires_at"],"2026-11-08")
        self.assertIn("не опубликована",item["reason"])
        self.assertEqual(item["channel"],"pending-agency")

    def test_no_email_and_site_footer_must_not_qualify(self):
        page=html.fromstring("""<html><body><main><h1>Graphic Designer</h1><p>Project contract
         for a logo design. Apply via website account.</p></main>
         <footer>info@unrelated.example.com</footer></body></html>""")
        with patch.object(src,"fetch_html",return_value=page):
            self.assertIsNone(src.pending_detail("https://agency.thepending.com/jobs/job/12345678-1234-1234-1234-123456789abc/"))

    def test_required_dutch_excludes_unqualified_project(self):
        page=html.fromstring("""<html><main><h1>Junior Graphic Designer</h1>
         <p>Freelance project; Dutch reading/writing is a must.</p>
         <p>Send your portfolio via email to recruiter@example.org.</p>
         <p>Apply by · 2026-11-08</p></main></html>""")
        with patch.object(src,"fetch_html",return_value=page):
            self.assertIsNone(src.pending_detail("https://agency.thepending.com/jobs/job/12345678-1234-1234-1234-123456789abc/"))

    def test_old_deadline_is_excluded(self):
        page=html.fromstring("""<html><main><h1>Freelance Graphic Designer</h1>
         <p>Freelance project: send your portfolio to hiring@example.org.</p>
         <p>Apply by · 2026-09-02</p></main></html>""")
        with patch.object(src,"fetch_html",return_value=page):
            self.assertIsNone(src.pending_detail("https://agency.thepending.com/jobs/job/12345678-1234-1234-1234-123456789abc/"))

    def test_date_is_discovery_not_invented_publication(self):
        lead=src.make_lead("https://agency.thepending.com/jobs/job/12345678-1234-1234-1234-123456789abc/",
          "Freelance graphic designer needed for a project. Send your portfolio to hiring@example.org.",
          "hiring@example.org","Client","pending-agency",date(2026,11,8))
        self.assertIsNotNone(lead)
        self.assertIn("обнаружение",lead["reason"])
        self.assertEqual(lead["expires_at"],"2026-11-08")

    def test_english_email_draft_and_required_subject(self):
        from realtime_service.outreach import create_draft, subject_for_brief
        lead={"category":"branding","body":"""Call for freelance graphic designer at Transparency International.
        This is a freelance tender for print publications and data visualizations.
        Please indicate “Freelance Graphic Designer” in the subject line of your email application.
        Applications should be sent to graphicdesigners@transparency.org by 31 October 2026."""}
        text,mode,brief=create_draft(lead)
        self.assertIn("Hello",text) if text.startswith("Hello") else self.assertIn("Hi",text)
        self.assertIn("https://samsel.site",text)
        self.assertNotIn("Здравствуйте",text)
        self.assertEqual(subject_for_brief(brief),"Freelance Graphic Designer")

    def test_future_london_subject_is_preserved(self):
        from realtime_service.outreach import analyse_brief,subject_for_brief
        lead={"body":"Freelance Designer. We are looking for independent designers for project-based work. Send portfolio to partnerships@futurelondonacademy.co.uk with the subject line 'Freelance Designer'.","category":"branding"}
        self.assertEqual(subject_for_brief(analyse_brief(lead)),"Freelance Designer")

    def test_validated_source_urls_only(self):
        with self.assertRaises(ValueError):
            src.fetch_html("http://127.0.0.1/private")

if __name__=="__main__":unittest.main()
