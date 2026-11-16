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
        self._indexes: dict[str, tuple[BM25Index, BM25Index, list[ChunkRecord]]] = {}

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

        index, titles, chunks = self._index_for(machine)
        if not chunks:
            return RetrievalResult(machine=machine, query=query, detected_machines=detected)

        # Model selection is already enforced above. Model-name tokens should
        # not make unrelated manuals/FAQs look relevant to a technical query.
        query_tokens = tuple(token for token in tokenize(query) if token not in {"a1", "mini"})
        scores = [
            body + 2.0 * title
            for body, title in zip(
                index.scores(query_tokens), titles.scores(query_tokens), strict=True
            )
        ]
        if any(term in query for term in ("怎么", "如何", "步骤", "处理", "清理", "排查", "检查")):
            title_scores = titles.scores(query_tokens)
            for position, chunk in enumerate(chunks):
                heading = " ".join(chunk.heading_path).lower()
                if "解决方案" in heading or "solution" in heading:
                    # When the title matches a how-to query, expose the actual
                    # procedure rather than only the definition/applicability.
                    scores[position] += 2.0 * title_scores[position]
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
        # Reserve room for other documents before allowing a long page to fill
        # the result window. Backfill if the corpus has too few distinct pages.
        counts: dict[str, int] = {}
        diverse, deferred = [], []
        for pair in ranked:
            doc_id = pair[1].doc_id
            if counts.get(doc_id, 0) < 2:
                diverse.append(pair)
                counts[doc_id] = counts.get(doc_id, 0) + 1
            else:
                deferred.append(pair)
        selected = (diverse + deferred)[: max(0, limit)]
        selected.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
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
            for score, chunk in selected
        )
        return RetrievalResult(
            machine=machine,
            query=query,
            hits=hits,
            detected_machines=detected,
        )

    def _index_for(self, machine: str) -> tuple[BM25Index, BM25Index, list[ChunkRecord]]:
        cached = self._indexes.get(machine)
        if cached is not None:
            return cached
        chunks = [chunk for chunk in self.chunks if machine in chunk.machines]
        index = BM25Index([tokenize(f"{chunk.title} {chunk.text}") for chunk in chunks])
        titles = BM25Index([tokenize(chunk.title) for chunk in chunks])
        self._indexes[machine] = (index, titles, chunks)
        return index, titles, chunks
