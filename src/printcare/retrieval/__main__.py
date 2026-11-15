"""Command line query tool: ``python -m printcare.retrieval``.

Example::

    python -m printcare.retrieval --db runtime/printcare.sqlite3 \
        --machine a1_mini --query "挤出机堵料"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from printcare.retrieval.retriever import Retriever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m printcare.retrieval",
        description="Query the local chunk index with machine filtering.",
    )
    parser.add_argument("--db", required=True, help="runtime SQLite database")
    parser.add_argument("--machine", required=True, choices=("a1", "a1_mini"))
    parser.add_argument("--query", required=True, help="question text")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    retriever = Retriever.from_sqlite(args.db)
    result = retriever.query(args.query, args.machine, limit=args.limit)

    if args.json:
        payload = {
            "machine": result.machine,
            "query": result.query,
            "warning": result.warning,
            "detected_machines": list(result.detected_machines),
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "doc_id": hit.doc_id,
                    "score": hit.score,
                    "title": hit.title,
                    "source_url": hit.source_url,
                    "heading_path": list(hit.heading_path),
                    "anchor": hit.anchor,
                    "official_updated_at": hit.official_updated_at,
                    "text": hit.text,
                }
                for hit in result.hits
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if result.warning:
        detected = ",".join(result.detected_machines) or "-"
        print(f"warning={result.warning} detected={detected}")
    print(f"machine={result.machine} hits={len(result.hits)}")
    for rank, hit in enumerate(result.hits, start=1):
        heading = " > ".join(hit.heading_path) or "-"
        print(f"{rank}. score={hit.score} section={hit.section} heading={heading}")
        print(f"   {hit.title} | {hit.source_url}")
        print(f"   {hit.text.replace(chr(10), ' ')[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
