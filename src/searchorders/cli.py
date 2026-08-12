from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigurationError, load_cases, load_search_profile
from .models import Lead
from .pipeline import evaluate_leads


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search-orders",
        description="Find and qualify project leads for I’MON Digital Agency",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate leads from a local JSON file")
    _common_paths(evaluate)
    evaluate.add_argument("input", type=Path)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        profile = load_search_profile(args.profile)
        cases = load_cases(args.cases)
        if args.command == "evaluate":
            return run_evaluate(args, profile, cases)
    except (ConfigurationError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
