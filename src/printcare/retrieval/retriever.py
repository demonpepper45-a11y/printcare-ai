"""Machine-filtered keyword retrieval over ingested wiki chunks.

Machines are a hard filter: a chunk is only searchable for the machines listed
in its metadata. Questions that mention another machine, or an unsupported
model, return no hits and a warning instead of cross-machine results.
"""

from __future__ import annotations

from collections.abc import Sequence

from printcare.retrieval.bm25 import BM25Index
from printcare.retrieval.models import ChunkRecord, RetrievalHit, RetrievalResult
from printcare.retrieval.source import load_chunks
from printcare.retrieval.tokenize import (
    detect_machines,
    detect_unsupported_models,
    extract_hms_codes,
    normalize_hms,
    tokenize,
)

SUPPORTED_MACHINES = ("a1", "a1_mini")
DEFAULT_LIMIT = 5
EXACT_CODE_BOOST = 5.0


class UnsupportedMachineError(ValueError):
    """Raised when the requested machine is not part of the first version."""


class Retriever:
    """In-memory BM25 index built from runtime chunks."""

    def __init__(self, chunks: Sequence[ChunkRecord]) -> None:
        self.chunks = tuple(chunks)
        self._indexes: dict[str, tuple[BM25Index, list[ChunkRecord]]] = {}

    @classmethod
    def from_sqlite(cls, db_path: str) -> Retriever:
        return cls(load_chunks(db_path))

    def machine_count(self, machine: str) -> int:
        return sum(1 for chunk in self.chunks if machine in chunk.machines)

    def query(
        self,
        question: str,
        machine: str,
        limit: int = DEFAULT_LIMIT,
    ) -> RetrievalResult:
        if machine not in SUPPORTED_MACHINES:
            raise UnsupportedMachineError(f"machine must be one of {', '.join(SUPPORTED_MACHINES)}")
        query = question.strip()
        detected = detect_machines(query)
        unsupported = detect_unsupported_models(query)

        if unsupported:
            return RetrievalResult(
                machine=machine,
                query=query,
                detected_machines=detected,
                warning="unsupported_machine_mentioned",
            )
        if detected and set(detected) != {machine}:
            return RetrievalResult(
                machine=machine,
                query=query,
                detected_machines=detected,
                warning="machine_mismatch",
            )
        if not query:
            return RetrievalResult(machine=machine, query=query)

        index, chunks = self._index_for(machine)
        if not chunks:
            return RetrievalResult(machine=machine, query=query, detected_machines=detected)

        scores = index.scores(tokenize(query))
        codes = {normalize_hms(code) for code in extract_hms_codes(query)}
        if codes:
            for position, chunk in enumerate(chunks):
                haystack = f"{chunk.title} {chunk.text}".upper()
                if any(code in haystack for code in codes):
                    scores[position] += EXACT_CODE_BOOST

        ranked = sorted(
            ((score, chunk) for score, chunk in zip(scores, chunks, strict=True) if score > 0),
            key=lambda pair: (-pair[0], pair[1].chunk_id),
        )
        hits = tuple(
            RetrievalHit(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                score=round(score, 4),
                text=chunk.text,
                heading_path=chunk.heading_path,
                anchor=chunk.anchor,
                source_url=chunk.source_url,
                title=chunk.title,
                machines=chunk.machines,
                section=chunk.section,
                official_updated_at=chunk.official_updated_at,
            )
            for score, chunk in ranked[:limit]
        )
        return RetrievalResult(
            machine=machine,
            query=query,
            hits=hits,
            detected_machines=detected,
        )

    def _index_for(self, machine: str) -> tuple[BM25Index, list[ChunkRecord]]:
        cached = self._indexes.get(machine)
        if cached is not None:
            return cached
        chunks = [chunk for chunk in self.chunks if machine in chunk.machines]
        index = BM25Index([tokenize(f"{chunk.title} {chunk.text}") for chunk in chunks])
        self._indexes[machine] = (index, chunks)
        return index, chunks
