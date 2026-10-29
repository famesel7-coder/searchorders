"""Direct-client-only policy: no exchange links or anonymous reposts in inbox."""
import unittest
from datetime import date
from realtime_service.direct_contacts import is_direct_lead


class DirectContactPolicyTests(unittest.TestCase):
    def row(self, **changes):
        base = {
            "channel": "pending-agency",
            "contact": "brief@client.example",
            "url": "https://agency.thepending.com/jobs/job/example",
            "expires_at": "",
        }
        base.update(changes)
        return base

    def test_real_direct_email_with_original_listing(self):
        self.assertTrue(is_direct_lead(self.row()))

    def test_no_contact_no_source_no_bid_without_email(self):
        for row in (
            self.row(contact=""),
            self.row(contact="@designer_hello"),
            self.row(contact="https://www.fl.ru/projects/123/test.html"),
            self.row(url=""),
            self.row(url="file:///tmp/leads"),
            self.row(channel="flru-free"),
            self.row(channel="telegram"),
            self.row(channel="unapproved-aggregator"),
            self.row(url="https://www.fl.ru/projects/111/design.html"),
        ):
            with self.subTest(row=row):
                self.assertFalse(is_direct_lead(row))

    def test_freelance_rosters_and_full_time_jobs_are_not_orders(self):
        self.assertFalse(is_direct_lead(self.row(
            body="Looking for designers for occasional project-based work.")))
        self.assertFalse(is_direct_lead(self.row(
            body="Hiring a designer for a full-time or freelance position.")))
        self.assertFalse(is_direct_lead(self.row(
            reason="Пул фрилансеров для будущих задач; оплаченный заказ не подтверждён")))

    def test_expired_brief_not_actionable(self):
        self.assertFalse(is_direct_lead(self.row(expires_at="2026-10-25"), date(2026, 10, 29)))
        self.assertTrue(is_direct_lead(self.row(expires_at="2026-11-01"), date(2026, 10, 29)))


if __name__ == "__main__":
    unittest.main()
