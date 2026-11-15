"""Retrieval-level baseline for the T05 evaluation set.

This runner checks whether each question's expected evidence is retrievable
with the T06 keyword retriever. It does **not** judge answer quality: that is
the T07 task once a model provider is configured.

Usage::

    $env:PYTHONPATH='src'
    python evals/run_retrieval_baseline.py --db runtime/printcare.sqlite3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from printcare.retrieval.retriever import Retriever

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.jsonl"
LOCALES = {"en", "zh"}
SKIP_CATEGORIES = {"multi_turn"}


@dataclass(frozen=True)
class Question:
    id: str
    machine: str
    category: str
    question: str
    expected_status: str
    expected_evidence: tuple[str, ...]
    forbidden_evidence: tuple[str, ...] = ()
    expected_refusal_reason: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class Outcome:
    question_id: str
    category: str
    verdict: str
    detail: str


def load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        questions.append(
            Question(
                id=payload["id"],
                machine=payload["machine"],
                category=payload["category"],
                question=payload["question"],
                expected_status=payload["expected_status"],
                expected_evidence=tuple(payload.get("expected_evidence") or ()),
                forbidden_evidence=tuple(payload.get("forbidden_evidence") or ()),
                expected_refusal_reason=payload.get("expected_refusal_reason"),
                notes=payload.get("notes") or "",
            )
        )
    return questions


def canonical_path_from_url(url: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    if parts and parts[0] in LOCALES:
        parts = parts[1:]
    return "/".join(parts).lower()


def evaluate(questions: list[Question], retriever: Retriever, k: int) -> list[Outcome]:
    indexed = {canonical_path_from_url(chunk.source_url) for chunk in retriever.chunks}
    outcomes: list[Outcome] = []
    for question in questions:
        if question.category in SKIP_CATEGORIES:
            outcomes.append(
                Outcome(question.id, question.category, "SKIP", "requires conversation (T07)")
            )
            continue
        if question.expected_status == "insufficient_evidence":
            outcomes.append(
                Outcome(question.id, question.category, "SKIP", "answer-level check (T07)")
            )
            continue

        result = retriever.query(question.question, question.machine, limit=k)
        retrieved = [canonical_path_from_url(hit.source_url) for hit in result.hits]

        if question.expected_status == "needs_clarification":
            passed = result.warning == "machine_mismatch" and not result.hits
            detail = f"warning={result.warning} hits={len(result.hits)}"
        elif question.expected_status == "refused":
            passed = result.warning == "unsupported_machine_mentioned" and not result.hits
            detail = f"warning={result.warning} hits={len(result.hits)}"
        else:
            missing = [path for path in question.expected_evidence if path not in indexed]
            if missing:
                outcomes.append(
                    Outcome(
                        question.id,
                        question.category,
                        "SKIP",
                        f"evidence not indexed: {', '.join(missing)}",
                    )
                )
                continue
            missing_hits = [path for path in question.expected_evidence if path not in retrieved]
            leaked = [path for path in question.forbidden_evidence if path in retrieved]
            passed = not missing_hits and not leaked
            detail = f"missing={missing_hits or '-'} leaked={leaked or '-'}"

        outcomes.append(
            Outcome(question.id, question.category, "PASS" if passed else "FAIL", detail)
        )
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="runtime SQLite database")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    questions = load_questions(args.questions)
    retriever = Retriever.from_sqlite(args.db)
    outcomes = evaluate(questions, retriever, args.k)

    counts = Counter(outcome.verdict for outcome in outcomes)
    if args.json:
        print(
            json.dumps(
                {
                    "total": len(outcomes),
                    "pass": counts.get("PASS", 0),
                    "fail": counts.get("FAIL", 0),
                    "skip": counts.get("SKIP", 0),
                    "outcomes": [outcome.__dict__ for outcome in outcomes],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for outcome in outcomes:
            print(
                f"{outcome.verdict:4} {outcome.question_id:12} "
                f"{outcome.category:16} {outcome.detail}"
            )
        print(
            f"total={len(outcomes)} pass={counts.get('PASS', 0)} "
            f"fail={counts.get('FAIL', 0)} skip={counts.get('SKIP', 0)}"
        )
    return 1 if counts.get("FAIL", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
