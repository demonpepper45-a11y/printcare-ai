"""Read chunks from the runtime SQLite database produced by ingestion."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from printcare.retrieval.models import ChunkRecord


def load_chunks(db_path: str | Path, machine: str | None = None) -> list[ChunkRecord]:
    """Load enabled chunks, optionally restricted to one machine.

    The database is opened read-only; a missing database is a usage error and
    surfaces as ``FileNotFoundError`` rather than an empty result.
    """
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"runtime database not found: {path}")

    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.text, c.heading_path, c.anchor, c.machines,
                   c.official_updated_at, c.retrieved_at,
                   d.source_url, d.title, d.section
              FROM chunks c
              JOIN documents d ON d.doc_id = c.doc_id
             WHERE d.enabled = 1
             ORDER BY c.doc_id, c.ordinal
            """
        ).fetchall()
    finally:
        connection.close()

    records: list[ChunkRecord] = []
    for row in rows:
        machines = tuple(json.loads(row["machines"]))
        if machine is not None and machine not in machines:
            continue
        records.append(
            ChunkRecord(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                text=row["text"],
                heading_path=tuple(json.loads(row["heading_path"])),
                anchor=row["anchor"],
                source_url=row["source_url"],
                title=row["title"],
                machines=machines,
                section=row["section"],
                official_updated_at=row["official_updated_at"],
                retrieved_at=row["retrieved_at"],
            )
        )
    return records
