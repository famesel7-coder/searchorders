"""HeadHunter project vacancy scanner, using only the official public vacancies API.

Strict rules: no CAPTCHA bypass, no HTML scraping, no deduced employer emails.
Import a vacancy only when the actual vacancy JSON includes an application
email/phone or an explicit email application instruction in its own description.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from lxml import html as lxml_html

API = "https://api.hh.ru/vacancies"
SOURCE_ID = "hh-direct"
SEARCH_TERMS = (
    "дизайнер презентаций",
    "Tilda дизайнер",
    "UI UX дизайнер проект",
    "дизайнер интерфейсов фриланс",
    "графический дизайнер проектная работа",
    "бренд дизайнер фриланс",
)
SOURCES = (
    {"id": SOURCE_ID, "title": "HeadHunter · прямые контакты",
     "url": "https://hh.ru/search/vacancy?text=%D0%B4%D0%B8%D0%B7%D0%B0%D0%B9%D0%BD%D0%B5%D1%80"},
)
FETCHERS = {SOURCE_ID: lambda: scan()}
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
PHONE = re.compile(r"^\+\d{10,15}$")
PROJECT = re.compile(
    r"фриланс|внештат|проектн.{0,15}(?:работ|занят|задач)|под\s+проект|"
    r"оплат.{0,15}за\s+проект|разов.{0,20}(?:задач|проект)|"
    r"по\s+договору\s+гпх|\bгпх\b|договор\s+подряда|самозанят|"
    r"подработк|сдельн|freelance|project.based|per.project|"
    r"short.term\s+contract|contract\s+designer|разработать\s+(?:лендинг|презентац)",
    re.I,
)
FULL_TIME = re.compile(
    r"в\s+штат|полная\s+занятость|полн.{0,7}\s+рабоч.{0,7}\s+день|"
    r"постоянн.{0,20}\s+работ|оклад|график\s+5/2|full.time|full.time\s+or\s+freelance",
    re.I,
)
APPLICATION = re.compile(
    r"(?:пишите|написать|присылайте|отправ(?:ьте|ляйте)|резюме\s+на|"
    r"портфолио\s+на|send\s+(?:your\s+)?(?:portfolio|cv|application)\s+to|"
    r"email\s+(?:us|your\s+portfolio)\s+at)\s*(?:на\s+почту|на\s+email|по\s+адресу|to)?\s*[:—-]?\s*",
    re.I,
)

def token():
    value = os.environ.get("SEARCHORDERS_HH_TOKEN", "").strip()
    if value:
        return value
    # Read only the local protected settings, never expose it in API status.
    from .engine import RUNTIME
    path = Path(RUNTIME) / "settings.json"
    try:
        return str(json.loads(path.read_text()).get("hh_api_token") or "").strip()
    except (ValueError, OSError, AttributeError):
        return ""

def request_json(path, *, params=None):
    if path != API and not re.fullmatch(r"https://api\.hh\.ru/vacancies/\d{5,15}", path):
        raise ValueError("Only official HH vacancies endpoints are allowed")
    headers = {
        "User-Agent": "SearchOrders/1.0 (famesel7@gmail.com)",
        "HH-User-Agent": "SearchOrders/1.0 (famesel7@gmail.com)",
        "Accept": "application/json",
    }
    access = token()
    if access:
        headers["Authorization"] = "Bearer " + access
    response = requests.get(path, params=params, headers=headers, timeout=(5, 14), allow_redirects=False)
    if response.status_code in (401, 403):
        raise PermissionError(
            "HH API: доступ ограничен (HTTP " + str(response.status_code) +
            "). Требуется официальная авторизация или разрешение капчи на стороне hh.ru."
        )
    if response.status_code == 429:
        raise RuntimeError("HH API: превышен лимит запросов (429). Повторная попытка позже.")
    response.raise_for_status()
    if len(response.content) > 1_500_000:
        raise ValueError("Unexpected HH API response size")
    if "json" not in response.headers.get("Content-Type", ""):
        raise ValueError("HH API did not return JSON")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected HH API response")
    return data

def plain(text):
    if not isinstance(text, str):
        return ""
    try:
        fragment = lxml_html.fragment_fromstring("<div>" + text + "</div>")
        return " ".join(" ".join(fragment.itertext()).split())
    except Exception:
        return " ".join(re.sub(r"<[^>]*>", " ", text).split())

def email_from_description(body):
    # No generic email harvesting: explicit application instruction and
    # mailbox must appear in one short sentence.
    for match in EMAIL.finditer(body):
        nearby = body[max(0, match.start()-110):match.start()]
        if APPLICATION.search(nearby) and not match.group().lower().startswith(
                ("noreply@", "no-reply@", "support@", "privacy@")):
            return match.group().lower()
    return None

def direct_contact(vacancy, body):
    contacts = vacancy.get("contacts")
    if isinstance(contacts, dict):
        address = str(contacts.get("email") or "").strip().lower()
        if EMAIL.fullmatch(address):
            return address
        for phone in contacts.get("phones") or []:
            if not isinstance(phone, dict):
                continue
            country = re.sub(r"\D", "", str(phone.get("country") or ""))
            city = re.sub(r"\D", "", str(phone.get("city") or ""))
            number = re.sub(r"\D", "", str(phone.get("number") or ""))
            candidate = "+" + country + city + number
            if PHONE.fullmatch(candidate):
                return candidate
    return email_from_description(body)

def category(text):
    from .engine import CATEGORIES
    matches = {k: len(re.findall(pat, text, re.I)) for k, (_, pat) in CATEGORIES.items()}
    choice = max(matches, key=matches.get)
    if matches[choice]:
        return choice
    if re.search(r"graphic designer|brand designer|presentation designer|web designer|ui.?ux designer", text, re.I):
        return "branding"
    return None

def convert(vacancy, current=None):
    now = current or datetime.now(timezone.utc)
    vid = str(vacancy.get("id") or "")
    if not re.fullmatch(r"\d{5,15}", vid):
        return None
    url = str(vacancy.get("alternate_url") or "")
    if not re.fullmatch(r"https://(?:www\.)?hh\.ru/vacancy/" + vid + r"/?(?:\?[^#]*)?", url):
        return None
    if vacancy.get("archived") is True:
        return None
    stamp = vacancy.get("published_at")
    try:
        published = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
    age = now - published
    if not timedelta(hours=-1) <= age <= timedelta(hours=72):
        return None
    title = plain(vacancy.get("name"))
    description = plain(vacancy.get("description"))
    if len(description) < 45:
        return None
    body = title + "\n\n" + description
    cat = category(title + " " + description[:1400])
    if not cat:
        return None
    form = vacancy.get("employment_form") or vacancy.get("employment") or {}
    form_label = str(form.get("name") or "") if isinstance(form, dict) else ""
    combined = title + "\n" + form_label + "\n" + description
    if not PROJECT.search(combined):
        return None
    if FULL_TIME.search(title + " " + form_label) and not re.search(
            r"разов|проект|внештат|фриланс|гпх|подработ|freelance", title + " " + form_label, re.I):
        return None
    if "full-time or freelance position" in combined.lower() or re.search(
            r"\bв\s+штат\b.{0,25}\bили\b.{0,25}\bфриланс", combined, re.I):
        return None
    address = direct_contact(vacancy, description)
    if not address:
        return None
    employer = vacancy.get("employer")
    buyer = plain(employer.get("name"))[:110] if isinstance(employer, dict) else ""
    if not buyer or re.search(r"конфиденциальн|анонимн|скрыт", buyer, re.I):
        return None
    # Monthly vacancy salary must not be presented as the project budget.
    salary = vacancy.get("salary_range") or vacancy.get("salary") or {}
    compensation = ""
    if isinstance(salary, dict):
        salary_min = salary.get("from")
        salary_max = salary.get("to")
        if isinstance(salary_min, (float, int)) or isinstance(salary_max, (float, int)):
            compensation = ("Оплата в вакансии (не обязательно за проект): " +
                            str(salary_min or "") + "–" + str(salary_max or "") +
                            " " + str(salary.get("currency") or "") + ". ")
    source = "Публичная карточка HH: прямой контакт в данных вакансии или инструкции по отклику. "
    if address.startswith("+"):
        source += "Телефон из поля contacts. "
    else:
        source += "Email из поля contacts или прямых инструкций вакансии. "
    source += compensation + "Опубликовано " + published.date().isoformat() + "."
    fingerprint = hashlib.sha1((url + "|" + address.lower()).encode()).hexdigest()
    return {
        "id": hashlib.sha1(url.encode()).hexdigest()[:20],
        "url": url, "channel": SOURCE_ID,
        "published_at": published.isoformat(), "discovered_at": now.isoformat(),
        "body": body[:3600], "category": cat,
        "score": 84 if address.count("@") else 78,
        "contact": address, "buyer": buyer,
        "budget": "", "reason": source,
        "fingerprint": fingerprint, "expires_at": "",
    }

def scan():
    found = 0
    potential = {}
    errors = []
    # Use a bounded number of official queries; stop immediately on 403/429.
    for term in SEARCH_TERMS[:4]:
        try:
            data = request_json(API, params={
                "text": term, "period": 3, "per_page": 30,
                "page": 0, "order_by": "publication_time", "host": "hh.ru",
            })
        except (PermissionError, RuntimeError) as exc:
            return found, [], [str(exc)]
        except (requests.RequestException, ValueError) as exc:
            errors.append("HH API search: " + str(exc)[:130])
            break
        items = data.get("items") or []
        if not isinstance(items, list):
            errors.append("HH API returned invalid vacancies list")
            break
        found += len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id") or "")
            if re.fullmatch(r"\d{5,15}", vid):
                potential[vid] = item
    rows = []
    # Strict cap: avoid hammering HH endpoints and stop after access errors.
    for vid, listing in list(potential.items())[:36]:
        try:
            detail = request_json(API + "/" + vid)
            row = convert(detail)
            if row:
                rows.append(row)
        except (PermissionError, RuntimeError) as exc:
            errors.append(str(exc))
            break
        except (requests.RequestException, ValueError) as exc:
            errors.append("HH vacancy " + vid + ": " + str(exc)[:110])
    return found, rows, errors
