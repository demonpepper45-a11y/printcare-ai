"""Build model context from retrieval hits and validate returned citations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from printcare.assistant.provider import strip_code_fence
from printcare.ingestion.ids import normalize_whitespace
from printcare.retrieval.models import RetrievalHit

MAX_QUOTE_CHARS = 200
MAX_SOURCE_CHARS = 1200


class ModelOutputError(RuntimeError):
    """Raised when the model output cannot be parsed as the agreed JSON object."""


@dataclass(frozen=True)
class CitationDrop:
    """Why one model-provided citation was discarded."""

    source: str
    reason: str
    quote_length: int = 0
    attempt: int = 1


@dataclass(frozen=True)
class Source:
    label: str
    hit: RetrievalHit


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    doc_id: str
    title: str
    source_url: str
    section_path: tuple[str, ...]
    anchor: str | None
    machine: str
    official_updated_at: str | None
    quote: str
    quote_truncated: bool


def build_sources(hits: tuple[RetrievalHit, ...] | list[RetrievalHit]) -> list[Source]:
    return [Source(label=f"S{index}", hit=hit) for index, hit in enumerate(hits, start=1)]


def select_sources(
    hits: tuple[RetrievalHit, ...] | list[RetrievalHit],
    max_per_doc: int = 3,
) -> list[RetrievalHit]:
    """Keep the ranked order but limit how many chunks one document can occupy.

    Long maintenance pages often produce many near-duplicate chunks that would
    otherwise crowd other documents out of the model context.
    """
    counts: dict[str, int] = {}
    selected: list[RetrievalHit] = []
    for hit in hits:
        used = counts.get(hit.doc_id, 0)
        if used >= max_per_doc:
            continue
        counts[hit.doc_id] = used + 1
        selected.append(hit)
    return selected


def format_sources(sources: list[Source], max_chars: int = MAX_SOURCE_CHARS) -> str:
    blocks: list[str] = []
    for source in sources:
        hit = source.hit
        text = hit.text
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        heading = " > ".join(hit.heading_path) or "-"
        blocks.append(
            f"[{source.label}] 标题：{hit.title}\n"
            f"章节：{heading}\n"
            f"机型：{', '.join(hit.machines)}\n"
            f"官方更新时间：{hit.official_updated_at or '未知'}\n"
            f"原文：{text}"
        )
    return "\n\n".join(blocks)


def parse_model_payload(raw: str) -> dict[str, Any]:
    text = strip_code_fence(raw)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelOutputError("model output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ModelOutputError("model output is not a JSON object")
    return payload


def validate_citations(
    raw_citations: Any,
    sources: list[Source],
    *,
    machine: str,
    max_quote: int = MAX_QUOTE_CHARS,
) -> tuple[tuple[Citation, ...], int]:
    """Compatibility wrapper around :func:`validate_citations_with_audit`."""
    citations, drops = validate_citations_with_audit(
        raw_citations, sources, machine=machine, max_quote=max_quote
    )
    return citations, len(drops)


def validate_citations_with_audit(
    raw_citations: Any,
    sources: list[Source],
    *,
    machine: str,
    max_quote: int = MAX_QUOTE_CHARS,
    attempt: int = 1,
) -> tuple[tuple[Citation, ...], tuple[CitationDrop, ...]]:
    """Keep citations that point to a provided source and quote visible text.

    Every discarded item is returned with a machine-readable reason so failures
    can be diagnosed without logging answer or page text.
    """
    by_label = {source.label: source for source in sources}
    citations: list[Citation] = []
    drops: list[CitationDrop] = []
    seen: set[str] = set()
    if not isinstance(raw_citations, list):
        return (), ()

    for item in raw_citations:
        if not isinstance(item, dict):
            drops.append(CitationDrop(source="-", reason="invalid_item", attempt=attempt))
            continue
        label = str(item.get("source") or "")
        quote = str(item.get("quote") or "")
        source = by_label.get(label)
        if source is None:
            drops.append(
                CitationDrop(
                    source=label or "-",
                    reason="unknown_source",
                    quote_length=len(quote),
                    attempt=attempt,
                )
            )
            continue
        if not quote.strip():
            drops.append(CitationDrop(source=label, reason="empty_quote", attempt=attempt))
            continue
        hit = source.hit
        visible_fields = (hit.title, hit.text[:MAX_SOURCE_CHARS])
        normalized_fields = tuple(normalize_whitespace(field) for field in visible_fields)
        normalized_quote = normalize_whitespace(quote)
        if not normalized_quote or not any(
            normalized_quote in field for field in normalized_fields
        ):
            drops.append(
                CitationDrop(
                    source=label,
                    reason="quote_not_found",
                    quote_length=len(normalized_quote),
                    attempt=attempt,
                )
            )
            continue
        if hit.chunk_id in seen:
            drops.append(CitationDrop(source=label, reason="duplicate_source", attempt=attempt))
            continue
        seen.add(hit.chunk_id)
        truncated = len(normalized_quote) > max_quote
        if truncated:
            normalized_quote = normalized_quote[:max_quote]
        citations.append(
            Citation(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                title=hit.title,
                source_url=hit.source_url,
                section_path=hit.heading_path,
                anchor=hit.anchor,
                machine=machine,
                official_updated_at=hit.official_updated_at,
                quote=normalized_quote,
                quote_truncated=truncated,
            )
        )
    return tuple(citations), tuple(drops)
