"""Regressions for evaluation boundaries and real multi-turn orchestration."""

import json
import tempfile
import unittest
from pathlib import Path

from evals.run_assistant_eval import Question as AnswerQuestion
from evals.run_assistant_eval import evaluate_question, load_questions
from evals.run_retrieval_baseline import Question as RetrievalQuestion
from evals.run_retrieval_baseline import evaluate

from printcare.assistant.assistant import Assistant
from printcare.assistant.provider import FakeProvider
from printcare.assistant.session import Session
from printcare.retrieval.retriever import Retriever
from tests.retrieval_corpus import build_corpus
from tests.test_assistant import answered_payload


class EvaluationRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "corpus.sqlite3"
        build_corpus(path).close()
        self.retriever = Retriever.from_sqlite(str(path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_answer_level_refusal_is_not_a_retrieval_failure(self):
        questions = [
            RetrievalQuestion("mod", "a1", "insufficient_evidence", "热床改装", "refused", ()),
            RetrievalQuestion(
                "unsupported", "a1", "unsupported_machine", "X1C 热床", "refused", ()
            ),
        ]
        results = evaluate(questions, self.retriever, 5)
        self.assertEqual([item.verdict for item in results], ["SKIP", "PASS"])

    def test_explicit_multi_turn_case_runs_both_model_calls(self):
        provider = FakeProvider([answered_payload(), answered_payload()])
        provider.last_usage = {"prompt_tokens": 11, "completion_tokens": 7}
        question = AnswerQuestion(
            "multi",
            "a1",
            "multi_turn",
            "那还要查什么？",
            "answered",
            ("a1/troubleshooting/heatbed",),
            (),
            context_turns=({"question": "热床不加热怎么办？", "expected_status": "answered"},),
        )
        outcome = evaluate_question(Assistant(self.retriever, provider), question)
        self.assertEqual(outcome["verdict"], "PASS")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(outcome["context_results"]), 1)
        self.assertIn("热床不加热", provider.calls[1][1]["content"])
        self.assertEqual(outcome["usage"]["prompt_tokens"], 22)
        self.assertEqual(outcome["usage"]["completion_tokens"], 14)

    def test_failed_context_turn_fails_whole_conversation(self):
        provider = FakeProvider([answered_payload(), answered_payload()])
        question = AnswerQuestion(
            "multi",
            "a1",
            "multi_turn",
            "那还要查什么？",
            "answered",
            (),
            (),
            context_turns=({"question": "热床不加热", "expected_status": "refused"},),
        )
        self.assertEqual(
            evaluate_question(Assistant(self.retriever, provider), question)["verdict"], "FAIL"
        )

    def test_multi_turn_without_context_is_a_dataset_failure(self):
        question = AnswerQuestion("missing", "a1", "multi_turn", "那怎么办？", "answered", (), ())
        provider = FakeProvider([])
        outcome = evaluate_question(Assistant(self.retriever, provider), question)
        self.assertEqual(outcome["verdict"], "FAIL")
        self.assertEqual(provider.calls, [])

    def test_dataset_multi_turn_cases_have_executable_context(self):
        path = Path(__file__).resolve().parents[1] / "evals" / "questions.jsonl"
        cases = [q for q in load_questions(path) if q.category == "multi_turn"]
        self.assertEqual(len(cases), 2)
        for question in cases:
            self.assertTrue(question.context_turns)
            self.assertIn("expected_status", question.context_turns[0])

    def test_followup_cannot_override_conflicting_machine(self):
        provider = FakeProvider([answered_payload()])
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1")
        assistant.answer("热床不加热", "a1", session)
        result = assistant.answer("那 A1 mini 呢？", "a1", session)
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(len(provider.calls), 1)

    def test_correction_clears_old_machine_issue_and_attempts(self):
        provider = FakeProvider(
            [
                answered_payload(),
                answered_payload(citations=[{"source": "S1", "quote": "A1 mini 热床"}]),
            ]
        )
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1")
        assistant.answer("A1 热床不加热", "a1", session)
        session.attempted_steps.append("已更换 A1 热床")
        result = assistant.answer("A1 mini 热床不加热", "a1_mini", session)
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.session.reported_issue, "A1 mini 热床不加热")
        self.assertEqual(result.session.attempted_steps, ())
        self.assertEqual(len(session.history), 1)
        self.assertNotIn("已更换 A1 热床", json.dumps(provider.calls[1], ensure_ascii=False))

    def test_conflicting_first_question_does_not_poison_next_turn(self):
        provider = FakeProvider([answered_payload()])
        assistant = Assistant(self.retriever, provider)
        session = Session.create("a1")
        assistant.answer("A1 mini 热床不加热", "a1", session)
        self.assertIsNone(session.reported_issue)
        result = assistant.answer("A1 热床不加热", "a1", session)
        self.assertEqual(result.status, "answered")
        self.assertEqual(session.reported_issue, "A1 热床不加热")
