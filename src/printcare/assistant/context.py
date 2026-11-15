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
    """Keep only citations that point to a provided source and quote it verbatim."""
    by_label = {source.label: source for source in sources}
    citations: list[Citation] = []
    seen: set[str] = set()
    dropped = 0
    if not isinstance(raw_citations, list):
        return (), 0

    for item in raw_citations:
        if not isinstance(item, dict):
            dropped += 1
            continue
        label = str(item.get("source") or "")
        quote = str(item.get("quote") or "")
        source = by_label.get(label)
        if source is None or not quote.strip():
            dropped += 1
            continue
        hit = source.hit
        normalized_text = normalize_whitespace(hit.text)
        normalized_quote = normalize_whitespace(quote)
        if not normalized_quote or normalized_quote not in normalized_text:
            dropped += 1
            continue
        truncated = len(normalized_quote) > max_quote
        if truncated:
            normalized_quote = normalized_quote[:max_quote]
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
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
    return tuple(citations), dropped
