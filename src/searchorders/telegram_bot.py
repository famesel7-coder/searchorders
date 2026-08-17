from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import LeadEvaluation
from .scan import ScanResult


BUTTON_CALLBACK = "run_search"
MAX_TELEGRAM_TEXT = 4096


class TelegramBotError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str, *, timeout: float = 45.0) -> None:
        if not token:
            raise TelegramBotError("TELEGRAM_BOT_TOKEN is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/{method}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise TelegramBotError(f"Telegram returned HTTP {exc.code} for {method}") from exc
        except URLError as exc:
            raise TelegramBotError(f"Could not reach Telegram: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise TelegramBotError("Telegram returned invalid JSON") from exc
        if not isinstance(result, dict) or not result.get("ok"):
            description = result.get("description", "unknown error") if isinstance(result, dict) else "invalid response"
            raise TelegramBotError(f"Telegram {method} failed: {description}")
        return result.get("result")

    def get_updates(self, *, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self.call("getUpdates", payload)
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:MAX_TELEGRAM_TEXT],
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> Any:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        return self.call("answerCallbackQuery", payload)


def search_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🚀 Запустить поиск", "callback_data": BUTTON_CALLBACK}]
        ]
    }


def source_keyboard(url: str | None) -> dict[str, Any] | None:
    if not url:
        return None
    return {"inline_keyboard": [[{"text": "Открыть заказ", "url": url}]]}


def _budget(evaluation: LeadEvaluation) -> str | None:
    lead = evaluation.lead
    if lead.salary_from and lead.salary_to:
        return f"{lead.salary_from:,}–{lead.salary_to:,} {lead.currency or ''}".replace(",", " ").strip()
    if lead.salary_from:
        return f"от {lead.salary_from:,} {lead.currency or ''}".replace(",", " ").strip()
    if lead.salary_to:
        return f"до {lead.salary_to:,} {lead.currency or ''}".replace(",", " ").strip()
    return None


def render_evaluation(evaluation: LeadEvaluation) -> str:
    icon = {"hot": "🔥", "review": "🟡", "archive": "⚪", "rejected": "⛔"}.get(
        evaluation.score.bucket,
        "•",
    )
    lines = [
        f"{icon} {evaluation.score.total}/100 — {evaluation.lead.title}",
        f"Источник: {evaluation.lead.source}",
    ]
    budget = _budget(evaluation)
    if budget:
        lines.append(f"Бюджет: {budget}")
    if evaluation.score.reasons:
        lines.append(f"Почему подходит: {'; '.join(evaluation.score.reasons[:3])}")
    if evaluation.matched_case:
        lines.append(f"Кейс: {evaluation.matched_case.name} — {evaluation.matched_case.url}")
    if evaluation.proposal_draft:
        lines.extend(["", "Черновик предложения:", evaluation.proposal_draft])
    return "\n".join(lines)[:MAX_TELEGRAM_TEXT]


class SearchOrdersBot:
    def __init__(
        self,
        api: TelegramAPI,
        scan: Callable[[], ScanResult],
        *,
        allowed_chat_id: str | None,
        max_leads_per_run: int = 7,
    ) -> None:
        self.api = api
        self.scan = scan
        self.allowed_chat_id = str(allowed_chat_id).strip() if allowed_chat_id else None
        self.max_leads_per_run = max(1, max_leads_per_run)

    def _authorized(self, chat_id: str | int | None) -> bool:
        return chat_id is not None and self.allowed_chat_id is not None and str(chat_id) == self.allowed_chat_id

    def _run_search(self, chat_id: str | int) -> None:
        self.api.send_message(chat_id, "Ищу новые проектные заказы и проверяю релевантность…")
        try:
            result = self.scan()
        except Exception as exc:  # keep the bot alive; details remain in server logs
            print(f"Search failed: {exc}", file=sys.stderr)
            self.api.send_message(
                chat_id,
                "Поиск завершился ошибкой источника. Подробности сохранены в логах сервера.",
                reply_markup=search_keyboard(),
            )
            return

        candidates = [
            item for item in result.evaluations if item.score.bucket in {"hot", "review"}
        ][: self.max_leads_per_run]
        summary = (
            f"Проверено: {result.collected_count}\n"
            f"Новых: {result.new_count}\n"
            f"Подходящих: {len(candidates)}"
        )
        if result.warnings:
            summary += f"\nПредупреждений источников: {len(result.warnings)}"
        self.api.send_message(chat_id, summary)

        if not candidates:
            self.api.send_message(
                chat_id,
                "Новых подходящих заказов пока нет.",
                reply_markup=search_keyboard(),
            )
            return
        for evaluation in candidates:
            self.api.send_message(
                chat_id,
                render_evaluation(evaluation),
                reply_markup=source_keyboard(evaluation.lead.url),
            )
        self.api.send_message(chat_id, "Поиск завершён.", reply_markup=search_keyboard())

    def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            callback_id = str(callback.get("id", ""))
            message = callback.get("message") or {}
            chat = message.get("chat") if isinstance(message, dict) else {}
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if not self._authorized(chat_id):
                if callback_id:
                    self.api.answer_callback_query(
                        callback_id,
                        text="Нет доступа",
                        show_alert=True,
                    )
                return
            if callback_id:
                self.api.answer_callback_query(callback_id, text="Поиск запущен")
            if callback.get("data") == BUTTON_CALLBACK:
                self._run_search(chat_id)
            return

        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        text = str(message.get("text", "")).strip()
        if chat_id is None:
            return
        if self.allowed_chat_id is None:
            if text.startswith("/start"):
                self.api.send_message(
                    chat_id,
                    f"Ваш TELEGRAM_CHAT_ID: {chat_id}\nДобавьте его в .env и перезапустите контейнер.",
                )
            return
        if not self._authorized(chat_id):
            return
        if text.startswith("/start"):
            self.api.send_message(
                chat_id,
                "I’MON Search Orders готов. Нажмите кнопку для немедленного прогона.",
                reply_markup=search_keyboard(),
            )
        elif text.startswith("/search"):
            self._run_search(chat_id)

    def run_forever(self) -> None:
        offset: int | None = None
        while True:
            try:
                updates = self.api.get_updates(offset=offset, timeout=30)
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    self.handle_update(update)
            except TelegramBotError as exc:
                print(f"Telegram polling error: {exc}", file=sys.stderr)
                time.sleep(5)


def api_from_environment() -> TelegramAPI:
    return TelegramAPI(os.getenv("TELEGRAM_BOT_TOKEN", ""))

