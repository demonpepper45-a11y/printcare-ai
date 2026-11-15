"""Command line entry point for the ingestion pipeline.

Examples::

    python -m printcare.ingestion --list
    python -m printcare.ingestion --limit 3 --dry-run
    python -m printcare.ingestion --section maintenance --deactivate-missing
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from printcare.ingestion.fetch import HttpFetcher
from printcare.ingestion.ids import canonical_path
from printcare.ingestion.inventory import fetch_inventory, select_refs
from printcare.ingestion.models import MACHINES, SECTIONS, SUPPORTED_LOCALES
from printcare.ingestion.pipeline import run_ingestion
from printcare.ingestion.store import IngestStore

DEFAULT_DB_PATH = "runtime/printcare.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m printcare.ingestion",
        description="Fetch, parse and store Bambu Lab A1 / A1 mini wiki pages.",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite path (default: %(default)s)")
    parser.add_argument("--locale", action="append", choices=SUPPORTED_LOCALES, help="repeatable")
    parser.add_argument("--machine", action="append", choices=MACHINES, help="repeatable")
    parser.add_argument("--section", action="append", choices=SECTIONS, help="repeatable")
    parser.add_argument("--paths-file", type=Path, help="only ingest paths listed in this file")
    parser.add_argument("--limit", type=int, help="stop after N documents")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    parser.add_argument("--list", action="store_true", help="only print the selected documents")
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse without writing")
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="disable stored documents missing from this run (only for complete inventories)",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when any document fails")
    return parser


def _read_paths(path: Path) -> set[str]:
    entries: set[str] = set()
    # utf-8-sig tolerates the BOM that Windows editors add to the first line.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(canonical_path(stripped))
    return entries


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    locales = tuple(args.locale) if args.locale else SUPPORTED_LOCALES
    machines = tuple(args.machine) if args.machine else MACHINES

    pages = fetch_inventory()
    refs = select_refs(pages, locales=locales, machines=machines)
    if args.section:
        refs = [ref for ref in refs if ref.section in args.section]
    if args.paths_file:
        allowed = _read_paths(args.paths_file)
        refs = [ref for ref in refs if ref.path in allowed]
    if args.limit:
        refs = refs[: args.limit]

    print(f"inventory={len(pages)} selected={len(refs)}")
    if args.list:
        for ref in refs:
            updated = ref.official_updated_at or "-"
            print(f"{ref.locale}\t{ref.machine}\t{ref.section}\t{updated}\t{ref.path}")
        return 0

    store = None if args.dry_run else IngestStore(args.db)
    try:
        report = run_ingestion(
            refs,
            HttpFetcher(delay=args.delay),
            store,
            deactivate_missing=args.deactivate_missing,
        )
    finally:
        if store is not None:
            store.close()

    print(
        f"parsed={report.parsed} inserted={report.inserted} updated={report.updated} "
        f"unchanged={report.unchanged} failed={report.failed} disabled={report.disabled} "
        f"run={report.run_id}"
    )
    for failure in report.failures[:20]:
        print(
            f"FAIL {failure.stage}: {failure.source_url} :: {failure.error_type}: {failure.message}"
        )
    return 1 if args.strict and report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
