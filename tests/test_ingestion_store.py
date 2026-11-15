import sqlite3
import tempfile
import unittest
from pathlib import Path

from printcare.ingestion.models import DocumentRecord, DocumentRef, Failure
from printcare.ingestion.parse import parse_document
from printcare.ingestion.store import IngestStore

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_page.html"
REF = DocumentRef(locale="en", path="a1-mini/troubleshooting/test", title="Extruder cleaning")
RETRIEVED_AT = "2026-11-15T10:00:00Z"


def build_record(parsed, updated_at="2026-11-10T00:00:00Z"):
    return DocumentRecord(
        doc_id=parsed.doc_id,
        canonical_path=REF.path,
        locale=REF.locale,
        source_url=REF.source_url,
        title=REF.title,
        machines=("a1_mini",),
        section="troubleshooting",
        content_hash=parsed.content_hash,
        retrieved_at=RETRIEVED_AT,
        ingested_at=RETRIEVED_AT,
        official_updated_at=updated_at,
    )


class IngestStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        self.store = IngestStore(self.db_path)
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.parsed = parse_document(self.html, REF)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_insert_then_unchanged(self):
        record = build_record(self.parsed)

        self.assertEqual(self.store.upsert_document(record, self.parsed.chunks), "inserted")
        self.assertEqual(self.store.count_documents(), 1)
        self.assertEqual(self.store.count_chunks(), len(self.parsed.chunks))

        self.assertEqual(self.store.upsert_document(record, self.parsed.chunks), "unchanged")
        self.assertEqual(self.store.count_documents(), 1)
        self.assertEqual(self.store.count_chunks(), len(self.parsed.chunks))

    def test_changed_content_replaces_chunks(self):
        self.store.upsert_document(build_record(self.parsed), self.parsed.chunks)
        changed = parse_document(self.html.replace("Power off", "Unplug"), REF)

        outcome = self.store.upsert_document(build_record(changed), changed.chunks)
        self.assertEqual(outcome, "updated")

        document = self.store.get_document(self.parsed.doc_id)
        self.assertEqual(document["content_hash"], changed.content_hash)
        self.assertEqual(self.store.count_chunks(), len(changed.chunks))
        self.assertEqual(
            {chunk["chunk_id"] for chunk in document["chunks"]},
            {chunk.chunk_id for chunk in changed.chunks},
        )

    def test_stored_document_keeps_provenance_fields(self):
        self.store.upsert_document(build_record(self.parsed), self.parsed.chunks)

        document = self.store.get_document(self.parsed.doc_id)
        self.assertEqual(document["source_url"], REF.source_url)
        self.assertEqual(document["official_updated_at"], "2026-11-10T00:00:00Z")
        self.assertEqual(document["section"], "troubleshooting")
        self.assertEqual(document["machines"], '["a1_mini"]')

        chunk = document["chunks"][0]
        self.assertTrue(chunk["heading_path"].startswith("["))
        self.assertEqual(chunk["retrieved_at"], RETRIEVED_AT)
        self.assertGreater(chunk["char_count"], 0)

    def test_deactivate_missing_only_disables_absent_documents(self):
        self.store.upsert_document(build_record(self.parsed), self.parsed.chunks)

        removed = self.store.deactivate_missing(set())

        self.assertEqual(removed, 1)
        self.assertEqual(self.store.count_documents(enabled_only=True), 0)

    def test_deactivate_missing_keeps_present_documents(self):
        self.store.upsert_document(build_record(self.parsed), self.parsed.chunks)

        removed = self.store.deactivate_missing({(REF.locale, REF.path)})

        self.assertEqual(removed, 0)
        self.assertEqual(self.store.count_documents(enabled_only=True), 1)

    def test_run_and_failures_are_persisted(self):
        from printcare.ingestion.models import IngestReport

        report = IngestReport(started_at=RETRIEVED_AT, finished_at=RETRIEVED_AT, failed=1)
        report.failures.append(
            Failure(
                source_url=REF.source_url,
                stage="parse",
                error_type="ParseError",
                message="no content",
            )
        )

        self.store.record_run("run_test", report)

        failures = self.store.failures_for_run("run_test")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].stage, "parse")

    def test_schema_survives_reopen(self):
        self.store.upsert_document(build_record(self.parsed), self.parsed.chunks)
        self.store.close()

        reopened = IngestStore(self.db_path)
        try:
            self.assertEqual(reopened.count_documents(), 1)
        finally:
            reopened.close()

    def test_failed_chunk_insert_rolls_back_document(self):
        duplicated = (self.parsed.chunks[0], self.parsed.chunks[0])

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.upsert_document(build_record(self.parsed), duplicated)

        self.assertEqual(self.store.count_documents(), 0)
        self.assertEqual(self.store.count_chunks(), 0)

    def test_missing_chunks_are_rebuilt_on_reingest(self):
        record = build_record(self.parsed)
        self.store.upsert_document(record, self.parsed.chunks)
        self.store.connection.execute("DELETE FROM chunks WHERE doc_id = ?", (record.doc_id,))
        self.store.connection.commit()

        outcome = self.store.upsert_document(record, self.parsed.chunks)

        self.assertEqual(outcome, "updated")
        self.assertEqual(self.store.count_chunks(), len(self.parsed.chunks))


if __name__ == "__main__":
    unittest.main()
