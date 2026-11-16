"""Safety/tool sections must travel with the maintenance document they belong to."""

import json
import tempfile
import unittest
from pathlib import Path

from printcare.assistant.assistant import Assistant
from printcare.assistant.context import build_sources, include_safety_sources, safety_sources
from printcare.assistant.policy import needs_safety_context
from printcare.assistant.provider import FakeProvider
from printcare.ingestion.store import IngestStore
from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import add_document

SAFETY = "安全提示：维护前请关闭打印机电源并断开电源连接，佩戴隔热手套。"
TOOLS = "- H2.0 内六角扳手、平头镊子。"
STEP = "拆下底盖并断开热床线缆。"
MINI_SAFETY = "A1 mini 安全提示：维护前必须断电，并等待热床冷却。"


class SafetyContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "safety.sqlite3"
        store = IngestStore(db_path)
        self.a1_doc = add_document(
            store,
            locale="zh",
            path="a1/troubleshooting/heatbed",
            machines=("a1",),
            title="A1 热床排查",
            texts=(STEP, SAFETY, TOOLS),
            headings=(("操作步骤",), ("安全提示",), ("所需工具",)),
        )
        self.mini_doc = add_document(
            store,
            locale="zh",
            path="a1-mini/troubleshooting/heatbed",
            machines=("a1_mini",),
            title="A1 mini 热床排查",
            texts=(MINI_SAFETY, "拆下底盖并断开热床线缆。"),
            headings=(("安全提示",), ("操作步骤",)),
        )
        store.close()
        self.retriever = Retriever.from_sqlite(str(db_path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_safety_hits_are_machine_and_document_scoped(self):
        hits = self.retriever.safety_hits({self.a1_doc, self.mini_doc}, "a1")

        self.assertTrue(hits)
        self.assertTrue(all(hit.doc_id == self.a1_doc for hit in hits))
        self.assertTrue(all("A1 mini" not in hit.text for hit in hits))

    def test_safety_sources_are_appended_with_tools_and_no_duplicates(self):
        selected = self.retriever.query("A1 热床怎么拆底盖", "a1", limit=8).hits
        limited = [hit for hit in selected if hit.doc_id == self.a1_doc][:1]
        safety = self.retriever.safety_hits({self.a1_doc}, "a1")

        merged = include_safety_sources(limited, safety)

        self.assertGreater(len(merged), len(limited))
        self.assertEqual(len(merged), len({hit.chunk_id for hit in merged}))
        self.assertEqual(len([hit for hit in merged if hit.doc_id == self.a1_doc]), 3)
        headings = {" ".join(hit.heading_path) for hit in merged}
        self.assertTrue(any("安全提示" in heading for heading in headings))
        self.assertTrue(any("工具" in heading for heading in headings))

    def test_guide_answer_includes_official_safety_text(self):
        payload = json.dumps(
            {
                "status": "answered",
                "answer": "先断电，拆下底盖并断开热床线缆 [S1]。",
                "citations": [{"source": "S1", "quote": STEP}],
                "missing_information": [],
                "follow_up_question": None,
                "refusal_reason": None,
            },
            ensure_ascii=False,
        )
        provider = FakeProvider(payload)
        result = Assistant(self.retriever, provider).answer("A1 热床怎么拆底盖？", "a1")

        self.assertEqual(result.status, "answered")
        self.assertIn("仅提供官方指南入口", result.answer)
        self.assertIn("官方安全前提", result.answer)
        self.assertIn("关闭打印机电源", result.answer)
        self.assertIn("H2.0", result.answer)
        self.assertNotIn("- -", result.answer)
        self.assertTrue(any("安全提示" in citation.section_path for citation in result.citations))
        prompt = provider.calls[0][1]["content"]
        self.assertIn("关闭打印机电源", prompt)
        self.assertNotIn("A1 mini 安全提示", prompt)

    def test_reviewed_document_with_safety_may_keep_steps(self):
        payload = json.dumps(
            {
                "status": "answered",
                "answer": "先断电，拆下底盖并断开热床线缆 [S1]。",
                "citations": [{"source": "S1", "quote": STEP}],
                "missing_information": [],
                "follow_up_question": None,
                "refusal_reason": None,
            },
            ensure_ascii=False,
        )
        result = Assistant(
            self.retriever,
            FakeProvider(payload),
            procedure_allowlist={self.a1_doc},
        ).answer("A1 热床怎么拆底盖？", "a1")

        self.assertEqual(result.status, "answered")
        self.assertIn("拆下底盖", result.answer)
        self.assertNotIn("仅提供官方指南入口", result.answer)

    def test_unreviewed_or_other_document_stays_guide_only(self):
        payload = json.dumps(
            {
                "status": "answered",
                "answer": "先断电，拆下底盖并断开热床线缆 [S1]。",
                "citations": [{"source": "S1", "quote": STEP}],
                "missing_information": [],
                "follow_up_question": None,
                "refusal_reason": None,
            },
            ensure_ascii=False,
        )
        no_allowlist = Assistant(self.retriever, FakeProvider(payload)).answer(
            "A1 热床怎么拆底盖？", "a1"
        )
        other_allowlist = Assistant(
            self.retriever,
            FakeProvider(payload),
            procedure_allowlist={self.mini_doc},
        ).answer("A1 热床怎么拆底盖？", "a1")

        self.assertIn("仅提供官方指南入口", no_allowlist.answer)
        self.assertIn("仅提供官方指南入口", other_allowlist.answer)

    def test_prompt_marks_safety_sources_as_provided(self):
        payload = json.dumps(
            {
                "status": "answered",
                "answer": "先断电，拆下底盖并断开热床线缆 [S1]。",
                "citations": [{"source": "S1", "quote": STEP}],
                "missing_information": [],
                "follow_up_question": None,
                "refusal_reason": None,
            },
            ensure_ascii=False,
        )
        provider = FakeProvider(payload)
        Assistant(self.retriever, provider).answer("A1 热床怎么拆底盖？", "a1")

        prompt = provider.calls[0][1]["content"]
        self.assertIn("本轮已附官方安全提示", prompt)
        self.assertIn("不得声称资料未提供安全前提", prompt)

    def test_definition_question_does_not_need_safety_context(self):
        self.assertFalse(needs_safety_context("HMS_0300-1000-0002-0001 什么意思？"))
        self.assertTrue(needs_safety_context("A1 热床怎么拆底盖？"))

    def test_safety_sources_helper_filters_headings(self):
        hits = self.retriever.safety_hits({self.a1_doc}, "a1")
        sources = build_sources(hits)

        self.assertEqual(len(safety_sources(sources)), len(sources))


if __name__ == "__main__":
    unittest.main()
