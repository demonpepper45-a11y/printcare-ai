"""SQLite-backed feedback storage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    solved INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class FeedbackStore:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        connection = self._connect()
        try:
            connection.executescript(SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def add(self, session_id: str, solved: bool, comment: str | None = None) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO feedback (session_id, solved, comment, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, int(solved), comment, _now()),
            )
            connection.commit()
            return int(cursor.lastrowid or 0)
        finally:
            connection.close()

    def summary(self) -> dict[str, int]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS total, SUM(solved) AS solved FROM feedback"
            ).fetchone()
        finally:
            connection.close()
        total = int(row["total"] or 0)
        solved = int(row["solved"] or 0)
        return {"total": total, "solved": solved, "unsolved": total - solved}
