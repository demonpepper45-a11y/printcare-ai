"""Orchestrate inventory → fetch → parse → store for one ingestion run.

Failures are recorded per document so a partial run stays diagnosable; the
pipeline never aborts because one page is broken.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from printcare.ingestion.fetch import FetchError
from printcare.ingestion.models import (
    DocumentRecord,
    DocumentRef,
    Failure,
    IngestReport,
    ParsedDocument,
)
from printcare.ingestion.parse import ParseError, parse_document
from printcare.ingestion.store import IngestStore

Fetcher = Callable[[DocumentRef], str]
Parser = Callable[[str, DocumentRef], ParsedDocument]
Clock = Callable[[], str]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_ingestion(
    refs: Sequence[DocumentRef],
    fetch: Fetcher,
    store: IngestStore | None = None,
    *,
    parser: Parser = parse_document,
    deactivate_missing: bool = False,
    now: Clock = utc_now,
    run_id: str | None = None,
) -> IngestReport:
    """Ingest a batch of documents and return a per-run summary."""
    report = IngestReport(started_at=now())
    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
    report.run_id = run_id

    for ref in refs:
        try:
            html = fetch(ref)
        except FetchError as exc:
            _record_failure(report, ref, "fetch", exc)
            continue
        except Exception as exc:  # noqa: BLE001 - unexpected transport errors are recorded too
            _record_failure(report, ref, "fetch", exc)
            continue

        try:
            parsed = parser(html, ref)
        except ParseError as exc:
            _record_failure(report, ref, "parse", exc)
            continue
        except Exception as exc:  # noqa: BLE001 - parser bugs should not stop the batch
            _record_failure(report, ref, "parse", exc)
            continue

        report.parsed += 1
        if store is None:
            continue

        record = DocumentRecord(
            doc_id=parsed.doc_id,
            canonical_path=ref.path,
            locale=ref.locale,
            source_url=ref.source_url,
            title=ref.title or parsed.title,
            machines=(ref.machine,),
            section=ref.section,
            content_hash=parsed.content_hash,
            retrieved_at=now(),
            ingested_at=now(),
            official_updated_at=ref.official_updated_at,
        )
        try:
            outcome = store.upsert_document(record, parsed.chunks)
        except Exception as exc:  # noqa: BLE001 - storage failures stay per document
            _record_failure(report, ref, "store", exc)
            continue
        if outcome == "inserted":
            report.inserted += 1
        elif outcome == "updated":
            report.updated += 1
        else:
            report.unchanged += 1

    if store is not None:
        if deactivate_missing:
            report.disabled = store.deactivate_missing({(ref.locale, ref.path) for ref in refs})
        report.finished_at = now()
        store.record_run(run_id, report)
    else:
        report.finished_at = now()
    return report


def _record_failure(report: IngestReport, ref: DocumentRef, stage: str, error: Exception) -> None:
    message = " ".join(str(error).split())[:300] or type(error).__name__
    report.failed += 1
    report.failures.append(
        Failure(
            source_url=ref.source_url,
            stage=stage,
            error_type=type(error).__name__,
            message=message,
        )
    )
