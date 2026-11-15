"""Data structures for keyword retrieval over ingested chunks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk read back from the runtime database."""

    chunk_id: str
    doc_id: str
    text: str
    heading_path: tuple[str, ...]
    anchor: str | None
    source_url: str
    title: str
    machines: tuple[str, ...]
    section: str
    official_updated_at: str | None
    retrieved_at: str


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    doc_id: str
    score: float
    text: str
    heading_path: tuple[str, ...]
    anchor: str | None
    source_url: str
    title: str
    machines: tuple[str, ...]
    section: str
    official_updated_at: str | None


@dataclass(frozen=True)
class RetrievalResult:
    machine: str
    query: str
    hits: tuple[RetrievalHit, ...] = ()
    detected_machines: tuple[str, ...] = ()
    warning: str | None = None
