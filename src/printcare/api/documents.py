"""Read and update knowledge-base document status."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

QUERY = """
    SELECT d.doc_id, d.canonical_path, d.locale, d.title, d.machines, d.section,
           d.enabled, d.official_updated_at, d.retrieved_at,
           COUNT(c.chunk_id) AS chunk_count
      FROM documents d
      LEFT JOIN chunks c ON c.doc_id = d.doc_id
     GROUP BY d.doc_id
     ORDER BY d.locale, d.canonical_path
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def list_documents(db_path: str | Path, machine: str | None = None) -> list[dict]:
    connection = _connect(db_path)
    try:
        rows = connection.execute(QUERY).fetchall()
    finally:
        connection.close()

    documents = []
    for row in rows:
        machines = [str(item) for item in json.loads(row["machines"])]
        if machine is not None and machine not in machines:
            continue
        documents.append(
            {
                "doc_id": row["doc_id"],
                "canonical_path": row["canonical_path"],
                "locale": row["locale"],
                "title": row["title"],
                "machines": machines,
                "section": row["section"],
                "enabled": bool(row["enabled"]),
                "official_updated_at": row["official_updated_at"],
                "retrieved_at": row["retrieved_at"],
                "chunk_count": int(row["chunk_count"]),
            }
        )
    return documents


def set_enabled(db_path: str | Path, doc_id: str, enabled: bool) -> bool:
    connection = _connect(db_path)
    try:
        cursor = connection.execute(
            "UPDATE documents SET enabled = ? WHERE doc_id = ?",
            (int(enabled), doc_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def counts(db_path: str | Path) -> tuple[int, int]:
    connection = _connect(db_path)
    try:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return int(documents), int(chunks)
    except sqlite3.Error:
        return 0, 0
    finally:
        connection.close()
