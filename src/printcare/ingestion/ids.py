"""Deterministic identifiers and text normalisation for ingested documents.

The rules mirror ``docs/interfaces.md``:

* ``doc_id`` is derived from locale and canonical path, so re-ingesting the same
  page keeps a stable identifier.
* ``chunk_id`` embeds a hash of the chunk text, so edited text produces a new
  identifier and stale citations can be detected.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote

WHITESPACE_RE = re.compile(r"[\s\u00a0]+")
SLASHES_RE = re.compile(r"/{2,}")


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace (including non-breaking spaces) into single spaces."""
    return WHITESPACE_RE.sub(" ", text).strip()


def canonical_path(raw_path: str) -> str:
    """Normalise a wiki path: drop query/fragment, collapse slashes, lowercase."""
    path = unquote(raw_path).strip()
    path = path.split("#", 1)[0].split("?", 1)[0]
    path = SLASHES_RE.sub("/", path)
    return path.strip("/").lower()


def compute_doc_id(locale: str, canonical: str) -> str:
    digest = hashlib.sha256(f"{locale}\n{canonical}".encode()).hexdigest()
    return f"doc_{digest[:16]}"


def compute_chunk_id(doc_id: str, text: str) -> str:
    digest = hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()
    return f"{doc_id}#{digest[:10]}"


def compute_content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()
