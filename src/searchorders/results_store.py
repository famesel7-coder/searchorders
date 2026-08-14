from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_results_payload(evaluations: list[Any]) -> dict[str, Any]:
    counts = Counter(item.score.bucket for item in evaluations)
    return {
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


def write_results(path: Path, evaluations: list[Any]) -> None:
    payload = build_results_payload(evaluations)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def read_results(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None
