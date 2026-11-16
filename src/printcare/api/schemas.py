"""Pydantic schemas for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Machine = Literal["a1", "a1_mini"]
Status = Literal["answered", "needs_clarification", "insufficient_evidence", "refused"]
RefusalReason = Literal[
    "no_reliable_source", "out_of_scope", "unsafe_procedure", "unsupported_machine"
]
MissingInformation = Literal[
    "machine_conflict",
    "phenomenon",
    "trigger_condition",
    "filament_material",
    "already_tried",
    "firmware_version",
    "other",
]

SESSION_PATTERN = r"^s_[A-Za-z0-9]{16,32}$"


class CitationModel(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    source_url: str
    section_path: list[str]
    anchor: str | None = None
    machine: Machine
    official_updated_at: str | None = None
    quote: str
    quote_truncated: bool


class MachineCheckModel(BaseModel):
    requested: Machine
    detected_in_question: list[Machine]
    result: Literal["match", "mismatch", "unknown"]


class SessionModel(BaseModel):
    session_id: str
    machine: Machine
    reported_issue: str | None = None
    attempted_steps: list[str] = []
    updated_at: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    machine: Machine
    session_id: str | None = Field(default=None, pattern=SESSION_PATTERN)
    locale: Literal["zh", "en"] = "zh"


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    status: Status
    answer: str
    citations: list[CitationModel]
    missing_information: list[MissingInformation]
    follow_up_question: str | None = None
    refusal_reason: RefusalReason | None = None
    machine_check: MachineCheckModel
    session: SessionModel


class SessionPatch(BaseModel):
    machine: Machine | None = None
    reported_issue: str | None = Field(default=None, max_length=200)
    attempted_steps: list[str] | None = Field(default=None, max_length=10)


class FeedbackRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_PATTERN)
    solved: bool
    comment: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    id: int


class FailureModel(BaseModel):
    source_url: str
    stage: str
    error_type: str
    message: str


class RefreshRequest(BaseModel):
    paths: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class RefreshResponse(BaseModel):
    run_id: str
    parsed: int
    inserted: int
    updated: int
    unchanged: int
    failed: int
    disabled: int
    failures: list[FailureModel]


class DocumentModel(BaseModel):
    doc_id: str
    canonical_path: str
    locale: str
    title: str
    machines: list[str]
    section: str
    enabled: bool
    official_updated_at: str | None = None
    retrieved_at: str
    chunk_count: int


class DocumentPatch(BaseModel):
    enabled: bool


class HealthResponse(BaseModel):
    status: str
    documents: int
    chunks: int
    model: str


class MachineModel(BaseModel):
    code: Machine
    label: str


class FeedbackSummary(BaseModel):
    total: int
    solved: int
    unsolved: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
