from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Lead, utc_now


def lead_key(lead: Lead) -> str:
    if lead.external_id:
        material = f"external:{lead.source}:{lead.external_id}"
    elif lead.url:
        material = f"url:{lead.url.rstrip('/')}"
    else:
        material = f"content:{lead.title.casefold()}:{(lead.company_name or '').casefold()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SeenLeadStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS seen_leads (
                        dedup_key TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        external_id TEXT,
                        source_url TEXT,
                        first_seen_at TEXT NOT NULL
                    )
                    """
                )

    def contains(self, lead: Lead) -> bool:
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT 1 FROM seen_leads WHERE dedup_key = ?",
                    (lead_key(lead),),
                ).fetchone()
        return row is not None

    def only_new(self, leads: list[Lead]) -> list[Lead]:
        return [lead for lead in leads if not self.contains(lead)]

    def mark_seen(self, leads: list[Lead]) -> None:
        timestamp = utc_now().isoformat()
        values = [
            (lead_key(lead), lead.source, lead.external_id, lead.url, timestamp)
            for lead in leads
        ]
        if not values:
            return
        with closing(self._connect()) as connection:
            with connection:
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO seen_leads
                        (dedup_key, source, external_id, source_url, first_seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    values,
                )
