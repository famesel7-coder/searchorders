"""One-time channel removal after the live SearchOrders state has been migrated.

Run on the *single* active SearchOrders server after service cutover. Never run
against an empty replacement state to imply the old source list was updated.
"""
from __future__ import annotations
from realtime_service.engine import ROOT, RUNTIME, sources
from realtime_service.source_store import remove_source

CHANNELS = ("vakansii_smm", "vakansii_reelsmaker", "vakansii_copywriters")


def main() -> None:
    before = set(sources())
    targets = {"https://t.me/s/" + name for name in CHANNELS}
    if not targets & before:
        raise SystemExit(
            "Ни один из трёх каналов не найден в этом экземпляре SearchOrders. "
            "Остановлено: сначала проверьте, что это актуальная рабочая база."
        )
    for name in CHANNELS:
        url = "https://t.me/s/" + name
        result = remove_source(url, ROOT / "data/search_sources.json", RUNTIME)
        print(f"{name}: removed={result['removed']}, total={result['sources']}")
    after = set(sources())
    if after & targets:
        raise SystemExit("ERROR: not all excluded channels were removed")
    if after != before - targets:
        raise SystemExit("ERROR: unrelated channel list changed")
    print("Verified: unwanted channels excluded, all other channels preserved.")


if __name__ == "__main__":
    main()
