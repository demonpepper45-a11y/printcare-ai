"""Helpers that build a small retrieval corpus for tests."""

from __future__ import annotations

from pathlib import Path

from printcare.ingestion.ids import compute_chunk_id, compute_content_hash, compute_doc_id
from printcare.ingestion.models import Chunk, DocumentRecord
from printcare.ingestion.store import IngestStore

NOW = "2026-11-15T12:00:00Z"
UPDATED = "2026-11-10T00:00:00Z"


def add_document(
    store: IngestStore,
    *,
    locale: str,
    path: str,
    machines: tuple[str, ...],
    title: str,
    texts: tuple[str, ...],
    section: str = "troubleshooting",
) -> str:
    doc_id = compute_doc_id(locale, path)
    chunks = tuple(
        Chunk(
            chunk_id=compute_chunk_id(doc_id, text),
            ordinal=index,
            heading_path=("测试章节",),
            anchor=None,
            text=text,
        )
        for index, text in enumerate(texts)
    )
    record = DocumentRecord(
        doc_id=doc_id,
        canonical_path=path,
        locale=locale,
        source_url=f"https://wiki.bambulab.com/{locale}/{path}",
        title=title,
        machines=machines,
        section=section,
        content_hash=compute_content_hash("\n".join(texts)),
        retrieved_at=NOW,
        ingested_at=NOW,
        official_updated_at=UPDATED,
    )
    store.upsert_document(record, chunks)
    return doc_id


def build_corpus(db_path: Path) -> IngestStore:
    """Two machine-specific documents, one shared document and two HMS pages."""
    store = IngestStore(db_path)
    add_document(
        store,
        locale="zh",
        path="a1/troubleshooting/heatbed",
        machines=("a1",),
        title="A1 热床不加热排查",
        texts=(
            "A1 热床不加热时，先断电，检查热床线缆与电源接口是否插紧。",
            "A1 热床温度异常时，检查热床传感器是否松动。",
        ),
    )
    add_document(
        store,
        locale="zh",
        path="a1-mini/troubleshooting/heatbed",
        machines=("a1_mini",),
        title="A1 mini 热床不加热排查",
        texts=(
            "A1 mini 热床不加热时，检查热床排线，mini 的热床线较细，不要用力拉扯。",
            "A1 mini 热床温度异常时先断电，再检查传感器。",
        ),
    )
    add_document(
        store,
        locale="zh",
        path="a1/troubleshooting/shared-sensor",
        machines=("a1", "a1_mini"),
        title="热床温度传感器通用检查",
        texts=("热床温度传感器检查：断电后测量阻值，两款机型方法一致。",),
    )
    add_document(
        store,
        locale="en",
        path="a1-mini/troubleshooting/hmscode/0300_1800_0001_0001",
        machines=("a1_mini",),
        title="HMS_0300-1800-0001-0001: Extruder eddy current sensor value is too low",
        texts=(
            "HMS_0300-1800-0001-0001 extruder eddy current sensor is abnormal; check the cable.",
        ),
    )
    add_document(
        store,
        locale="en",
        path="a1/troubleshooting/hmscode/0300_0100_0001_0008",
        machines=("a1",),
        title="HMS_0300-0100-0001-0008: Heating process abnormal",
        texts=("HMS_0300-0100-0001-0008 heating process abnormal; check the heatbed connector.",),
    )
    return store
