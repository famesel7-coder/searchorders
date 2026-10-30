"""Strict eligibility for original-source leads and manual on-site applications.

An open bidding link, a Telegram nickname from a repost, or a site footer
must never be treated as the customer's direct application address.
Only specific source adapters which inspect the original request and its
application instructions are admitted to the actionable feed.
"""
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse


EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Explicit first-party collectors; extend only with collectors that check
# the actual order page and the contact in that order, not a generic footer.
DIRECT_CHANNELS = frozenset({
    "pending-agency", "impactpool-design", "design-jobs-board", "manual-email", "manual-platform", "flru-free"
})
PHONE = re.compile(r"\+\d{10,15}")
TELEGRAM_HANDLE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,31}")
TELEGRAM_POST = re.compile(r"/([A-Za-z0-9_]{5,32})/\d{1,12}/?")
def is_telegram_lead(row):
    """A published contact in an indexed Telegram post, not a verified buyer.

    The feed MUST label these separately from confirmed client email sources.
    """
    url=str(row.get("url") or "").strip()
    contact=str(row.get("contact") or "").strip()
    channel=str(row.get("channel") or "").strip()
    parsed=urlparse(url)
    match=TELEGRAM_POST.fullmatch(parsed.path)
    if (parsed.scheme!="https" or parsed.hostname not in ("t.me","www.t.me")
        or not match or match.group(1)!=channel
        or not (TELEGRAM_HANDLE.fullmatch(contact) or EMAIL.fullmatch(contact))):
        return False
    if "Контакт опубликован в Telegram" not in str(row.get("reason") or ""):
        return False
    if len(str(row.get("body") or ""))<60:
        return False
    try:
        dt=datetime.fromisoformat(str(row.get("published_at") or "").replace("Z","+00:00"))
        if dt.tzinfo is None:return False
        age=(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()
    except ValueError:return False
    return -3600 <= age <= 72*3600

def source_group(row):
    if is_telegram_lead(row):return "telegram"
    if is_direct_lead(row):return "other"
    return None

def is_direct_lead(row, today=None):
    channel = str(row.get("channel") or "")
    email = str(row.get("contact") or "").strip()
    url = str(row.get("url") or "").strip()
    if channel not in DIRECT_CHANNELS:
        return False
    if channel=="flru-free":
        from .browse_sources import platform_for_url
        if email != url or (platform_for_url(url) or {}).get("id")!="fl":
            return False
        if "для всех" not in str(row.get("reason") or "").lower():
            return False
        try:
            dt=datetime.fromisoformat(str(row.get("published_at") or "").replace("Z","+00:00"))
            if dt.tzinfo is None:return False
            age=(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()
            if not -7200 <= age <= 5*86400:return False
        except ValueError:return False
    elif channel=="manual-platform":
        from .browse_sources import platform_for_url
        if email != url or platform_for_url(url) is None:
            return False
    elif not EMAIL.fullmatch(email):
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
    if channel not in ("manual-platform","flru-free") and parsed.hostname.lower().removeprefix("www.") in ("fl.ru", "t.me", "telegram.me"):
        return False
    expires = str(row.get("expires_at") or "")
    if expires and expires < (today or date.today()).isoformat():
        return False
    return True
