"""Regressions for unsafe content actually observed in live-model review."""

import json
import unittest

from printcare.assistant.assistant import BAD_CITATIONS_ANSWER, Assistant
from printcare.assistant.provider import FakeProvider
from tests import test_assistant as fixtures
from tests.test_assistant import answered_payload


class AnswerPolicyTest(unittest.TestCase):
    setUp = fixtures.AssistantTest.setUp
    tearDown = fixtures.AssistantTest.tearDown

    def test_invasive_steps_are_replaced_with_verifiable_guide_titles(self):
        for answer in (
            "先拔出NTC线缆，再测量接线柱电阻 [S1]。",
            "断电后重新连接热床供电线 [S1]。",
            "加热至80度后取下热端 [S1]。",
            "Disconnect the cable and measure resistance [S1].",
            "拆下底盖并逐个断开连接器 [S1]。",
        ):
            with self.subTest(answer=answer):
                result = Assistant(
                    self.retriever, FakeProvider(answered_payload(answer=answer))
                ).answer("热床不加热怎么办？", "a1")
                self.assertEqual(result.status, "answered")
                self.assertIn("仅提供官方指南入口", result.answer)
                self.assertNotIn(answer, result.answer)
                self.assertEqual(result.citations[0].quote, "A1 热床不加热排查")

    def test_modification_is_refused_without_spending_model_tokens(self):
        for question in ("A1可以加装主动腔体加热模块吗？", "如何绕过温控保护？"):
            provider = FakeProvider([])
            result = Assistant(self.retriever, provider).answer(question, "a1")
            self.assertEqual(result.status, "refused")
            self.assertEqual(result.refusal_reason, "unsafe_procedure")
            self.assertEqual(provider.calls, [])

    def test_elliptical_followup_cannot_bypass_modification_refusal(self):
        from printcare.assistant.session import Session

        provider = FakeProvider([])
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1")
        assistant.answer("A1加装主动腔体加热模块", "a1", session)
        result = assistant.answer("那怎么安装？", "a1", session)
        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "unsafe_procedure")
        self.assertEqual(provider.calls, [])

    def test_normal_hotend_replacement_is_not_a_modification_refusal(self):
        provider = FakeProvider(answered_payload())
        result = Assistant(self.retriever, provider).answer("更换热端后热床不加热", "a1")
        self.assertEqual(result.status, "answered")
        self.assertEqual(len(provider.calls), 1)

    def test_insufficient_evidence_cannot_keep_uncited_maintenance_suggestions(self):
        raw = answered_payload(
            status="insufficient_evidence",
            answer="无法判断噪声是否正常，但可以涂脂并控制电机往返运动 [S1]。",
        )
        result = Assistant(self.retriever, FakeProvider(raw)).answer("热床噪声是否正常？", "a1")
        self.assertEqual(result.answer, BAD_CITATIONS_ANSWER)
        self.assertEqual(result.citations, ())

    def test_explicit_topics_get_independent_sources_even_if_model_omits_one(self):
        from printcare.ingestion.store import IngestStore
        from printcare.retrieval.retriever import Retriever
        from tests.retrieval_corpus import add_document

        path = self.tmp.name + "/assistant.sqlite3"
        store = IngestStore(path)
        add_document(
            store,
            locale="zh",
            path="a1/circuit",
            machines=("a1",),
            title="A1 电路故障诊断",
            texts=("只有指示灯不亮时才适用该分支。",),
        )
        store.close()
        provider = FakeProvider(answered_payload())
        result = Assistant(Retriever.from_sqlite(path), provider).answer(
            "热床和电路怎么检查？", "a1"
        )
        self.assertTrue(any("电路" in c.title for c in result.citations))
        self.assertIn("电路故障诊断", json.dumps(provider.calls, ensure_ascii=False))
        self.assertNotIn("只有指示灯不亮时", result.answer)  # Do not invent this user symptom.
