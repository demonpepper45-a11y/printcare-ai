"""Data structures shared by the ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

SUPPORTED_LOCALES = ("en", "zh")
MACHINES = ("a1", "a1_mini")
SECTIONS = ("maintenance", "troubleshooting", "manual", "other")

WIKI_BASE_URL = "https://wiki.bambulab.com"


@dataclass(frozen=True)
class DocumentRef:
    """A page discovered in the official inventory."""

    locale: str
    path: str
    title: str
    official_updated_at: str | None = None

    @property
    def source_url(self) -> str:
        return f"{WIKI_BASE_URL}/{self.locale}/{self.path}"

    @property
    def machine(self) -> str:
        if self.path.startswith("a1-mini/"):
            return "a1_mini"
        return "a1"

    @property
    def section(self) -> str:
        parts = self.path.split("/")
        candidate = parts[1] if len(parts) > 1 else ""
        return candidate if candidate in SECTIONS else "other"


@dataclass(frozen=True)
class ImageRef:
    """An image reference kept as URL plus alt text; binaries are never stored."""

    src: str
    alt: str = ""


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str | None = None


@dataclass(frozen=True)
class Paragraph:
    text: str
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    items: tuple[str, ...]
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True)
class TableBlock:
    rows: tuple[tuple[str, ...], ...]
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True)
class QuoteBlock:
    text: str


Span = Heading | Paragraph | ListBlock | TableBlock | QuoteBlock


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    ordinal: int
    heading_path: tuple[str, ...]
    anchor: str | None
    text: str
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    blocks: tuple[Span, ...]
    chunks: tuple[Chunk, ...]
    content_hash: str
    title: str = ""


@dataclass(frozen=True)
class DocumentRecord:
    """Metadata persisted for one document; chunks live in their own table."""

    doc_id: str
    canonical_path: str
    locale: str
    source_url: str
    title: str
    machines: tuple[str, ...]
    section: str
    content_hash: str
    retrieved_at: str
    ingested_at: str
    official_updated_at: str | None = None
    shared_reason: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class Failure:
    source_url: str
    stage: str
    error_type: str
    message: str


@dataclass
class IngestReport:
    started_at: str
    finished_at: str | None = None
    run_id: str = ""
    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    disabled: int = 0
    failures: list[Failure] = field(default_factory=list)
