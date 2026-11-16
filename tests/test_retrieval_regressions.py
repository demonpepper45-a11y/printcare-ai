"""Small adversarial corpora for colloquial terms and long-page crowding."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from printcare.ingestion.store import IngestStore
from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import add_document


class RetrievalRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.sqlite3"
        self.store = IngestStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, path, title, texts, machine="a1"):
        return add_document(
            self.store, locale="zh", path=path, machines=(machine,), title=title, texts=texts
        )

    def test_belt_alias_and_long_page_do_not_hide_maintenance(self):
        target = self.add("a1/maintenance/belt", "同步带张紧", ("松动时请调整张力。",))
        self.add(
            "a1/troubleshooting/noise",
            "同步带松动故障排查",
            tuple(f"同步带松动导致噪声，调整同步带张力，检查位置 {n}。" for n in range(12)),
        )
        hits = Retriever.from_sqlite(str(self.path)).query("皮带松了怎么调张力？", "a1", 5).hits
        self.assertIn(target, {hit.doc_id for hit in hits})
        self.assertEqual(len(hits), 5)  # Backfill when only two documents exist.
        self.assertEqual([hit.score for hit in hits], sorted((h.score for h in hits), reverse=True))

    def test_first_layer_alias_matches_title_and_keeps_machine_filter(self):
        target = self.add(
            "a1-mini/troubleshooting/first", "首层打印问题", ("清洁打印板后再试。",), "a1_mini"
        )
        self.add("a1/troubleshooting/first", "第一层粘不住", ("检查首层。",))
        hits = (
            Retriever.from_sqlite(str(self.path))
            .query("A1 mini 第一层太薄粘不住怎么办？", "a1_mini", 5)
            .hits
        )
        self.assertEqual(hits[0].doc_id, target)
        self.assertTrue(all(hit.machines == ("a1_mini",) for hit in hits))

    def test_model_name_alone_does_not_match_unrelated_manual(self):
        self.add("a1-mini/manual", "A1 mini 用户手册", ("欢迎使用设备。",), "a1_mini")
        result = Retriever.from_sqlite(str(self.path)).query("A1 mini zzzz", "a1_mini")
        self.assertEqual(result.hits, ())

    def test_how_to_query_retrieves_solution_instead_of_only_definition(self):
        self.add(
            "first-layer",
            "首层打印问题",
            ("首层太薄的定义。", "首层太薄：运行打印校准。"),
            "a1_mini",
        )
        retriever = Retriever.from_sqlite(str(self.path))
        chunks = [
            replace(chunk, heading_path=("解决方案", "步骤1"))
            if "校准" in chunk.text
            else replace(chunk, heading_path=("问题定义",))
            for chunk in retriever.chunks
        ]
        hits = Retriever(chunks).query("A1 mini 第一层太薄怎么办？", "a1_mini", 1).hits
        self.assertIn("校准", hits[0].text)
