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


def load_questions(path: Path) -> list[Question]:
    questions = []
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
                context_turns=tuple(payload.get("context_turns") or ()),
            )
        )
    return questions


def canonical_path_from_url(url: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    if parts and parts[0] in LOCALES:
        parts = parts[1:]
    return "/".join(parts).lower()


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
            )
            context_results.append(evaluate_question(assistant, context_question, session))

    result = assistant.answer(question.question, question.machine, session)
    cited = {canonical_path_from_url(citation.source_url) for citation in result.citations}
    missing = [path for path in question.expected_evidence if path not in cited]
    leaked = [path for path in question.forbidden_evidence if path in cited]
    status_ok = result.status == question.expected_status
    reason_ok = (
        question.expected_refusal_reason is None
        or result.refusal_reason == question.expected_refusal_reason
    )
    evidence_ok = not missing and not leaked
    if question.expected_status == "answered":
        passed = status_ok and evidence_ok
    else:
        passed = status_ok and reason_ok and not result.citations
    passed = passed and all(item["verdict"] == "PASS" for item in context_results)
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
        "citation_quotes": [citation.quote for citation in result.citations],
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
