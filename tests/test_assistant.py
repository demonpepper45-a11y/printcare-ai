import json
import tempfile
import unittest
from pathlib import Path

from printcare.assistant.assistant import BAD_CITATIONS_ANSWER, DEFAULT_FOLLOW_UP, Assistant
from printcare.assistant.context import ModelOutputError
from printcare.assistant.provider import FakeProvider
from printcare.assistant.session import Session
from printcare.ingestion.store import IngestStore
from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import add_document

TEXT = "A1 热床不加热时，先断电，检查热床线缆与电源接口是否插紧。"


def answered_payload(**overrides):
    payload = {
        "status": "answered",
        "answer": "先断电，再检查热床线缆。",
        "citations": [{"source": "S1", "quote": "先断电，检查热床线缆"}],
        "missing_information": [],
        "follow_up_question": None,
        "refusal_reason": None,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "assistant.sqlite3"
        store = IngestStore(db_path)
        add_document(
            store,
            locale="zh",
            path="a1/troubleshooting/heatbed",
            machines=("a1",),
            title="A1 热床不加热排查",
            texts=(TEXT,),
        )
        store.close()
        self.retriever = Retriever.from_sqlite(str(db_path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_answered_keeps_valid_citation(self):
        provider = FakeProvider(answered_payload())
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "answered")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].machine, "a1")
        self.assertEqual(result.machine_check.result, "match")
        self.assertEqual(result.session.reported_issue, "A1 热床不加热怎么办？")
        self.assertIsNotNone(result.usage)

    def test_unverifiable_citation_downgrades_answer(self):
        provider = FakeProvider(answered_payload(citations=[{"source": "S9", "quote": "先断电"}]))
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.citations, ())
        self.assertEqual(result.answer, BAD_CITATIONS_ANSWER)
        self.assertEqual([drop.reason for drop in result.citation_audit], ["unknown_source"])

    def test_citation_retry_recovers_valid_answer(self):
        bad = answered_payload(
            answer="先断电 [S1]。",
            citations=[{"source": "S1", "quote": "不存在的原文"}],
        )
        provider = FakeProvider([bad, answered_payload()])
        result = Assistant(self.retriever, provider).answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "answered")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(
            [(drop.reason, drop.attempt) for drop in result.citation_audit],
            [("quote_not_found", 1)],
        )

    def test_citation_retry_failure_keeps_audit(self):
        bad = answered_payload(
            answer="先断电 [S1]。",
            citations=[{"source": "S1", "quote": "不存在的原文"}],
        )
        provider = FakeProvider([bad, bad])
        result = Assistant(self.retriever, provider).answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.answer, BAD_CITATIONS_ANSWER)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(
            [(drop.reason, drop.attempt) for drop in result.citation_audit],
            [("quote_not_found", 1), ("quote_not_found", 2)],
        )

    def test_model_insufficient_explanation_is_preserved(self):
        payload = answered_payload(
            status="insufficient_evidence",
            answer="资料没有给出重新接回的完整步骤，建议参考官方指南。 [S1]",
            citations=[],
        )
        result = Assistant(self.retriever, FakeProvider(payload)).answer(
            "A1 热床不加热怎么办？", "a1"
        )

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIn("重新接回", result.answer)
        self.assertNotIn(BAD_CITATIONS_ANSWER, result.answer)
        self.assertNotIn("[S1]", result.answer)
        self.assertEqual(result.citations, ())

    def test_model_refusal_explanation_is_preserved(self):
        payload = answered_payload(
            status="refused",
            answer="不能用手直接拿高温喷嘴，有烫伤风险，请参考官方指南。",
            citations=[],
            refusal_reason="unsafe_procedure",
        )
        result = Assistant(self.retriever, FakeProvider(payload)).answer(
            "A1 热床不加热怎么办？", "a1"
        )

        self.assertEqual(result.status, "refused")
        self.assertIn("烫伤风险", result.answer)
        self.assertNotIn("这个问题超出首版", result.answer)
        self.assertEqual(result.refusal_reason, "unsafe_procedure")

    def test_refusal_with_step_like_text_falls_back_to_default(self):
        payload = answered_payload(
            status="refused",
            answer="不能这样操作，但你可以先断电，然后再重新接线。",
            citations=[],
            refusal_reason="unsafe_procedure",
        )
        result = Assistant(self.retriever, FakeProvider(payload)).answer(
            "A1 热床不加热怎么办？", "a1"
        )

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.answer, "这个问题超出首版可依据官方资料回答的范围。")

    def test_marker_without_valid_quote_downgrades_entire_answer(self):
        provider = FakeProvider(answered_payload(answer="先断电 [S1]，然后测量 [S9]。"))
        result = Assistant(self.retriever, provider).answer("热床不加热怎么办？", "a1")
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.answer, BAD_CITATIONS_ANSWER)
        self.assertEqual(result.citations, ())

    def test_valid_marker_is_preserved(self):
        provider = FakeProvider(answered_payload(answer="先断电，再检查线缆 [S1]。"))
        result = Assistant(self.retriever, provider).answer("热床不加热怎么办？", "a1")
        self.assertEqual(result.status, "answered")
        self.assertIn("[S1]", result.answer)

    def test_vague_no_extrusion_asks_ticket_questions_without_model_call(self):
        provider = FakeProvider([])
        result = Assistant(self.retriever, provider).answer("A1 打印时不出料", "a1")

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(provider.calls, [])
        self.assertIsNotNone(result.fault_ticket)
        self.assertEqual(result.fault_ticket.flow, "no_extrusion")
        self.assertEqual(result.fault_ticket.symptom, "打印时不出料")
        self.assertIn("错误码", result.follow_up_question)
        self.assertIn("AMS lite", result.follow_up_question)
        self.assertEqual(set(result.missing_information), {"error_code", "feed_method"})

    def test_ticket_merges_followup_answers(self):
        session = Session.create("a1")
        provider = FakeProvider([answered_payload()])
        assistant = Assistant(self.retriever, provider)

        first = assistant.answer("A1 打印时不出料", "a1", session)
        second = assistant.answer("使用外置料架，没有错误码，PLA，打印时不出料", "a1", session)

        self.assertEqual(first.status, "needs_clarification")
        self.assertIsNotNone(second.fault_ticket)
        self.assertEqual(second.fault_ticket.feed_method, "外置料架")
        self.assertEqual(second.fault_ticket.error_code, "无")
        self.assertEqual(second.fault_ticket.filament, "PLA")
        self.assertEqual(second.fault_ticket.symptom, "打印时不出料")

    def test_detailed_maintenance_question_still_reaches_model(self):
        provider = FakeProvider([answered_payload()])
        result = Assistant(self.retriever, provider).answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "answered")
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNotNone(result.fault_ticket)
        self.assertEqual(result.fault_ticket.flow, "heatbed")

    def test_machine_mismatch_skips_model_call(self):
        provider = FakeProvider([])
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("A1 mini 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "needs_clarification")
        self.assertIn("A1 mini", result.follow_up_question)
        self.assertEqual(result.missing_information, ("machine_conflict",))
        self.assertEqual(result.machine_check.result, "mismatch")
        self.assertEqual(provider.calls, [])
        self.assertIsNone(result.usage)

    def test_unsupported_model_mention_is_refused(self):
        provider = FakeProvider([])
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("X1C 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "unsupported_machine")
        self.assertEqual(provider.calls, [])

    def test_no_hits_is_refused_without_source(self):
        provider = FakeProvider([])
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("zzzz 完全无关的内容", "a1")

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "no_reliable_source")
        self.assertEqual(provider.calls, [])

    def test_needs_clarification_gets_fallback_question(self):
        provider = FakeProvider(
            json.dumps(
                {
                    "status": "needs_clarification",
                    "answer": "",
                    "citations": [],
                    "missing_information": [],
                    "follow_up_question": None,
                    "refusal_reason": None,
                },
                ensure_ascii=False,
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.follow_up_question, DEFAULT_FOLLOW_UP)
        self.assertEqual(result.missing_information, ("other",))
        self.assertEqual(result.citations, ())

    def test_refused_without_reason_defaults(self):
        provider = FakeProvider(
            json.dumps(
                {
                    "status": "refused",
                    "answer": "",
                    "citations": [],
                    "missing_information": [],
                    "follow_up_question": None,
                    "refusal_reason": None,
                },
                ensure_ascii=False,
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "no_reliable_source")
        self.assertTrue(result.answer)

    def test_non_answered_answers_drop_citation_markers(self):
        provider = FakeProvider(
            json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer": "资料不足 [S1]，无法给结论。",
                    "citations": [],
                    "missing_information": [],
                    "follow_up_question": None,
                    "refusal_reason": None,
                },
                ensure_ascii=False,
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertNotIn("[S1]", result.answer)

    def test_answered_with_uncertain_conclusion_downgrades(self):
        provider = FakeProvider(
            answered_payload(
                answer="资料只给出 48 dB 的参考值，无法直接判断超过 60 分贝是否正常。",
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热能判断是主板坏了吗？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.citations, ())
        self.assertNotIn("[S1]", result.answer)

    def test_uncertainty_with_interleaved_adverb_also_downgrades(self):
        provider = FakeProvider(
            answered_payload(
                answer="资料没有给出判定标准，因此无法据此判断是否正常。",
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热能判断是主板坏了吗？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")

    def test_uncertainty_with_qualified_phrase_also_downgrades(self):
        provider = FakeProvider(
            answered_payload(
                answer="因此无法仅凭现有资料判断“超过 60 分贝”是否正常。",
            )
        )
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("热床不加热能判断是主板坏了吗？", "a1")

        self.assertEqual(result.status, "insufficient_evidence")

    def test_normal_answer_keeps_answered_status(self):
        provider = FakeProvider(answered_payload())
        assistant = Assistant(self.retriever, provider)

        result = assistant.answer("A1 热床不加热怎么办？", "a1")

        self.assertEqual(result.status, "answered")

    def test_invalid_model_output_raises(self):
        provider = FakeProvider("先断电再检查线缆。")
        assistant = Assistant(self.retriever, provider)

        with self.assertRaises(ModelOutputError):
            assistant.answer("热床不加热怎么办？", "a1")

    def test_session_carries_context_between_turns(self):
        provider = FakeProvider([answered_payload(), answered_payload()])
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1")

        assistant.answer("热床不加热怎么办？", "a1", session)
        assistant.answer("那还要检查什么？", "a1", session)

        self.assertEqual(len(provider.calls), 2)
        second_user_message = provider.calls[1][1]["content"]
        self.assertIn("会话现象", second_user_message)
        self.assertIn("热床不加热怎么办", second_user_message)
        self.assertEqual(len(session.history), 2)

    def test_machine_correction_is_recorded(self):
        provider = FakeProvider(answered_payload())
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1_mini")

        assistant.answer("热床不加热怎么办？", "a1", session)

        self.assertEqual(session.machine, "a1")
        self.assertEqual(len(session.corrections), 1)
        self.assertEqual(session.corrections[0]["from"], "a1_mini")


if __name__ == "__main__":
    unittest.main()
