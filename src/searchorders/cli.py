from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigurationError, load_cases, load_search_profile, load_sources
from .models import Lead
from .pipeline import evaluate_leads
from .scan import scan_sources
from .telegram_bot import SearchOrdersBot, TelegramBotError, api_from_environment


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


def _write_results(path: Path, evaluations: list[Any]) -> None:
    counts = Counter(item.score.bucket for item in evaluations)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(evaluations),
            "hot": counts["hot"],
            "review": counts["review"],
            "archive": counts["archive"],
            "rejected": counts["rejected"],
        },
        "items": [item.to_dict() for item in evaluations],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default="data/search-profile.yaml", type=Path)
    parser.add_argument("--cases", default="data/cases.yaml", type=Path)
    parser.add_argument("--output", default="output/leads.json", type=Path)


def _scan_paths(parser: argparse.ArgumentParser) -> None:
    _common_paths(parser)
    parser.add_argument("--sources", default="data/sources.yaml", type=Path)
    parser.add_argument("--state", default="state/searchorders.db", type=Path)
    parser.add_argument("--max-results", type=int, default=30)


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

    bot = subparsers.add_parser("bot", help="Run the protected Telegram search button")
    _scan_paths(bot)
    bot.add_argument("--max-leads-per-run", type=int, default=7)
    return parser


def run_evaluate(
    args: argparse.Namespace,
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
) -> int:
    leads = _read_leads(args.input)
    evaluations = evaluate_leads(leads, profile, cases)
    _write_results(args.output, evaluations)
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
    _write_results(args.output, result.evaluations)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        profile = load_search_profile(args.profile)
        cases = load_cases(args.cases)
        if args.command == "evaluate":
            return run_evaluate(args, profile, cases)
        if args.command == "scan":
            return run_scan(args, profile, cases)
        if args.command == "bot":
            return run_bot(args, profile, cases)
    except (ConfigurationError, OSError, TelegramBotError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
