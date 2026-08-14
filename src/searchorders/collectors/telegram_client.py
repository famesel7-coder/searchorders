from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..models import Lead
from ..telegram_client_api import TelegramClientSetupError, create_telegram_client


CONTACT_RE = re.compile(r"(telegram|whatsapp|t\.me|vk\.me|@[\w_]{4,}|[\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)


class TelegramClientCollectorError(RuntimeError):
    pass


@dataclass(slots=True)
class _CollectedMessage:
    external_id: str
    title: str
    description: str
    url: str | None
    published_at: datetime | None
    company_name: str


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def _title_from_text(value: str) -> str:
    condensed = " ".join(value.split())
    if len(condensed) <= 100:
        return condensed or "Telegram message"
    return condensed[:97].rstrip() + "..."


def _normalize_entity_ref(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.strip("/")
        if path.startswith("s/"):
            path = path[2:]
        return f"@{path}" if path and not path.startswith(("+", "joinchat/")) else value
    raw = value.strip()
    if raw.startswith("s/"):
        raw = raw[2:]
    if raw.startswith("@") or raw.startswith(("+", "-")):
        return raw
    return f"@{raw}" if raw and not raw.isdigit() else raw


def _message_url(entity: Any, message: Any) -> str | None:
    username = getattr(entity, "username", None)
    message_id = getattr(message, "id", None)
    if username and message_id is not None:
        return f"https://t.me/{username}/{message_id}"
    return None


def _message_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TelegramClientCollector:
    def __init__(
        self,
        listing_urls: list[str],
        *,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        history_limit: int = 200,
        max_details: int = 30,
        api_id_env: str = "TELEGRAM_API_ID",
        api_hash_env: str = "TELEGRAM_API_HASH",
        session_env: str = "TELEGRAM_SESSION",
        client_factory: Any | None = None,
    ) -> None:
        self.entity_refs = [_normalize_entity_ref(item) for item in listing_urls]
        self.include_patterns = [_normalized(item) for item in (include_patterns or []) if str(item).strip()]
        self.exclude_patterns = [_normalized(item) for item in (exclude_patterns or []) if str(item).strip()]
        self.history_limit = max(1, history_limit)
        self.max_details = max(1, max_details)
        self.api_id_env = api_id_env
        self.api_hash_env = api_hash_env
        self.session_env = session_env
        self.client_factory = client_factory
        self.warnings: list[str] = []

    def _build_client(self) -> Any:
        if self.client_factory:
            return self.client_factory(
                api_id_env=self.api_id_env,
                api_hash_env=self.api_hash_env,
                session_env=self.session_env,
            )
        return create_telegram_client(
            api_id_env=self.api_id_env,
            api_hash_env=self.api_hash_env,
            session_env=self.session_env,
            require_session=True,
        )

    def _message_allowed(self, title: str, description: str, company_name: str, url: str | None) -> bool:
        haystack = _normalized("\n".join([title, description, company_name, url or ""]))
        if self.exclude_patterns and any(pattern in haystack for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(pattern in haystack for pattern in self.include_patterns)

    async def _collect_async(self, *, max_results: int | None = None) -> list[Lead]:
        limit = min(self.max_details, max_results or self.max_details)
        client = self._build_client()
        leads: list[Lead] = []
        seen: set[tuple[str, str]] = set()
        try:
            async with client:
                for entity_ref in self.entity_refs:
                    if len(leads) >= limit:
                        break
                    try:
                        entity = await client.get_entity(entity_ref)
                    except Exception as exc:
                        self.warnings.append(f"{entity_ref}: {exc}")
                        continue
                    company_name = str(
                        getattr(entity, "title", None)
                        or getattr(entity, "username", None)
                        or entity_ref
                    )
                    async for message in client.iter_messages(entity, limit=self.history_limit):
                        text = str(
                            getattr(message, "message", None)
                            or getattr(message, "text", None)
                            or ""
                        ).strip()
                        if not text:
                            continue
                        title = _title_from_text(text)
                        url = _message_url(entity, message)
                        if not self._message_allowed(title, text, company_name, url):
                            continue
                        chat_id = getattr(entity, "id", entity_ref)
                        message_id = getattr(message, "id", None)
                        if message_id is None:
                            continue
                        external_id = f"{chat_id}:{message_id}"
                        key = ("telegram_client", external_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        leads.append(
                            Lead(
                                source="telegram_client",
                                external_id=external_id,
                                title=title,
                                description=text[:30000],
                                url=url,
                                company_name=company_name,
                                published_at=_message_datetime(getattr(message, "date", None)),
                                area="Telegram",
                                employment="Авторизованный Telegram-чат",
                                accept_temporary=True,
                                has_direct_contact=bool(CONTACT_RE.search(text)),
                                raw={"entity_ref": entity_ref},
                            )
                        )
                        if len(leads) >= limit:
                            break
        except TelegramClientSetupError as exc:
            raise TelegramClientCollectorError(str(exc)) from exc
        return leads

    def collect(self, *, max_results: int | None = None) -> list[Lead]:
        return asyncio.run(self._collect_async(max_results=max_results))
