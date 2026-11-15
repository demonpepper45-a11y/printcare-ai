import tempfile
import unittest
from pathlib import Path

from printcare.retrieval.retriever import Retriever, UnsupportedMachineError
from printcare.retrieval.source import load_chunks
from tests.retrieval_corpus import build_corpus


class MachineFilterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "retrieval.sqlite3"
        self.store = build_corpus(self.db_path)
        self.store.close()
        self.retriever = Retriever.from_sqlite(str(self.db_path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a1_results_never_include_a1_mini_only_chunks(self):
        result = self.retriever.query("热床不加热 检查", "a1")

        self.assertTrue(result.hits)
        self.assertTrue(all("a1" in hit.machines for hit in result.hits))
        self.assertFalse(any("A1 mini" in hit.title for hit in result.hits))

    def test_a1_mini_results_never_include_a1_only_chunks(self):
        result = self.retriever.query("热床不加热 检查", "a1_mini")

        self.assertTrue(result.hits)
        self.assertTrue(all("a1_mini" in hit.machines for hit in result.hits))
        self.assertFalse(any(hit.title == "A1 热床不加热排查" for hit in result.hits))

    def test_shared_document_is_available_for_both_machines(self):
        for machine in ("a1", "a1_mini"):
            result = self.retriever.query("传感器 通用 检查", machine)

            titles = [hit.title for hit in result.hits]
            self.assertIn("热床温度传感器通用检查", titles)

    def test_unsupported_machine_raises(self):
        with self.assertRaises(UnsupportedMachineError):
            self.retriever.query("热床", "x1")

    def test_chunk_source_is_also_filtered(self):
        chunks = load_chunks(self.db_path, machine="a1_mini")

        self.assertTrue(chunks)
        self.assertTrue(all("a1_mini" in chunk.machines for chunk in chunks))

    def test_missing_database_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_chunks(Path(self.tmp.name) / "missing.sqlite3")

    def test_machine_counts(self):
        self.assertEqual(self.retriever.machine_count("a1"), 4)
        self.assertEqual(self.retriever.machine_count("a1_mini"), 4)


if __name__ == "__main__":
    unittest.main()
