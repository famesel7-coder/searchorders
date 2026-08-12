from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    pass


def load_yaml(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        raise ConfigurationError(f"Configuration file does not exist: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"Expected a mapping in {resolved}")
    return data


def load_search_profile(path: str | Path) -> dict[str, Any]:
    profile = load_yaml(path)
    required = ("services", "lead_filters", "scoring", "proposal")
    missing = [key for key in required if key not in profile]
    if missing:
        raise ConfigurationError(
            f"Search profile is missing required sections: {', '.join(missing)}"
        )
    return profile


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ConfigurationError("Case catalog must contain a 'cases' list")
    return [case for case in cases if isinstance(case, dict)]

