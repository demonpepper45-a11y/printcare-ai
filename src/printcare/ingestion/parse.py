"""Turn wiki HTML into blocks, chunks and a content hash.

Wiki.js renders each page server-side inside ``<template slot="contents">``.
The parser keeps heading structure, lists, tables and image references, and
never stores image binaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

from printcare.ingestion.ids import (
    compute_chunk_id,
    compute_content_hash,
    compute_doc_id,
    normalize_whitespace,
)
from printcare.ingestion.models import (
    Chunk,
    DocumentRef,
    Heading,
    ImageRef,
    ListBlock,
    Paragraph,
    ParsedDocument,
    QuoteBlock,
    Span,
    TableBlock,
)

WIKI_HOST = "https://wiki.bambulab.com"
MAX_CHUNK_CHARS = 800
# Wiki.js sometimes renders unresolved template fields as a literal "None".
JUNK_PARAGRAPH_TEXTS = {"none", "null"}
# Some A1 pages embed maintenance sections for other models (e.g. "针对X1, P1系列打印机").
FOREIGN_MODEL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(x1c|x1e|x1|p1p|p1s|p2s|h2d|h2s|h2|a2l|x2d)(?![a-z0-9])"
)
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
SKIP_TAGS = {
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "button",
    "svg",
    "noscript",
}


class ParseError(RuntimeError):
    """Raised when a page yields no usable content."""


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document")
        self.stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse_document(html: str, ref: DocumentRef) -> ParsedDocument:
    """Parse one wiki page into blocks and chunks."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    contents = _find_contents(builder.root)
    if contents is None:
        raise ParseError('page has no <template slot="contents"> block')

    blocks = extract_blocks(contents)
    if not blocks:
        raise ParseError("page content has no usable blocks")

    doc_id = compute_doc_id(ref.locale, ref.path)
    chunks = build_chunks(doc_id, blocks)
    if not chunks:
        raise ParseError("page content produced no chunks")

    content_hash = compute_content_hash(render_document_text(blocks))
    return ParsedDocument(
        doc_id=doc_id,
        blocks=tuple(blocks),
        chunks=tuple(chunks),
        content_hash=content_hash,
        title=ref.title,
    )


def extract_blocks(node: _Node) -> list[Span]:
    """Walk the content node and produce ordered block spans."""
    spans: list[Span] = []
    _walk(node, spans)
    return spans


def build_chunks(doc_id: str, blocks: list[Span]) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen_ids: set[str] = set()
    heading_stack: list[Heading] = []
    texts: list[str] = []
    images: list[ImageRef] = []
    anchor: str | None = None

    def flush() -> None:
        nonlocal texts, images
        if any(FOREIGN_MODEL_RE.search(heading.text) for heading in heading_stack):
            # Content under another model's section must never be indexed for this page.
            texts = []
            images = []
            return
        text = "\n".join(part for part in texts if part).strip()
        if text:
            chunk_id = compute_chunk_id(doc_id, text)
            if chunk_id not in seen_ids:
                seen_ids.add(chunk_id)
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        ordinal=len(chunks),
                        heading_path=tuple(item.text for item in heading_stack),
                        anchor=anchor,
                        text=text,
                        images=_dedupe_images(images),
                    )
                )
        texts = []
        images = []

    for span in blocks:
        if isinstance(span, Heading):
            flush()
            heading_stack = [item for item in heading_stack if item.level < span.level]
            heading_stack.append(span)
            anchor = _nearest_anchor(heading_stack)
            continue
        rendered = render_block(span)
        if not rendered:
            continue
        candidate = "\n".join([*texts, rendered]) if texts else rendered
        if texts and len(candidate) > MAX_CHUNK_CHARS:
            flush()
        texts.append(rendered)
        images.extend(getattr(span, "images", ()))
    flush()
    return chunks


def render_block(span: Span) -> str:
    if isinstance(span, Paragraph):
        return normalize_whitespace(span.text)
    if isinstance(span, ListBlock):
        lines = []
        for index, item in enumerate(span.items, start=1):
            prefix = f"{index}." if span.ordered else "-"
            lines.append(f"{prefix} {item}")
        return "\n".join(lines)
    if isinstance(span, TableBlock):
        return "\n".join(" | ".join(cell for cell in row) for row in span.rows)
    if isinstance(span, QuoteBlock):
        return normalize_whitespace(span.text)
    return ""


def render_document_text(blocks: list[Span]) -> str:
    parts: list[str] = []
    for span in blocks:
        if isinstance(span, Heading):
            parts.append(f"{'#' * span.level} {span.text}")
        else:
            rendered = render_block(span)
            if rendered:
                parts.append(rendered)
    return "\n".join(parts)


