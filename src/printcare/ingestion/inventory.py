"""Read the official Wiki.js inventory and turn it into :class:`DocumentRef`.

Only metadata is retrieved here: the GraphQL ``pages.list`` query returns path,
title, locale and update time, while page bodies require authorisation
(see ``docs/sources.md``).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any

from printcare.ingestion.ids import canonical_path, compute_doc_id
from printcare.ingestion.models import SUPPORTED_LOCALES, DocumentRef

GRAPHQL_ENDPOINT = "https://wiki.bambulab.com/graphql"
INVENTORY_QUERY = "query { pages { list { id path title updatedAt locale } } }"
DEFAULT_USER_AGENT = (
    "PrintCareAI-Ingestion/0.1 (+https://github.com/demonpepper45-a11y/printcare-ai)"
)
MAX_INVENTORY_BYTES = 64 * 1024 * 1024

PostJson = Callable[[str, dict[str, Any], int], bytes]


class InventoryError(RuntimeError):
    """Raised when the inventory cannot be retrieved or decoded."""


def _default_post_json(url: str, payload: dict[str, Any], timeout: int) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": DEFAULT_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_INVENTORY_BYTES)


def fetch_inventory(
    post_json: PostJson | None = None,
    timeout: int = 90,
) -> list[dict[str, Any]]:
    """Return the raw page list from the official GraphQL endpoint."""
    sender = post_json or _default_post_json
    payload = {"query": INVENTORY_QUERY}
    try:
        raw = sender(GRAPHQL_ENDPOINT, payload, timeout)
    except Exception as exc:  # noqa: BLE001 - wrapped for a diagnosable message
        raise InventoryError(f"inventory request failed: {type(exc).__name__}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InventoryError("inventory response is not valid JSON") from exc

    errors = data.get("errors")
    if errors:
        raise InventoryError(f"inventory query returned {len(errors)} error(s)")
    pages = (data.get("data") or {}).get("pages", {}).get("list")
    if not isinstance(pages, list):
        raise InventoryError("inventory response has no pages.list array")
    return pages


def select_refs(
    pages: list[dict[str, Any]],
    locales: tuple[str, ...] = SUPPORTED_LOCALES,
    machines: tuple[str, ...] = ("a1", "a1_mini"),
) -> list[DocumentRef]:
    """Filter inventory rows to the A1 family and supported locales.

    Duplicate ``(locale, path)`` rows (case variants included) collapse onto the
    newest ``updatedAt`` so the same page is never ingested twice.
    """
    chosen: dict[tuple[str, str], DocumentRef] = {}
    for page in pages:
        locale = str(page.get("locale") or "")
        raw_path = str(page.get("path") or "")
        if locale not in locales or not raw_path:
            continue
        path = canonical_path(raw_path)
        if not (path.startswith("a1/") or path.startswith("a1-mini/")):
            continue
        ref = DocumentRef(
            locale=locale,
            path=path,
            title=str(page.get("title") or path),
            official_updated_at=_as_text(page.get("updatedAt")),
        )
        if ref.machine not in machines:
            continue
        key = (locale, path)
        existing = chosen.get(key)
        if existing is None or (ref.official_updated_at or "") > (
            existing.official_updated_at or ""
        ):
            chosen[key] = ref
    return sorted(chosen.values(), key=lambda item: (item.locale, item.path))


def group_by_doc_id(refs: list[DocumentRef]) -> dict[str, DocumentRef]:
    """Map deterministic document ids to refs, keeping the newest duplicate."""
    grouped: dict[str, DocumentRef] = {}
    for ref in refs:
        doc_id = compute_doc_id(ref.locale, ref.path)
        grouped.setdefault(doc_id, ref)
    return grouped


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
