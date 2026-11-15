"""Persistence for Telegram public-channel discovery sources.

Only source URLs are managed here. Existing lead/outreach history is never changed.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

_URL = re.compile(r"https://t\.me/(?:s/)?([A-Za-z0-9_]{5,32})/?", re.I)
_LOCK = threading.RLock()


def canonical_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Требуется ссылка на публичный Telegram-канал")
    match = _URL.fullmatch(value.strip())
    if not match:
        raise ValueError("Ожидалась ссылка https://t.me/s/channel без параметров")
    return "https://t.me/s/" + match.group(1).lower()


def _read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, list):
        raise ValueError(f"Неверный формат реестра источников: {path.name}")
    return result


def _atomic_list(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _configured_sources(registry: Path, state: Path) -> list[str]:
    source_registry = json.loads(registry.read_text(encoding="utf-8"))["source_registry"]
    configured = [
        canonical_url(item["url"])
        for item in source_registry
        if item.get("tier") == "telegram_primary"
    ]
    configured += [
        canonical_url(item) for item in _read_list(state / "extra_sources.json")
    ]
    return list(dict.fromkeys(configured))


def list_sources(registry: Path, state: Path) -> list[str]:
    with _LOCK:
        sources = _configured_sources(registry, state)
        excluded = {canonical_url(item) for item in _read_list(state / "excluded_sources.json")}
        return [source for source in sources if source not in excluded]


def remove_source(url: str, registry: Path, state: Path) -> dict:
    target = canonical_url(url)
    with _LOCK:
        active = list_sources(registry, state)
        if target not in active:
            return {"ok": True, "removed": False, "sources": len(active)}
        excluded = {canonical_url(item) for item in _read_list(state / "excluded_sources.json")}
        excluded.add(target)
        _atomic_list(state / "excluded_sources.json", sorted(excluded))
        after = list_sources(registry, state)
        if target in after:
            raise RuntimeError("Источник не был исключён; проверьте реестр")
        return {"ok": True, "removed": True, "sources": len(after)}


def add_source(url: str, registry: Path, state: Path) -> dict:
    target = canonical_url(url)
    with _LOCK:
        active = list_sources(registry, state)
        if target in active:
            return {"ok": True, "added": False, "message": "Источник уже отслеживается", "sources": len(active)}
        excluded = {canonical_url(item) for item in _read_list(state / "excluded_sources.json")}
        if target in excluded:
            excluded.remove(target)
            _atomic_list(state / "excluded_sources.json", sorted(excluded))
        else:
            extra = [canonical_url(item) for item in _read_list(state / "extra_sources.json")]
            if target not in extra:
                extra.append(target)
                _atomic_list(state / "extra_sources.json", extra)
        after = list_sources(registry, state)
        if target not in after:
            raise RuntimeError("Источник не появился в реестре")
        return {"ok": True, "added": True, "sources": len(after)}