def _walk(node: _Node, spans: list[Span]) -> None:
    if node.tag in SKIP_TAGS:
        return
    tag = node.tag.lower()
    if tag in HEADING_TAGS:
        spans.append(
            Heading(
                level=HEADING_TAGS[tag],
                text=normalize_whitespace(_text(node, include_images=False)),
                anchor=node.attrs.get("id") or None,
            )
        )
        return
    if tag == "p":
        paragraph = _paragraph(node)
        if paragraph is not None:
            spans.append(paragraph)
        return
    if tag in {"ul", "ol"} and _is_block_list(node):
        spans.append(_list_block(node, ordered=tag == "ol"))
        return
    if tag == "table":
        table = _table_block(node)
        if table is not None:
            spans.append(table)
        return
    if tag == "blockquote":
        text = normalize_whitespace(_text(node))
        if text:
            spans.append(QuoteBlock(text=text))
        return
    for child in node.children:
        if isinstance(child, _Node):
            _walk(child, spans)


def _paragraph(node: _Node) -> Paragraph | None:
    text = normalize_whitespace(_text(node))
    images = _collect_images(node)
    if text.lower() in JUNK_PARAGRAPH_TEXTS and not images:
        return None
    if not text and not images:
        return None
    return Paragraph(text=text, images=tuple(images))


def _is_block_list(node: _Node) -> bool:
    return any(
        isinstance(child, _Node) and child.tag.lower() in {"li", "ul", "ol"}
        for child in node.children
    )


def _list_block(node: _Node, ordered: bool) -> ListBlock:
    items: list[str] = []
    for child in node.children:
        if not isinstance(child, _Node) or child.tag.lower() != "li":
            continue
        item = normalize_whitespace(_text(child))
        if item:
            items.append(item)
    return ListBlock(ordered=ordered, items=tuple(items), images=tuple(_collect_images(node)))


def _table_block(node: _Node) -> TableBlock | None:
    rows: list[tuple[str, ...]] = []
    for row in _iter_descendants(node, "tr"):
        cells = [
            normalize_whitespace(_text(cell))
            for cell in row.children
            if isinstance(cell, _Node) and cell.tag.lower() in {"td", "th"}
        ]
        if cells:
            rows.append(tuple(cells))
    if not rows:
        return None
    return TableBlock(rows=tuple(rows), images=tuple(_collect_images(node)))


def _iter_descendants(node: _Node, tag: str):
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag.lower() == tag:
                yield child
            else:
                yield from _iter_descendants(child, tag)


def _text(node: _Node, include_images: bool = True) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag in SKIP_TAGS or "toc-anchor" in (child.attrs.get("class") or ""):
            continue
        elif child.tag.lower() == "img":
            if include_images:
                parts.append(_image_placeholder(child))
        elif child.tag.lower() == "br":
            parts.append(" ")
        else:
            parts.append(_text(child, include_images=include_images))
    return "".join(parts)


def _image_placeholder(node: _Node) -> str:
    alt = (node.attrs.get("alt") or "").strip()
    label = alt or unquote(node.attrs.get("src", "").rsplit("/", 1)[-1]) or "图片"
    return f"[图: {label}]"


def _collect_images(node: _Node) -> list[ImageRef]:
    images: list[ImageRef] = []
    for child in node.children:
        if not isinstance(child, _Node):
            continue
        if child.tag.lower() == "img":
            src = (child.attrs.get("src") or "").strip()
            if src:
                images.append(
                    ImageRef(
                        src=urljoin(f"{WIKI_HOST}/", src),
                        alt=(child.attrs.get("alt") or "").strip(),
                    )
                )
        elif child.tag not in SKIP_TAGS:
            images.extend(_collect_images(child))
    return images


def _find_contents(node: _Node) -> _Node | None:
    for child in node.children:
        if not isinstance(child, _Node):
            continue
        if child.tag.lower() == "template" and child.attrs.get("slot") == "contents":
            return child
        found = _find_contents(child)
        if found is not None:
            return found
    return None


def _nearest_anchor(headings: list[Heading]) -> str | None:
    for heading in reversed(headings):
        if heading.anchor:
            return heading.anchor
    return None


def _dedupe_images(images: list[ImageRef]) -> tuple[ImageRef, ...]:
    seen: set[str] = set()
    unique: list[ImageRef] = []
    for image in images:
        if image.src in seen:
            continue
        seen.add(image.src)
        unique.append(image)
    return tuple(unique)
