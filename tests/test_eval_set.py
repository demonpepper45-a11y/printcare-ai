import json
import re
import unittest
from pathlib import Path

from printcare.retrieval.tokenize import detect_machines, detect_unsupported_models

QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "evals" / "questions.jsonl"
VALID_MACHINES = {"a1", "a1_mini"}
VALID_STATUSES = {"answered", "needs_clarification", "insufficient_evidence", "refused"}
VALID_REFUSALS = {"no_reliable_source", "out_of_scope", "unsafe_procedure", "unsupported_machine"}
VALID_CATEGORIES = {
    "direct_qa",
    "error_code",
    "multi_doc",
    "machine_conflict",
    "insufficient_evidence",
    "unsupported_machine",
    "chinese_synonym",
    "multi_turn",
    "safety_miss",
    "safety_false_positive",
}
PREFIX_FOR_MACHINE = {"a1": "a1/", "a1_mini": "a1-mini/"}
HMS_PATTERN = re.compile(r"(?i)[0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}")


def load_questions() -> list[dict]:
    questions = []
    for line in QUESTIONS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            questions.append(json.loads(line))
    return questions


class EvaluationSetTest(unittest.TestCase):
    def setUp(self):
        self.questions = load_questions()

    def test_first_batch_has_at_least_thirty_questions(self):
        self.assertGreaterEqual(len(self.questions), 30)

    def test_ids_and_machine_question_pairs_are_unique(self):
        ids = [item["id"] for item in self.questions]
        pairs = [(item["machine"], item["question"]) for item in self.questions]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_every_category_is_covered(self):
        categories = {item["category"] for item in self.questions}

        self.assertEqual(categories, VALID_CATEGORIES)

    def test_schema_and_enums(self):
        for item in self.questions:
            with self.subTest(question=item["id"]):
                self.assertIn(item["machine"], VALID_MACHINES)
                self.assertIn(item["category"], VALID_CATEGORIES)
                self.assertIn(item["expected_status"], VALID_STATUSES)
                self.assertTrue(item["question"].strip())

    def test_expected_evidence_matches_selected_machine(self):
        for item in self.questions:
            prefix = PREFIX_FOR_MACHINE[item["machine"]]
            for path in item.get("expected_evidence") or ():
                with self.subTest(question=item["id"], path=path):
                    self.assertTrue(
                        path.startswith(prefix),
                        f"{path} 不属于机型 {item['machine']}",
                    )

    def test_forbidden_evidence_is_never_on_own_machine(self):
        for item in self.questions:
            prefix = PREFIX_FOR_MACHINE[item["machine"]]
            for path in item.get("forbidden_evidence") or ():
                with self.subTest(question=item["id"], path=path):
                    self.assertFalse(path.startswith(prefix))

    def test_answered_questions_carry_evidence(self):
        for item in self.questions:
            if item["expected_status"] == "answered":
                with self.subTest(question=item["id"]):
                    self.assertTrue(item.get("expected_evidence"))

    def test_machine_conflict_questions_mention_the_other_machine(self):
        for item in self.questions:
            if item["category"] != "machine_conflict":
                continue
            with self.subTest(question=item["id"]):
                detected = detect_machines(item["question"])
                self.assertTrue(detected)
                self.assertNotEqual(set(detected), {item["machine"]})
                self.assertEqual(item.get("expected_evidence"), [])

    def test_unsupported_questions_mention_unsupported_models(self):
        for item in self.questions:
            if item["category"] != "unsupported_machine":
                continue
            with self.subTest(question=item["id"]):
                self.assertTrue(detect_unsupported_models(item["question"]))
                self.assertEqual(item["expected_status"], "refused")
                self.assertEqual(item.get("expected_refusal_reason"), "unsupported_machine")

    def test_insufficient_questions_have_no_evidence(self):
        for item in self.questions:
            if item["expected_status"] != "insufficient_evidence":
                continue
            with self.subTest(question=item["id"]):
                self.assertEqual(item.get("expected_evidence"), [])

    def test_error_code_questions_contain_a_code(self):
        for item in self.questions:
            if item["category"] != "error_code":
                continue
            with self.subTest(question=item["id"]):
                self.assertTrue(HMS_PATTERN.search(item["question"]))

    def test_refused_questions_carry_a_valid_reason(self):
        for item in self.questions:
            if item["expected_status"] != "refused":
                continue
            reason = item.get("expected_refusal_reason")
            if reason is None:
                continue
            with self.subTest(question=item["id"]):
                self.assertIn(reason, VALID_REFUSALS)

    def test_multi_turn_questions_have_notes(self):
        for item in self.questions:
            if item["category"] != "multi_turn":
                continue
            with self.subTest(question=item["id"]):
                self.assertTrue(item.get("notes"))


if __name__ == "__main__":
    unittest.main()
