import tempfile
import unittest
from pathlib import Path

from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import build_corpus


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "retrieval.sqlite3"
        build_corpus(self.db_path).close()
        self.retriever = Retriever.from_sqlite(str(self.db_path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_chinese_question_returns_relevant_chunk(self):
        result = self.retriever.query("A1 热床不加热怎么检查", "a1")

        self.assertIsNone(result.warning)
        self.assertEqual(result.hits[0].title, "A1 热床不加热排查")
        self.assertEqual(result.detected_machines, ("a1",))

    def test_exact_model_mention_matches_selected_machine(self):
        result = self.retriever.query("A1 mini 热床不加热怎么检查", "a1_mini")

        self.assertIsNone(result.warning)
        self.assertEqual(result.hits[0].title, "A1 mini 热床不加热排查")

    def test_mismatched_model_is_not_answered(self):
        result = self.retriever.query("A1 mini 热床不加热怎么检查", "a1")

        self.assertEqual(result.warning, "machine_mismatch")
        self.assertEqual(result.hits, ())
        self.assertEqual(result.detected_machines, ("a1_mini",))

    def test_unsupported_model_mention_warns(self):
        result = self.retriever.query("X1C 热床不加热怎么检查", "a1")

        self.assertEqual(result.warning, "unsupported_machine_mentioned")
        self.assertEqual(result.hits, ())

    def test_hms_code_is_found_for_the_right_machine(self):
        result = self.retriever.query("HMS_0300-1800-0001-0001", "a1_mini")

        self.assertIsNone(result.warning)
        self.assertTrue(result.hits)
        self.assertIn("0300-1800-0001-0001", result.hits[0].title)

    def test_hms_code_of_other_machine_returns_nothing(self):
        result = self.retriever.query("HMS_0300-1800-0001-0001", "a1")

        self.assertEqual(result.hits, ())
        self.assertIsNone(result.warning)

    def test_empty_question_returns_no_hits(self):
        result = self.retriever.query("   ", "a1")

        self.assertEqual(result.hits, ())
        self.assertEqual(result.query, "")

    def test_limit_is_respected(self):
        result = self.retriever.query("热床", "a1", limit=1)

        self.assertEqual(len(result.hits), 1)

    def test_hits_carry_citation_metadata(self):
        hit = self.retriever.query("A1 热床不加热", "a1").hits[0]

        self.assertTrue(hit.source_url.startswith("https://wiki.bambulab.com/"))
        self.assertEqual(hit.official_updated_at, "2026-11-10T00:00:00Z")
        self.assertEqual(hit.machines, ("a1",))
        self.assertTrue(hit.chunk_id.startswith("doc_"))

    def test_scores_are_descending(self):
        hits = self.retriever.query("热床 不加热 检查", "a1_mini").hits
        scores = [hit.score for hit in hits]

        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
