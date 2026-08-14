from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ConfigurationError, load_cases, load_search_profile, load_sources
from .models import Lead
from .pipeline import evaluate_leads
from .results_store import write_results
from .scan import scan_sources
from .telegram_bot import SearchOrdersBot, TelegramBotError, api_from_environment
from .telegram_client_api import (
    TelegramClientSetupError,
    create_telegram_session_sync,
    list_telegram_dialogs_sync,
)
from .web import serve_web


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _lead_from_dict(data: dict[str, Any]) -> Lead:
    return Lead(
        source=str(data.get("source", "fixture")),
        external_id=str(data.get("external_id", data.get("id", "unknown"))),
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        url=data.get("url"),
        company_name=data.get("company_name"),
        company_url=data.get("company_url"),
        published_at=_parse_datetime(data.get("published_at")),
        area=data.get("area"),
        employment=data.get("employment"),
        schedule=data.get("schedule"),
        accept_temporary=bool(data.get("accept_temporary", False)),
        salary_from=data.get("salary_from"),
        salary_to=data.get("salary_to"),
        currency=data.get("currency"),
        has_direct_contact=bool(data.get("has_direct_contact", False)),
        raw=data.get("raw", {}) if isinstance(data.get("raw", {}), dict) else {},
    )


def _read_leads(path: Path) -> list[Lead]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("leads", payload.get("items", []))
    if not isinstance(payload, list):
        raise ValueError("Input JSON must be a list or contain a 'leads'/'items' list")
    return [_lead_from_dict(item) for item in payload if isinstance(item, dict)]


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default="data/search-profile.yaml", type=Path)
    parser.add_argument("--cases", default="data/cases.yaml", type=Path)
    parser.add_argument("--output", default="output/leads.json", type=Path)


def _scan_paths(parser: argparse.ArgumentParser) -> None:
    _common_paths(parser)
    parser.add_argument("--sources", default="data/sources.yaml", type=Path)
    parser.add_argument("--state", default="state/searchorders.db", type=Path)
    parser.add_argument("--max-results", type=int, default=30)


def _telegram_credentials_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-id", type=int)
    parser.add_argument("--api-hash")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search-orders",
        description="Find and qualify project leads for I’MON Digital Agency",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate leads from a local JSON file")
    _common_paths(evaluate)
    evaluate.add_argument("input", type=Path)

    scan = subparsers.add_parser("scan", help="Collect and evaluate new project leads now")
    _scan_paths(scan)

    web = subparsers.add_parser("web", help="Run a local web UI for manual scans")
    _scan_paths(web)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8080)
    web.add_argument("--title", default="I’MON Search Orders")

    bot = subparsers.add_parser("bot", help="Run the protected Telegram search button")
    _scan_paths(bot)
    bot.add_argument("--max-leads-per-run", type=int, default=7)

    telegram_auth = subparsers.add_parser(
        "telegram-auth",
        help="Create or refresh the Telegram session string for chat and channel search",
    )
    _telegram_credentials_args(telegram_auth)
    telegram_auth.add_argument("--phone")
    telegram_auth.add_argument("--env-file", type=Path, default=Path(".env"))
    telegram_auth.add_argument("--print-only", action="store_true")

    telegram_dialogs = subparsers.add_parser(
        "telegram-dialogs",
        help="List available Telegram chats and channels for source configuration",
    )
    _telegram_credentials_args(telegram_dialogs)
    telegram_dialogs.add_argument("--session")
    telegram_dialogs.add_argument("--limit", type=int, default=100)
    return parser


def run_evaluate(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> int:
    leads = _read_leads(args.input)
    evaluations = evaluate_leads(leads, profile, cases)
    write_results(args.output, evaluations)
    print(f"Saved {len(evaluations)} evaluated leads to {args.output}")
    return 0


def _scan_once(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> Any:
    sources = load_sources(args.sources)
    return scan_sources(
        profile,
        cases,
        sources,
        state_path=args.state,
        max_results=max(1, args.max_results),
    )


def run_scan(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> int:
    result = _scan_once(args, profile, cases)
    write_results(args.output, result.evaluations)
    print(
        f"Collected {result.collected_count}; new {result.new_count}; "
        f"saved {len(result.evaluations)} evaluations to {args.output}"
    )
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


def run_bot(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> int:
    api = api_from_environment()
    bot = SearchOrdersBot(
        api,
        lambda: _scan_once(args, profile, cases),
        allowed_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        max_leads_per_run=max(1, args.max_leads_per_run),
    )
    bot.run_forever()
    return 0


def run_web(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> int:
    server = serve_web(
        lambda: _scan_once(args, profile, cases),
        output_path=args.output,
        host=args.host,
        port=args.port,
        title=args.title,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping web UI...")
    finally:
        server.server_close()
    return 0


def _upsert_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _, _ = line.partition("=")
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    for key, value in remaining.items():
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def run_telegram_auth(args: argparse.Namespace) -> int:
    phone = str(args.phone or "").strip() or input("Telegram phone number: ").strip()
    if not phone:
        raise TelegramClientSetupError("Phone number is required for Telegram login")
    session_string = create_telegram_session_sync(
        api_id=args.api_id,
        api_hash=args.api_hash,
        phone=phone,
    )
    if args.print_only:
        print(session_string)
        return 0
    updates = {"TELEGRAM_SESSION": session_string}
    if args.api_id is not None:
        updates["TELEGRAM_API_ID"] = str(args.api_id)
    if args.api_hash:
        updates["TELEGRAM_API_HASH"] = str(args.api_hash)
    _upsert_env_file(args.env_file, updates)
    print(f"Saved TELEGRAM_SESSION to {args.env_file}")
    return 0


def run_telegram_dialogs(args: argparse.Namespace) -> int:
    rows = list_telegram_dialogs_sync(
        api_id=args.api_id,
        api_hash=args.api_hash,
        session_string=args.session,
        limit=args.limit,
    )
    if not rows:
        print("No Telegram dialogs found.")
        return 0
    for row in rows:
        username = f" @{row['username']}" if row.get("username") else ""
        print(f"{row['type']}\t{row['ref']}\t{row['name']}{username}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "telegram-auth":
            return run_telegram_auth(args)
        if args.command == "telegram-dialogs":
            return run_telegram_dialogs(args)
        profile = load_search_profile(args.profile)
        cases = load_cases(args.cases)
        if args.command == "evaluate":
            return run_evaluate(args, profile, cases)
        if args.command == "scan":
            return run_scan(args, profile, cases)
        if args.command == "web":
            return run_web(args, profile, cases)
        if args.command == "bot":
            return run_bot(args, profile, cases)
    except (
        ConfigurationError,
        OSError,
        TelegramBotError,
        TelegramClientSetupError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
