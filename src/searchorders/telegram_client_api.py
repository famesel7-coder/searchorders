from __future__ import annotations

import asyncio
import getpass
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class TelegramClientSetupError(RuntimeError):
    pass


@dataclass(slots=True)
class TelegramClientCredentials:
    api_id: int
    api_hash: str
    session_string: str


def _import_telethon() -> tuple[Any, Any, Any]:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
        from telethon.sessions import StringSession
    except ImportError as exc:  # pragma: no cover - depends on local install state
        raise TelegramClientSetupError(
            "Telethon is not installed. Run `pip install -e .` to enable Telegram search."
        ) from exc
    return TelegramClient, StringSession, SessionPasswordNeededError


def resolve_telegram_credentials(
    *,
    api_id: int | None = None,
    api_hash: str | None = None,
    session_string: str | None = None,
    api_id_env: str = "TELEGRAM_API_ID",
    api_hash_env: str = "TELEGRAM_API_HASH",
    session_env: str = "TELEGRAM_SESSION",
    require_session: bool = True,
) -> TelegramClientCredentials:
    api_id_value = str(api_id if api_id is not None else os.getenv(api_id_env, "")).strip()
    api_hash_value = str(api_hash if api_hash is not None else os.getenv(api_hash_env, "")).strip()
    session_value = str(
        session_string if session_string is not None else os.getenv(session_env, "")
    ).strip()

    if not api_id_value:
        raise TelegramClientSetupError(
            f"{api_id_env} is required. Create it at https://my.telegram.org under API development tools."
        )
    if not api_hash_value:
        raise TelegramClientSetupError(
            f"{api_hash_env} is required. Create it at https://my.telegram.org under API development tools."
        )
    try:
        parsed_api_id = int(api_id_value)
    except ValueError as exc:
        raise TelegramClientSetupError(f"{api_id_env} must be an integer") from exc
    if require_session and not session_value:
        raise TelegramClientSetupError(
            f"{session_env} is empty. Run `search-orders telegram-auth` first."
        )
    return TelegramClientCredentials(
        api_id=parsed_api_id,
        api_hash=api_hash_value,
        session_string=session_value,
    )


def create_telegram_client(
    *,
    api_id: int | None = None,
    api_hash: str | None = None,
    session_string: str | None = None,
    api_id_env: str = "TELEGRAM_API_ID",
    api_hash_env: str = "TELEGRAM_API_HASH",
    session_env: str = "TELEGRAM_SESSION",
    require_session: bool = True,
) -> Any:
    TelegramClient, StringSession, _ = _import_telethon()
    credentials = resolve_telegram_credentials(
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        api_id_env=api_id_env,
        api_hash_env=api_hash_env,
        session_env=session_env,
        require_session=require_session,
    )
    return TelegramClient(
        StringSession(credentials.session_string),
        credentials.api_id,
        credentials.api_hash,
    )


async def create_telegram_session(
    *,
    api_id: int | None = None,
    api_hash: str | None = None,
    phone: str,
    code_callback: Callable[[], str] | None = None,
    password_callback: Callable[[], str] | None = None,
    api_id_env: str = "TELEGRAM_API_ID",
    api_hash_env: str = "TELEGRAM_API_HASH",
) -> str:
    TelegramClient, StringSession, SessionPasswordNeededError = _import_telethon()
    credentials = resolve_telegram_credentials(
        api_id=api_id,
        api_hash=api_hash,
        session_string="",
        api_id_env=api_id_env,
        api_hash_env=api_hash_env,
        require_session=False,
    )
    session = StringSession()
    client = TelegramClient(session, credentials.api_id, credentials.api_hash)
    code_reader = code_callback or (lambda: input("Telegram code: ").strip())
    password_reader = password_callback or (
        lambda: getpass.getpass("Telegram 2FA password: ").strip()
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            try:
                await client.sign_in(phone=phone, code=code_reader())
            except SessionPasswordNeededError:
                password = password_reader()
                if not password:
                    raise TelegramClientSetupError("Telegram 2FA password is required")
                await client.sign_in(password=password)
        session_string = client.session.save()
        if not session_string:
            raise TelegramClientSetupError("Could not save Telegram session string")
        return session_string
    finally:
        await client.disconnect()


async def list_telegram_dialogs(
    *,
    limit: int = 100,
    api_id: int | None = None,
    api_hash: str | None = None,
    session_string: str | None = None,
    api_id_env: str = "TELEGRAM_API_ID",
    api_hash_env: str = "TELEGRAM_API_HASH",
    session_env: str = "TELEGRAM_SESSION",
) -> list[dict[str, Any]]:
    client = create_telegram_client(
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        api_id_env=api_id_env,
        api_hash_env=api_hash_env,
        session_env=session_env,
        require_session=True,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise TelegramClientSetupError(
                "Telegram session is not authorized. Run `search-orders telegram-auth` again."
            )
        rows: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs(limit=max(1, limit)):
            entity = dialog.entity
            username = getattr(entity, "username", None)
            if username:
                ref = f"@{username}"
            else:
                ref = str(dialog.id)
            dialog_type = "user"
            if getattr(dialog, "is_channel", False):
                dialog_type = "megagroup" if getattr(entity, "megagroup", False) else "channel"
            elif getattr(dialog, "is_group", False):
                dialog_type = "group"
            rows.append(
                {
                    "id": str(dialog.id),
                    "type": dialog_type,
                    "name": str(dialog.name or ref),
                    "username": username or "",
                    "ref": ref,
                }
            )
        return rows
    finally:
        await client.disconnect()


def create_telegram_session_sync(**kwargs: Any) -> str:
    return asyncio.run(create_telegram_session(**kwargs))


def list_telegram_dialogs_sync(**kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(list_telegram_dialogs(**kwargs))
