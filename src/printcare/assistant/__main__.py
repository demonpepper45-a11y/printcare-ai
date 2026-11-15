"""Command line chat entry point: ``python -m printcare.assistant``.

Example::

    $env:PYTHONPATH='src'
    python -m printcare.assistant --db runtime/printcare.sqlite3 \
        --machine a1_mini --question "挤出机堵料怎么清理？"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from printcare.assistant.assistant import Assistant
from printcare.assistant.context import ModelOutputError
from printcare.assistant.provider import DEFAULT_BASE_URL, DeepSeekProvider, ProviderError
from printcare.assistant.session import Session
from printcare.retrieval.retriever import Retriever, UnsupportedMachineError
from printcare.settings import ConfigError, Settings, resolve_model_api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m printcare.assistant",
        description="Ask the machine-scoped RAG assistant with citations.",
    )
    parser.add_argument("--db", required=True, help="runtime SQLite database")
    parser.add_argument("--machine", required=True, choices=("a1", "a1_mini"))
    parser.add_argument("--question", required=True)
    parser.add_argument("--k", type=int, default=6, help="retrieved chunks")
    parser.add_argument("--model", help="override PRINTCARE_MODEL_NAME")
    parser.add_argument("--session", type=Path, help="JSON file for multi-turn state")
    parser.add_argument("--thinking", action="store_true", help="enable model thinking mode")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        key = resolve_model_api_key(settings)
    except ConfigError as exc:
        print(f"config error: {exc}")
        return 2

    provider = DeepSeekProvider(
        key,
        model=args.model or settings.model_name,
        base_url=settings.model_base_url or DEFAULT_BASE_URL,
        thinking=args.thinking,
    )
    retriever = Retriever.from_sqlite(args.db)
    assistant = Assistant(retriever, provider, k=args.k)

    session = None
    if args.session and args.session.is_file():
        session = Session.load(args.session)

    try:
        result = assistant.answer(args.question, args.machine, session)
    except (ProviderError, ModelOutputError, UnsupportedMachineError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        return 1

    if args.session and session is not None:
        session.save(args.session)

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    print(f"status={result.status} machine={result.machine_check.requested}")
    print(result.answer)
    if result.follow_up_question:
        print(f"追问：{result.follow_up_question}")
    if result.refusal_reason:
        print(f"拒答原因：{result.refusal_reason}")
    for index, citation in enumerate(result.citations, start=1):
        heading = " > ".join(citation.section_path) or "-"
        print(f"引用 {index}: {citation.title} | {heading}")
        print(f"  {citation.source_url}")
        print(f"  「{citation.quote}」")
    if result.usage:
        print(
            f"tokens: prompt={result.usage.get('prompt_tokens', 0)} "
            f"completion={result.usage.get('completion_tokens', 0)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
