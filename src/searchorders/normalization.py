from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Iterable

from .models import Lead

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
CONTACT_RE = re.compile(r"(?:https?://t\.me/[A-Za-z0-9_+\-/]+|@[A-Za-z0-9_]{4,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d\s()\-]{8,}\d))", re.IGNORECASE)
BUDGET_RANGE_RE = re.compile(r"(?:бюджет|оплата|стоимость|budget)?\s*[:—-]?\s*(?P<low>\d[\d\s.,]{1,10})\s*(?:-|–|—|до)\s*(?P<high>\d[\d\s.,]{1,10})\s*(?P<mult>тыс(?:яч)?|k|млн|m)?\s*(?P<cur>₽|руб(?:лей|ля|\.)?|р\.|usd|\$|eur|€)?", re.IGNORECASE)
BUDGET_SINGLE_RE = re.compile(r"(?:бюджет|оплата|стоимость|budget)\s*[:—-]?\s*(?:от\s*)?(?P<value>\d[\d\s.,]{1,10})\s*(?P<mult>тыс(?:яч)?|k|млн|m)?\s*(?P<cur>₽|руб(?:лей|ля|\.)?|р\.|usd|\$|eur|€)?", re.IGNORECASE)
DEADLINE_RE = re.compile(r"(?:срок|дедлайн|deadline)\s*[:—-]\s*(?P<value>[^\n.;]{2,80})", re.IGNORECASE)
DEADLINE_UNTIL_RE = re.compile(r"\b(?:до|к)\s+(?P<value>(?:\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)|(?:конц[ау]\s+(?:недели|месяца))|(?:следующей\s+недели))", re.IGNORECASE)
COMPANY_RE = re.compile(r"(?:^|\n)\s*(?:компания|заказчик|клиент|бренд)\s*[:—-]\s*(?P<value>[^\n,;]{2,100})", re.IGNORECASE)


def normalize_text(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = URL_RE.sub(" ", value)
    value = re.sub(r"[^a-zа-я0-9@+]+", " ", value, flags=re.IGNORECASE)
    return WS_RE.sub(" ", value).strip()


def _number(value: str, multiplier: str | None) -> int | None:
    cleaned = value.replace(" ", "").replace(",", ".")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    mult = (multiplier or "").casefold()
    if mult.startswith("тыс") or mult == "k": number *= 1000
    elif mult in {"млн", "m"}: number *= 1000000
    result = int(number)
    return result if 500 <= result <= 1000000000 else None


def _currency(value: str | None) -> str | None:
    normalized = (value or "").casefold()
    if any(marker in normalized for marker in ("₽", "руб", "р.")): return "RUB"
    if "usd" in normalized or "$" in normalized: return "USD"
    if "eur" in normalized or "€" in normalized: return "EUR"
    return None


def extract_budget(text: str) -> tuple[int | None, int | None, str | None]:
    match = BUDGET_RANGE_RE.search(text)
    if match:
        low = _number(match.group("low"), match.group("mult")); high = _number(match.group("high"), match.group("mult"))
        if low and high and low <= high: return low, high, _currency(match.group("cur"))
    match = BUDGET_SINGLE_RE.search(text)
    if match:
        value = _number(match.group("value"), match.group("mult"))
        if value: return value, None, _currency(match.group("cur"))
    return None, None, None


def extract_contacts(text: str) -> list[str]:
    values: list[str] = []
    for match in CONTACT_RE.findall(text):
        cleaned = match.rstrip(".,);]")
        if cleaned and cleaned not in values: values.append(cleaned)
    return values[:10]


def extract_deadline(text: str) -> str | None:
    match = DEADLINE_RE.search(text) or DEADLINE_UNTIL_RE.search(text)
    if not match: return None
    return " ".join(match.group("value").strip(" .,:;—-").split())[:120] or None


def extract_company_name(text: str) -> str | None:
    match = COMPANY_RE.search(text)
    if not match: return None
    value = " ".join(match.group("value").strip(" .,:;—-").split())
    if len(value) < 2 or len(value) > 100: return None
    return value


def content_fingerprint(lead: Lead) -> str:
    text = normalize_text(f"{lead.title}\n{lead.description}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contact_set(lead: Lead) -> set[str]:
    return {item.casefold() for item in lead.contacts or extract_contacts(lead.description)}


def enrich_lead(lead: Lead) -> Lead:
    full_text = f"{lead.title}\n{lead.description}"
    contacts = lead.contacts or extract_contacts(lead.description)
    low, high, currency = extract_budget(full_text)
    raw = dict(lead.raw); raw.setdefault("content_fingerprint", content_fingerprint(lead))
    return replace(lead, contacts=contacts, has_direct_contact=lead.has_direct_contact or bool(contacts), budget_from=lead.budget_from if lead.budget_from is not None else low, budget_to=lead.budget_to if lead.budget_to is not None else high, currency=lead.currency or currency, deadline_text=lead.deadline_text or extract_deadline(full_text), company_name=lead.company_name or extract_company_name(full_text), raw=raw)


def compact_source_refs(leads: Iterable[Lead]) -> list[dict[str, str | None]]:
    return [{"source_id": lead.source_id or lead.source, "source": lead.source, "source_name": lead.source_name, "external_id": lead.external_id, "url": lead.url} for lead in leads]
