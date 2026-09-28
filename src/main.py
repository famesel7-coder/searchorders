from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dashboard import build_dashboard
from scoring import score_curated_lead, score_lead
from signals import fetch_commercial_signals
from sources import fetch_sam, fetch_ted, fetch_uk
from translator import translate_leads, translate_signals

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "search_config.json"
DEFAULT_OUTPUT_DIR = ROOT / "data"
DEFAULT_CURATED_LEADS = ROOT / "data" / "curated_leads.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_curated_leads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    leads = payload.get("leads", []) if isinstance(payload, dict) else []
    return leads if isinstance(leads, list) else []


def _fingerprint_text(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^a-z0-9\u00c0-\u024f\u0400-\u04ff]+", " ", text).strip()


def dedupe(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_projects: set[str] = set()
    result: list[dict[str, Any]] = []

    for lead in leads:
        lead_id = str(lead.get("id") or "").strip()
        title = _fingerprint_text(lead.get("title"))
        company = _fingerprint_text(lead.get("company"))
        project_key = f"{company}|{title}" if company and title else ""

        if lead_id and lead_id in seen_ids:
            continue
        if project_key and project_key in seen_projects:
            continue

        if lead_id:
            seen_ids.add(lead_id)
        if project_key:
            seen_projects.add(project_key)
        result.append(lead)

    return result


def collect(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    leads: list[dict[str, Any]] = []
    warnings: list[str] = []

    for name, fetcher in (
        ("TED", fetch_ted),
        ("UK Find a Tender", fetch_uk),
    ):
        try:
            leads.extend(fetcher(config))
        except Exception as exc:  # one source should not kill the whole run
            warnings.append(f"{name} failed: {exc}")

    if config.get("sam", {}).get("enabled", True) and not os.getenv("SAM_API_KEY"):
        warnings.append("SAM.gov skipped: SAM_API_KEY is not set")
    else:
        try:
            leads.extend(fetch_sam(config))
        except Exception as exc:
            warnings.append(f"SAM.gov failed: {exc}")

    return dedupe(leads), warnings


def rank(leads: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = [score_lead(lead, config) for lead in leads]
    minimum = int(config.get("minimum_score", 0))
    ranked = [lead for lead in ranked if int(lead.get("score", 0)) >= minimum]
    return sorted(
        ranked,
        key=lambda lead: (
            int(lead.get("score", 0)),
            str(lead.get("published_at") or ""),
        ),
        reverse=True,
    )


def public_lead(lead: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in lead.items() if key != "raw"}


def save_outputs(leads: list[dict[str, Any]], output_dir: Path, warnings: list[str]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    json_path = output_dir / "leads_latest.json"
    payload = {
        "generated_at": generated_at,
        "count": len(leads),
        "warnings": warnings,
        "leads": [public_lead(lead) for lead in leads],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "leads_latest.csv"
    columns = [
        "score", "base_confidence", "fit_adjustment", "source", "title_ru", "title",
        "company", "country", "published_at", "deadline", "value", "currency",
        "primary_cpv", "services", "url", "fit_reasons", "score_reasons",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for lead in leads:
            row = public_lead(lead)
            writer.writerow(
                {
                    key: "; ".join(str(x) for x in row.get(key, []))
                    if isinstance(row.get(key), list)
                    else row.get(key, "")
                    for key in columns
                }
            )

    return json_path, csv_path


def save_signal_outputs(
    signals: list[dict[str, Any]],
    output_dir: Path,
    warnings: list[str],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    json_path = output_dir / "signals_latest.json"
    payload = {
        "generated_at": generated_at,
        "count": len(signals),
        "warnings": warnings,
        "signals": signals,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "signals_latest.csv"
    columns = [
        "score", "signal_type", "source", "company_guess", "title_ru", "title",
        "published_at", "publisher_domain", "url", "status",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for signal in signals:
            writer.writerow({key: signal.get(key, "") for key in columns})

    return json_path, csv_path


def print_signal_summary(signals: list[dict[str, Any]], warnings: list[str], limit: int) -> None:
    print(f"Commercial signals: {len(signals)}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    for index, signal in enumerate(signals[:limit], start=1):
        company = signal.get("company_guess") or "(company needs enrichment)"
        print(
            f"{index:>2}. [{signal.get('score', 0):>3}] {signal.get('signal_type')} | "
            f"{company} | {signal.get('title') or '(no title)'}\n"
            f"    {signal.get('url') or ''}"
        )


def print_summary(leads: list[dict[str, Any]], warnings: list[str], limit: int) -> None:
    print(f"Curated leads: {len(leads)}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    for index, lead in enumerate(leads[:limit], start=1):
        value = lead.get("value")
        currency = lead.get("currency") or ""
        value_text = f" | {value} {currency}" if value not in (None, "") else ""
        fit_score = lead.get("fit_score", lead.get("score", lead.get("confidence", 0)))
        conclusion = lead.get("conclusion", "")
        print(
            f"{index:>2}. [{fit_score:>3}] {conclusion} | {lead.get('company') or '(unknown company)'} | "
            f"{lead.get('title_ru') or lead.get('title') or '(no title)'}"
            f"{value_text}\n    {lead.get('url') or ''}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Find and rank international project leads for I’MON")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top", type=int, default=20, help="How many leads to print")
    args = parser.parse_args()

    config = load_config(args.config)

    if config.get("strategy", {}).get("tenders_enabled", False):
        raw_leads, warnings = collect(config)
        leads = rank(raw_leads, config)
        leads = translate_leads(
            leads,
            config,
            args.output_dir / "translation_cache.json",
        )
    else:
        warnings = []
        leads = [score_curated_lead(lead, config) for lead in load_curated_leads(DEFAULT_CURATED_LEADS)]
        conclusion_priority = {"strong": 2, "verify_more": 1, "reject": 0}
        leads = sorted(
            leads,
            key=lambda lead: (
                conclusion_priority.get(str(lead.get("conclusion") or ""), 0),
                int(lead.get("fit_score", 0)),
                str(lead.get("published_at") or ""),
            ),
            reverse=True,
        )

    json_path, csv_path = save_outputs(leads, args.output_dir, warnings)
    print_summary(leads, warnings, args.top)
    print(f"\nSaved: {json_path}")
    print(f"Saved: {csv_path}")

    signals, signal_warnings = fetch_commercial_signals(config)
    signals = translate_signals(
        signals,
        config,
        args.output_dir / "translation_cache.json",
    )
    signal_json_path, signal_csv_path = save_signal_outputs(signals, args.output_dir, signal_warnings)
    print()
    print_signal_summary(signals, signal_warnings, args.top)
    print(f"\nSaved: {signal_json_path}")
    print(f"Saved: {signal_csv_path}")

    dashboard_path = build_dashboard(
        [public_lead(lead) for lead in leads],
        signals,
        args.output_dir / "dashboard.html",
    )
    print(f"Saved: {dashboard_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
