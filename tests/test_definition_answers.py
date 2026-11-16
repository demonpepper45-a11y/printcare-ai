"""Task 2: keep official meanings while retaining procedural safety guards."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from printcare.assistant.assistant import Assistant
from printcare.assistant.context import build_sources
from printcare.assistant.definitions import find_hms_definition
from printcare.assistant.policy import is_definition_question
from printcare.assistant.provider import FakeProvider
from printcare.assistant.session import Session
from printcare.ingestion.store import IngestStore
from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import add_document
from tests.test_assistant import answered_payload

CODE = "HMS_0300-0100-0001-0008"


class DefinitionAnswerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "definitions.sqlite3"
        store = IngestStore(path)
        add_document(
            store,
            locale="zh",
            path="a1/hms",
            machines=("a1",),
            title=f"{CODE}: 热床加热过程中出现异常，加热模块可能故障。",
            texts=("断电后拆下底盖，测量热床电阻。",),
        )
        store.close()
        self.retriever = Retriever.from_sqlite(str(path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_definition_uses_official_title_without_repair_generation(self):
        for question in (
            f"{CODE}是什么意思？只解释错误定义，不要维修步骤。",
            f"不需要拆卸热床，我只想了解{CODE}的含义。",
        ):
            with self.subTest(question=question):
                provider = FakeProvider([])
                session = Session.create("a1")
                result = Assistant(self.retriever, provider).answer(question, "a1", session)
                self.assertEqual(result.status, "answered")
                self.assertIn("加热模块可能故障", result.answer)
                self.assertNotIn("仅提供官方指南", result.answer)
                self.assertNotIn("测量", result.answer)
                self.assertEqual(
                    result.citations[0].quote, "热床加热过程中出现异常，加热模块可能故障"
                )
                self.assertEqual(provider.calls, [])
                self.assertIsNone(result.usage)
                self.assertEqual(len(session.history), 1)

    def test_mixed_question_still_uses_procedural_guard(self):
        provider = FakeProvider(
            answered_payload(
                answer="拆下底盖，测量热床电阻 [S1]。",
                citations=[{"source": "S1", "quote": "断电后拆下底盖"}],
            )
        )
        result = Assistant(self.retriever, provider).answer(f"{CODE}的含义和维修步骤是什么？", "a1")
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("仅提供官方指南", result.answer)

    def test_machine_conflict_precedes_definition(self):
        result = Assistant(self.retriever, FakeProvider([])).answer(
            f"A1 {CODE}是什么意思？", "a1_mini"
        )
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.citations, ())

    def test_unknown_or_multiple_codes_do_not_borrow_another_definition(self):
        sources = build_sources(self.retriever.query(CODE, "a1", 8).hits)
        for question in (
            "HMS_0300-0100-0001-0099是什么意思？",
            f"{CODE}和0300_0100_0001_0099分别是什么意思？",
        ):
            with self.subTest(question=question):
                self.assertIsNone(find_hms_definition(question, sources))

    def test_official_title_instruction_is_not_part_of_definition(self):
        source = build_sources(self.retriever.query(CODE, "a1", 8).hits)[0]
        hit = replace(source.hit, title=f"{CODE}: 电机转动受阻，请检查同步带。")
        selected = find_hms_definition(f"{CODE}是什么意思？", build_sources([hit]))
        self.assertEqual(selected[1], "电机转动受阻")
        unsafe = replace(source.hit, title=f"{CODE}: Reinstall the hotend")
        self.assertIsNone(find_hms_definition(f"{CODE}是什么意思？", build_sources([unsafe])))

    def test_intent_classification_preserves_positive_action_after_negation(self):
        for question in (
            "错误码的含义和怎么排查？",
            "只问定义，但是告诉我接线步骤。",
            "不要维修说明，但请测量热床电阻并解释含义。",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_definition_question(question))
        self.assertTrue(is_definition_question("同步带是什么？不要维修步骤。"))

    def test_term_definition_prompt_does_not_disable_safety_guard(self):
        provider = FakeProvider(
            answered_payload(
                answer="热床传感器需要拆下底盖测量电阻 [S1]。",
                citations=[{"source": "S1", "quote": "断电后拆下底盖"}],
            )
        )
        result = Assistant(self.retriever, provider).answer("热床电阻是什么？只解释含义。", "a1")
        self.assertIn("不主动添加维修", provider.calls[0][1]["content"])
        self.assertIn("仅提供官方指南", result.answer)
