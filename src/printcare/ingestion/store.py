"""SQLite persistence for documents, chunks and ingestion diagnostics.

The database is a runtime artefact: it lives outside Git (``runtime/`` is
ignored) and stores page text only to keep the local index rebuildable.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from printcare.ingestion.models import Chunk, DocumentRecord, Failure, IngestReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    canonical_path TEXT NOT NULL,
    locale TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    machines TEXT NOT NULL,
    shared_reason TEXT,
    section TEXT NOT NULL,
    official_updated_at TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    ingested_at TEXT NOT NULL,
    UNIQUE (locale, canonical_path)
);

CREATE TABLE IF NOT EXISTS doc_aliases (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    alias_path TEXT NOT NULL,
    PRIMARY KEY (doc_id, alias_path)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading_path TEXT NOT NULL,
    anchor TEXT,
    text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    images TEXT NOT NULL,
    machines TEXT NOT NULL,
    locale TEXT NOT NULL,
    official_updated_at TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_machines ON chunks(machines);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    report_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_failures (
    run_id TEXT NOT NULL REFERENCES ingest_runs(run_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    stage TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


class IngestStore:
    """Small wrapper around SQLite with idempotent upserts."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> IngestStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def upsert_document(self, record: DocumentRecord, chunks: tuple[Chunk, ...]) -> str:
        """Insert or refresh one document; return ``inserted``/``updated``/``unchanged``."""
        existing = self.connection.execute(
            "SELECT content_hash, enabled FROM documents WHERE locale = ? AND canonical_path = ?",
            (record.locale, record.canonical_path),
        ).fetchone()

        if existing is None:
            self._insert_document(record, chunks)
            self.connection.commit()
            return "inserted"

        if existing["content_hash"] == record.content_hash:
            self.connection.execute(
                """
                UPDATE documents
                   SET title = ?, source_url = ?, official_updated_at = ?, retrieved_at = ?,
                       ingested_at = ?, enabled = 1
                 WHERE doc_id = ?
                """,
                (
                    record.title,
                    record.source_url,
                    record.official_updated_at,
                    record.retrieved_at,
                    record.ingested_at,
                    record.doc_id,
                ),
            )
            self.connection.commit()
            return "unchanged"

        self.connection.execute("DELETE FROM chunks WHERE doc_id = ?", (record.doc_id,))
        self.connection.execute(
            """
            UPDATE documents
               SET title = ?, source_url = ?, official_updated_at = ?, retrieved_at = ?,
                   ingested_at = ?, content_hash = ?, enabled = 1
             WHERE doc_id = ?
            """,
            (
                record.title,
                record.source_url,
                record.official_updated_at,
                record.retrieved_at,
                record.ingested_at,
                record.content_hash,
                record.doc_id,
            ),
        )
        self._insert_chunks(record, chunks)
        self.connection.commit()
        return "updated"

    def _insert_document(self, record: DocumentRecord, chunks: tuple[Chunk, ...]) -> None:
        self.connection.execute(
            """
            INSERT INTO documents (doc_id, canonical_path, locale, source_url, title, machines,
                                   shared_reason, section, official_updated_at, retrieved_at,
                                   content_hash, enabled, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.doc_id,
                record.canonical_path,
                record.locale,
                record.source_url,
                record.title,
                json.dumps(list(record.machines)),
                record.shared_reason,
                record.section,
                record.official_updated_at,
                record.retrieved_at,
                record.content_hash,
                int(record.enabled),
                record.ingested_at,
            ),
        )
        self._insert_chunks(record, chunks)

    def _insert_chunks(self, record: DocumentRecord, chunks: tuple[Chunk, ...]) -> None:
        self.connection.executemany(
            """
            INSERT INTO chunks (chunk_id, doc_id, ordinal, heading_path, anchor, text, char_count,
                                images, machines, locale, official_updated_at, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    record.doc_id,
                    chunk.ordinal,
                    json.dumps(list(chunk.heading_path)),
                    chunk.anchor,
                    chunk.text,
                    len(chunk.text),
                    json.dumps([{"src": image.src, "alt": image.alt} for image in chunk.images]),
                    json.dumps(list(record.machines)),
                    record.locale,
                    record.official_updated_at,
                    record.retrieved_at,
                )
                for chunk in chunks
            ],
        )

    def deactivate_missing(self, keep_keys: set[tuple[str, str]]) -> int:
        """Disable documents that were not part of a complete inventory run."""
        rows = self.connection.execute(
            "SELECT doc_id, locale, canonical_path FROM documents WHERE enabled = 1"
        ).fetchall()
        stale = [
            row["doc_id"] for row in rows if (row["locale"], row["canonical_path"]) not in keep_keys
        ]
        if stale:
            self.connection.executemany(
                "UPDATE documents SET enabled = 0 WHERE doc_id = ?",
                [(doc_id,) for doc_id in stale],
            )
            self.connection.commit()
        return len(stale)

    def record_run(self, run_id: str, report: IngestReport) -> None:
        self.connection.execute(
            "INSERT INTO ingest_runs (run_id, started_at, finished_at, report_json) "
            "VALUES (?, ?, ?, ?)",
            (
                run_id,
                report.started_at,
                report.finished_at,
                json.dumps(
                    {
                        "inserted": report.inserted,
                        "updated": report.updated,
                        "unchanged": report.unchanged,
                        "parsed": report.parsed,
                        "failed": report.failed,
                        "disabled": report.disabled,
                    }
                ),
            ),
        )
        self.connection.executemany(
            "INSERT INTO ingest_failures (run_id, source_url, stage, error_type, message) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (run_id, failure.source_url, failure.stage, failure.error_type, failure.message)
                for failure in report.failures
            ],
        )
        self.connection.commit()

    def get_document(self, doc_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return None
        chunks = self.connection.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY ordinal", (doc_id,)
        ).fetchall()
        document = dict(row)
        document["chunks"] = [dict(chunk) for chunk in chunks]
        return document

    def count_documents(self, enabled_only: bool = False) -> int:
        query = "SELECT COUNT(*) FROM documents"
        if enabled_only:
            query += " WHERE enabled = 1"
        return int(self.connection.execute(query).fetchone()[0])

    def count_chunks(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def failures_for_run(self, run_id: str) -> list[Failure]:
        rows = self.connection.execute(
            "SELECT source_url, stage, error_type, message FROM ingest_failures WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return [
            Failure(
                source_url=row["source_url"],
                stage=row["stage"],
                error_type=row["error_type"],
                message=row["message"],
            )
            for row in rows
        ]
