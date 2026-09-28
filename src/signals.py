from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests


def _clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_feed_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def _guess_company(title: str) -> str:
    patterns = (
        r"^(.+?)\s+(?:raises|raised|secures|secured|closes|lands|bags|nabs|gets|receives)\b",
        r"^(.+?)\s+(?:rebrands|rebrand|unveils|launches)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            guess = match.group(1).strip(" :-–—")
            return re.sub(r"\s+", " ", guess)
    return ""


def _detect_signal_type(text: str, config: dict[str, Any]) -> str:
    lowered = text.casefold()
    for signal_type in ("rebrand", "funding", "expansion"):
        for keyword in config.get("signal_keywords", {}).get(signal_type, []):
            if keyword.casefold() in lowered:
                return signal_type
    return ""


def _score_signal(signal: dict[str, Any]) -> int:
    score = {
        "rebrand": 70,
        "funding": 65,
        "expansion": 55,
    }.get(str(signal.get("signal_type") or ""), 0)

    published = str(signal.get("published_at") or "")
    if published:
        try:
            age = max(0, (date.today() - date.fromisoformat(published)).days)
            if age <= 3:
                score += 15
            elif age <= 7:
                score += 10
            elif age <= 14:
                score += 5
        except ValueError:
            pass

    title = str(signal.get("title") or "")
    if re.search(r"(?:\$|€|£)\s?\d|\b\d+(?:\.\d+)?\s?(?:m|million|bn|billion)\b", title, re.I):
        score += 10
    if re.search(r"\bseries\s+[ab]\b", title, re.I):
        score += 10
    if signal.get("company_guess"):
        score += 5

    return min(100, score)


def _rss_items(root: ET.Element) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for node in root.findall(".//item"):
        items.append(
            {
                "title": (node.findtext("title") or "").strip(),
                "url": (node.findtext("link") or "").strip(),
                "published": (node.findtext("pubDate") or "").strip(),
                "summary": (node.findtext("description") or "").strip(),
            }
        )

    if items:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for node in root.findall(".//atom:entry", ns):
        link = node.find("atom:link", ns)
        items.append(
            {
                "title": (node.findtext("atom:title", default="", namespaces=ns) or "").strip(),
                "url": str(link.get("href") if link is not None else "").strip(),
                "published": (
                    node.findtext("atom:published", default="", namespaces=ns)
                    or node.findtext("atom:updated", default="", namespaces=ns)
                    or ""
                ).strip(),
                "summary": (
                    node.findtext("atom:summary", default="", namespaces=ns)
                    or node.findtext("atom:content", default="", namespaces=ns)
                    or ""
                ).strip(),
            }
        )
    return items


def fetch_commercial_signals(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    signals: list[dict[str, Any]] = []
    warnings: list[str] = []
    lookback_days = int(config.get("lookback_days", 14))

    for feed in config.get("signal_feeds", []):
        name = str(feed.get("name") or "").strip()
        url = str(feed.get("url") or "").strip()
        if not url:
            continue
        try:
            response = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "searchorders/0.1 (+https://github.com/famesel7-coder/searchorders)"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            warnings.append(f"{name or url} signal feed failed: {exc}")
            continue

        for item in _rss_items(root):
            title = _clean_html(item["title"])
            summary = _clean_html(item["summary"])
            published_at = _parse_feed_date(item["published"])
            if published_at:
                try:
                    if (date.today() - date.fromisoformat(published_at)).days > lookback_days:
                        continue
                except ValueError:
                    pass

            # High precision first: require the buying signal to be visible in the headline.
            signal_type = _detect_signal_type(title, config)
            if not signal_type:
                continue

            item_url = item["url"]
            fingerprint = hashlib.sha1(f"{name}|{title}|{item_url}".encode("utf-8")).hexdigest()[:16]
            signal = {
                "id": f"signal:{fingerprint}",
                "source": name,
                "signal_type": signal_type,
                "title": title,
                "company_guess": _guess_company(title),
                "published_at": published_at,
                "publisher_domain": urlparse(item_url).netloc.lower(),
                "url": item_url,
                "summary": summary[:1000],
                "status": "needs_enrichment",
            }
            signal["score"] = _score_signal(signal)
            signals.append(signal)

    unique: dict[str, dict[str, Any]] = {}
    for signal in signals:
        key = str(signal.get("url") or signal.get("id"))
        if key not in unique or int(signal["score"]) > int(unique[key]["score"]):
            unique[key] = signal

    return sorted(
        unique.values(),
        key=lambda item: (int(item.get("score", 0)), str(item.get("published_at") or "")),
        reverse=True,
    ), warnings
