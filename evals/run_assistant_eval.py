"""Answer-level evaluation for the T05 question set.

Runs every question through the T07 assistant with the configured model and
checks the answer status plus, for answered questions, whether the expected
documents are cited and forbidden machine documents are not.

This is an automatic check only. It cannot judge whether the prose is faithful;
that still needs the human review described in ``evals/README.md``.

Usage::

    $env:PYTHONPATH='src'
    python evals/run_assistant_eval.py --db runtime/printcare.sqlite3
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from printcare.assistant.assistant import Assistant
from printcare.assistant.provider import DEFAULT_BASE_URL, DeepSeekProvider
from printcare.assistant.session import Session
from printcare.retrieval.retriever import Retriever
from printcare.settings import Settings, resolve_model_api_key

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.jsonl"
DEFAULT_OUTPUT = Path("runtime/assistant-eval.json")
LOCALES = {"en", "zh"}
VALID_STATUSES = {"answered", "needs_clarification", "insufficient_evidence", "refused"}
VALID_ANSWER_MODES = {None, "guide_only", "other"}
# Conservative peak prices for deepseek-flash, USD per 1M tokens.
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20


@dataclass(frozen=True)
class Question:
    id: str
    machine: str
    category: str
    question: str
    expected_status: str
    expected_evidence: tuple[str, ...]
    forbidden_evidence: tuple[str, ...]
    expected_refusal_reason: str | None = None
    context_turns: tuple[dict, ...] = ()
    expected_answer_mode: str | None = None
    review_checks: tuple[str, ...] = ()
    accepted_outcomes: tuple[dict, ...] = ()


def _validate_outcome(outcome: dict, question_id: str, index: int) -> None:
    if not isinstance(outcome, dict) or "status" not in outcome:
        raise ValueError(f"{question_id}: accepted_outcomes[{index}] needs a status")
    if outcome["status"] not in VALID_STATUSES:
        raise ValueError(f"{question_id}: invalid accepted outcome status")
    if outcome.get("answer_mode") not in VALID_ANSWER_MODES:
        raise ValueError(f"{question_id}: invalid accepted outcome answer_mode")
    for key in ("answer_contains_any", "answer_contains_all", "answer_not_contains"):
        terms = outcome.get(key)
        if terms is not None and (
            not isinstance(terms, list) or not all(isinstance(term, str) for term in terms)
        ):
            raise ValueError(f"{question_id}: {key} must be a list of strings")
    groups = outcome.get("answer_contains_groups")
    if groups is not None and (
        not isinstance(groups, list)
        or not all(
            isinstance(group, list) and group and all(isinstance(term, str) for term in group)
            for group in groups
        )
    ):
        raise ValueError(f"{question_id}: answer_contains_groups must be a list of term lists")
    min_length = outcome.get("min_answer_length")
    if min_length is not None and (
        not isinstance(min_length, int) or isinstance(min_length, bool) or min_length < 0
    ):
        raise ValueError(f"{question_id}: min_answer_length must be a non-negative integer")


def load_questions(path: Path) -> list[Question]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("expected_answer_mode") not in (None, "guide_only", "other"):
            raise ValueError("invalid expected_answer_mode")
        accepted_outcomes = tuple(payload.get("accepted_outcomes") or ())
        for index, outcome in enumerate(accepted_outcomes):
            _validate_outcome(outcome, str(payload.get("id")), index)
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
                context_turns=tuple(payload.get("context_turns") or ()),
                expected_answer_mode=payload.get("expected_answer_mode"),
                review_checks=tuple(payload.get("review_checks") or ()),
                accepted_outcomes=accepted_outcomes,
            )
        )
    return questions


def canonical_path_from_url(url: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    if parts and parts[0] in LOCALES:
        parts = parts[1:]
    return "/".join(parts).lower()


def _default_outcome(question: Question) -> dict:
    return {
        "status": question.expected_status,
        "answer_mode": question.expected_answer_mode,
        "refusal_reason": question.expected_refusal_reason,
        "expected_evidence": list(question.expected_evidence),
    }


def _outcome_matches(
    question: Question,
    outcome: dict,
    result,
    cited: set[str],
    answer_mode: str,
) -> bool:
    """Check one accepted outcome, including its content conditions.

    Non-answered alternatives must not carry citations, and answered outcomes
    must cite the declared evidence and avoid forbidden machine documents.
    """
    if result.status != outcome.get("status"):
        return False
    expected_reason = outcome.get("refusal_reason")
    if expected_reason is not None and result.refusal_reason != expected_reason:
        return False

    if outcome.get("status") == "answered":
        expected = outcome.get("expected_evidence", list(question.expected_evidence))
        if any(path not in cited for path in expected):
            return False
        if any(path in cited for path in question.forbidden_evidence):
            return False
    elif result.citations:
        return False

    mode = outcome.get("answer_mode")
    if mode is not None and answer_mode != mode:
        return False

    answer = result.answer
    for term in outcome.get("answer_contains_all") or ():
        if term not in answer:
            return False
    any_terms = outcome.get("answer_contains_any")
    if any_terms and not any(term in answer for term in any_terms):
        return False
    for group in outcome.get("answer_contains_groups") or ():
        if not any(term in answer for term in group):
            return False
    if any(term in answer for term in outcome.get("answer_not_contains") or ()):
        return False
    min_length = outcome.get("min_answer_length")
    return not (min_length and len(answer) < min_length)


def evaluate_question(
    assistant: Assistant, question: Question, session: Session | None = None
) -> dict:
    context_results = []
    if question.category == "multi_turn" and not question.context_turns:
        return {"id": question.id, "verdict": "FAIL", "note": "missing explicit context_turns"}
    if question.context_turns:
        session = Session.create(question.context_turns[0].get("machine", question.machine))
        for index, turn in enumerate(question.context_turns):
            context_question = replace(
                question,
                id=f"{question.id}/context-{index + 1}",
                category="direct_qa",
                question=turn["question"],
                machine=turn.get("machine", question.machine),
                expected_status=turn["expected_status"],
                expected_evidence=tuple(turn.get("expected_evidence") or ()),
                forbidden_evidence=tuple(turn.get("forbidden_evidence") or ()),
                expected_refusal_reason=turn.get("expected_refusal_reason"),
                context_turns=(),
                expected_answer_mode=turn.get("expected_answer_mode"),
                review_checks=tuple(turn.get("review_checks") or ()),
            )
            context_results.append(evaluate_question(assistant, context_question, session))

    result = assistant.answer(question.question, question.machine, session)
    cited = {canonical_path_from_url(citation.source_url) for citation in result.citations}
    missing = [path for path in question.expected_evidence if path not in cited]
    leaked = [path for path in question.forbidden_evidence if path in cited]
    answer_mode = "guide_only" if "当前仅提供官方指南入口" in result.answer else "other"
    outcomes = question.accepted_outcomes or (_default_outcome(question),)
    matched_outcome = None
    for index, outcome in enumerate(outcomes):
        if _outcome_matches(question, outcome, result, cited, answer_mode):
            matched_outcome = index
            break
    if question.accepted_outcomes:
        mode_ok = matched_outcome is not None
    else:
        mode_ok = (
            question.expected_answer_mode is None or answer_mode == question.expected_answer_mode
        )
    passed = matched_outcome is not None and all(
        item["verdict"] == "PASS" for item in context_results
    )
    usage = dict(result.usage or {})
    for item in context_results:
        for key in ("prompt_tokens", "completion_tokens"):
            usage[key] = int(usage.get(key) or 0) + int(item["usage"].get(key) or 0)
    return {
        "id": question.id,
        "category": question.category,
        "verdict": "PASS" if passed else "FAIL",
        "expected_status": question.expected_status,
        "actual_status": result.status,
        "citations": len(result.citations),
        "missing_evidence": missing,
        "leaked_evidence": leaked,
        "answer": result.answer,
        "answer_mode": answer_mode,
        "expected_answer_mode": question.expected_answer_mode,
        "answer_mode_ok": mode_ok,
        "accepted_outcomes": list(outcomes),
        "matched_outcome": matched_outcome,
        "review_checks": list(question.review_checks),
        "citation_quotes": [citation.quote for citation in result.citations],
        "citation_sources": [
            {
                "source_label": citation.source_label,
                "url": citation.source_url,
                "section": list(citation.section_path),
                "quote": citation.quote,
            }
            for citation in result.citations
        ],
        "citation_drops": [
            {"source": drop.source, "reason": drop.reason, "attempt": drop.attempt}
            for drop in getattr(result, "citation_audit", ())
        ],
        "follow_up_question": result.follow_up_question,
        "refusal_reason": result.refusal_reason,
        "usage": usage,
        "context_results": context_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    provider = DeepSeekProvider(
        resolve_model_api_key(settings),
        model=args.model or settings.model_name,
        base_url=settings.model_base_url or DEFAULT_BASE_URL,
        thinking=args.thinking,
    )
    assistant = Assistant(Retriever.from_sqlite(args.db), provider, k=args.k)
    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]

    results = []
    prompt_tokens = 0
    completion_tokens = 0
    for question in questions:
        try:
            outcome = evaluate_question(assistant, question)
        except Exception as exc:  # noqa: BLE001 - one bad question must not stop the run
            outcome = {
                "id": question.id,
                "verdict": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        usage = outcome.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        results.append(outcome)
        print(
            f"{outcome['verdict']:4} {outcome['id']:12} {outcome.get('actual_status', '-'):22} "
            f"{outcome.get('note', '')}"
        )

    passes = sum(1 for item in results if item["verdict"] == "PASS")
    fails = sum(1 for item in results if item["verdict"] == "FAIL")
    skips = sum(1 for item in results if item["verdict"] == "SKIP")
    cost = (
        prompt_tokens / 1_000_000 * INPUT_PRICE_PER_MILLION
        + completion_tokens / 1_000_000 * OUTPUT_PRICE_PER_MILLION
    )
    summary = {
        "total": len(results),
        "pass": passes,
        "fail": fails,
        "skip": skips,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": round(cost, 4),
        "model": provider.model,
        "guide_only": sum(item.get("answer_mode") == "guide_only" for item in results),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"total={len(results)} pass={passes} fail={fails} skip={skips} "
        f"tokens_in={prompt_tokens} tokens_out={completion_tokens} cost≈${cost:.4f}"
    )
    print(f"details: {args.json_out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
