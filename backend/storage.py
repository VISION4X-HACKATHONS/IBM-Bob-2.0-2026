from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATABASE_PATH = Path(os.environ.get(
    "CODEGUARDIAN_DB_PATH",
    Path(__file__).resolve().parents[1] / ".codeguardian" / "analyses.sqlite3",
))


def _connect(database_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS analyses (
            analysis_id TEXT PRIMARY KEY,
            repository_path TEXT NOT NULL,
            request TEXT NOT NULL,
            created_at TEXT NOT NULL,
            record_json TEXT NOT NULL
        )"""
    )
    return connection


def save_analysis(record: dict[str, Any], database_path: Path = DATABASE_PATH) -> None:
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    with closing(_connect(database_path)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO analyses (analysis_id, repository_path, request, created_at, record_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record["id"],
                record["repository_path"],
                record["result"]["request"],
                record["created_at"],
                json.dumps(record),
            ),
        )
        connection.commit()


def get_analysis(analysis_id: str, database_path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with closing(_connect(database_path)) as connection:
        row = connection.execute(
            "SELECT record_json FROM analyses WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
    return json.loads(row["record_json"]) if row else None


def update_analysis(record: dict[str, Any], database_path: Path = DATABASE_PATH) -> None:
    save_analysis(record, database_path)