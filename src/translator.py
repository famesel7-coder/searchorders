from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

MYMEMORY_URL = "https://api.mymemory.translated.net/get"

COUNTRY_SOURCE_LANG = {
    "DEU": "de",
    "GERMANY": "de",
    "NLD": "nl",
    "NETHERLANDS": "nl",
    "GBR": "en",
    "GB": "en",
    "UK": "en",
    "UNITED KINGDOM": "en",
    "USA": "en",
    "US": "en",
    "UNITED STATES": "en",
    "CHE": "de",
    "SWITZERLAND": "de",
}


class TranslationCache:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = {str(k): str(v) for k, v in loaded.items()}
            except Exception:
                self.data = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _source_lang(record: dict[str, Any], default: str = "en") -> str:
    country = str(record.get("country") or "").strip().upper()
    return COUNTRY_SOURCE_LANG.get(country, default)


def _translate_text(
    text: str,
    source_lang: str,
    target_lang: str,
    cache: TranslationCache,
    delay_seconds: float,
    max_chars: int,
) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""

    trimmed = cleaned[:max_chars]
    cache_key = f"{source_lang}|{target_lang}|{trimmed}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            MYMEMORY_URL,
            params={"q": trimmed, "langpair": f"{source_lang}|{target_lang}"},
            headers={"User-Agent": "searchorders/0.1"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        translated = str(
            (payload.get("responseData") or {}).get("translatedText") or ""
        ).strip()
        if not translated:
            translated = trimmed
    except Exception:
        translated = trimmed

    cache.set(cache_key, translated)
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    return translated


def translate_leads(
    leads: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
) -> list[dict[str, Any]]:
    translation = config.get("translation", {})
    if not translation.get("enabled", True):
        return leads

    target = str(translation.get("target", "ru"))
    delay = float(translation.get("request_delay_seconds", 0.25))
    max_chars = int(translation.get("max_chars_per_field", 900))
    cache = TranslationCache(cache_path)

    out: list[dict[str, Any]] = []
    for lead in leads:
        source = _source_lang(lead)
        translated = dict(lead)
        translated["title_ru"] = _translate_text(
            str(lead.get("title") or ""), source, target, cache, delay, max_chars
        )
        translated["description_ru"] = _translate_text(
            str(lead.get("description") or ""), source, target, cache, delay, max_chars
        )
        out.append(translated)

    cache.save()
    return out


def translate_signals(
    signals: list[dict[str, Any]],
    config: dict[str, Any],
    cache_path: Path,
) -> list[dict[str, Any]]:
    translation = config.get("translation", {})
    if not translation.get("enabled", True):
        return signals

    target = str(translation.get("target", "ru"))
    delay = float(translation.get("request_delay_seconds", 0.25))
    max_chars = int(translation.get("max_chars_per_field", 900))
    cache = TranslationCache(cache_path)

    out: list[dict[str, Any]] = []
    for signal in signals:
        translated = dict(signal)
        translated["title_ru"] = _translate_text(
            str(signal.get("title") or ""), "en", target, cache, delay, max_chars
        )
        translated["summary_ru"] = _translate_text(
            str(signal.get("summary") or ""), "en", target, cache, delay, max_chars
        )
        out.append(translated)

    cache.save()
    return out
