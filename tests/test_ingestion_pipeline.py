import tempfile
import unittest
from pathlib import Path

from printcare.ingestion.fetch import FetchError
from printcare.ingestion.models import DocumentRef
from printcare.ingestion.pipeline import run_ingestion
from printcare.ingestion.store import IngestStore

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_page.html"
HTML = FIXTURE.read_text(encoding="utf-8")
REFS = [
    DocumentRef(locale="en", path="a1-mini/troubleshooting/a", title="Doc A"),
    DocumentRef(locale="en", path="a1-mini/troubleshooting/b", title="Doc B"),
]


def fetch_all(_ref):
    return HTML


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = IngestStore(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_dry_run_parses_without_writing(self):
        report = run_ingestion(REFS, fetch_all, None)

        self.assertEqual(report.parsed, 2)
        self.assertEqual(report.inserted, 0)
        self.assertEqual(report.failed, 0)
        self.assertEqual(self.store.count_documents(), 0)

    def test_first_run_inserts_and_records_run(self):
        report = run_ingestion(REFS, fetch_all, self.store)

        self.assertEqual((report.inserted, report.updated, report.unchanged), (2, 0, 0))
        self.assertEqual(self.store.count_documents(), 2)
        self.assertEqual(self.store.failures_for_run(report.run_id), [])

    def test_second_run_is_unchanged(self):
        run_ingestion(REFS, fetch_all, self.store)
        report = run_ingestion(REFS, fetch_all, self.store)

        self.assertEqual((report.inserted, report.unchanged), (0, 2))

    def test_changed_page_updates_existing_document(self):
        run_ingestion(REFS, fetch_all, self.store)
        changed = HTML.replace("Power off the printer.", "Unplug the printer.")

        report = run_ingestion(REFS, lambda _ref: changed, self.store)

        self.assertEqual((report.updated, report.inserted), (2, 0))

    def test_fetch_failure_is_recorded_and_others_continue(self):
        def fetch_some(ref):
            if ref.path.endswith("/b"):
                raise FetchError("HTTP 500 for test")
            return HTML

        report = run_ingestion(REFS, fetch_some, self.store)

        self.assertEqual((report.inserted, report.failed), (1, 1))
        self.assertEqual(report.failures[0].stage, "fetch")
        recorded = self.store.failures_for_run(report.run_id)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].error_type, "FetchError")

    def test_parse_failure_is_recorded_with_stage(self):
        def fetch_garbage(ref):
            if ref.path.endswith("/b"):
                return "<html><body>no template</body></html>"
            return HTML

        report = run_ingestion(REFS, fetch_garbage, self.store)

        self.assertEqual((report.inserted, report.failed), (1, 1))
        self.assertEqual(report.failures[0].stage, "parse")
        self.assertEqual(report.failures[0].error_type, "ParseError")

    def test_failure_message_is_bounded_and_single_line(self):
        def fetch_broken(_ref):
            raise FetchError("boom\nwith newline " + "x" * 1000)

        report = run_ingestion(REFS[:1], fetch_broken, self.store)

        message = report.failures[0].message
        self.assertLessEqual(len(message), 300)
        self.assertNotIn("\n", message)

    def test_deactivate_missing_only_when_requested(self):
        run_ingestion(REFS, fetch_all, self.store)
        report = run_ingestion(REFS[:1], fetch_all, self.store, deactivate_missing=True)

        self.assertEqual(report.disabled, 1)
        self.assertEqual(self.store.count_documents(enabled_only=True), 1)

    def test_deactivate_missing_is_skipped_by_default(self):
        run_ingestion(REFS, fetch_all, self.store)
        report = run_ingestion(REFS[:1], fetch_all, self.store)

        self.assertEqual(report.disabled, 0)
        self.assertEqual(self.store.count_documents(enabled_only=True), 2)


if __name__ == "__main__":
    unittest.main()
