"""Strict eligibility for direct-client contact leads.

An open bidding link, a Telegram nickname from a repost, or a site footer
must never be treated as the customer's direct application address.
Only specific source adapters which inspect the original request and its
application instructions are admitted to the actionable feed.
"""
import re
from datetime import date
from urllib.parse import urlparse

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Explicit first-party collectors; extend only with collectors that check
# the actual order page and the contact in that order, not a generic footer.
DIRECT_CHANNELS = frozenset({
    "pending-agency", "impactpool-design", "design-jobs-board", "manual-email"
})

def is_direct_lead(row, today=None):
    channel = str(row.get("channel") or "")
    email = str(row.get("contact") or "").strip()
    url = str(row.get("url") or "").strip()
    if channel not in DIRECT_CHANNELS or not EMAIL.fullmatch(email):
        return False
    text = str(row.get("body") or "").lower()
    reason = str(row.get("reason") or "").lower()
    # A talent pool or a full-time vacancy is not a concrete paid order.
    if ("пул фрилансеров для будущих задач" in reason
        or "occasional project-based work" in text
        or "full-time or freelance position" in text):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return False
    # Never treat a free exchange bid or a public Telegram repost as a
    # confirmed client contact, even when its name happens to look like email.
    if parsed.hostname.lower().removeprefix("www.") in ("fl.ru", "t.me", "telegram.me"):
        return False
    expires = str(row.get("expires_at") or "")
    if expires and expires < (today or date.today()).isoformat():
        return False
    return True
