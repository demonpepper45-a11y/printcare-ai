"""Answer orchestration: retrieval, model call, citation checks and status mapping."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from printcare.assistant.context import (
    Citation,
    build_sources,
    parse_model_payload,
    select_sources,
    validate_citations,
)
from printcare.assistant.prompts import build_messages
from printcare.assistant.provider import ModelProvider
from printcare.assistant.session import Session, SessionSummary
from printcare.retrieval.retriever import Retriever

VALID_STATUSES = {"answered", "needs_clarification", "insufficient_evidence", "refused"}
VALID_MISSING = {
    "machine_conflict",
    "phenomenon",
    "trigger_condition",
    "filament_material",
    "already_tried",
    "firmware_version",
    "other",
}
VALID_REFUSALS = {"no_reliable_source", "out_of_scope", "unsafe_procedure", "unsupported_machine"}
CITATION_MARKER_RE = re.compile(r"\[S\d+\]")
UNCERTAIN_CONCLUSION_PHRASES = (
    "无法判断",
    "无法直接判断",
    "无法确定",
    "不能确定",
    "无法给出结论",
    "无法得出结论",
)

NO_HITS_ANSWER = "现有官方资料没有覆盖这个问题，无法给出有依据的结论。"
BAD_CITATIONS_ANSWER = "检索到的官方资料不足以支持一个可核验的结论，因此不给出具体步骤。"
UNSUPPORTED_ANSWER = "首版只支持拓竹 A1 与 A1 mini，无法回答其他机型的问题。"
DEFAULT_FOLLOW_UP = "请补充具体现象、发生时机和已经尝试过的步骤。"
DEFAULT_REFUSAL_ANSWER = "这个问题超出首版可依据官方资料回答的范围。"


def display_machine(machine: str) -> str:
    return "A1 mini" if machine == "a1_mini" else "A1"


@dataclass(frozen=True)
class MachineCheck:
    requested: str
    detected_in_question: tuple[str, ...]
    result: str


@dataclass(frozen=True)
class ChatResult:
    request_id: str
    session_id: str
    status: str
    answer: str
    citations: tuple[Citation, ...]
    missing_information: tuple[str, ...]
    follow_up_question: str | None
    refusal_reason: str | None
    machine_check: MachineCheck
    session: SessionSummary
    usage: dict[str, int] | None = None


class Assistant:
    """Machine-scoped RAG answerer with enforced citation invariants."""

    def __init__(
        self,
        retriever: Retriever,
        provider: ModelProvider,
        *,
        k: int = 8,
        max_per_doc: int = 3,
    ) -> None:
        self.retriever = retriever
        self.provider = provider
        self.k = k
        self.max_per_doc = max_per_doc

    def answer(
        self,
        question: str,
        machine: str,
        session: Session | None = None,
    ) -> ChatResult:
        text = question.strip()
        if not text:
            raise ValueError("question is empty")

        retrieval = self.retriever.query(text, machine, limit=self.k)
        detected = retrieval.detected_machines
        session = session or Session.create(machine)
        if session.machine != machine:
            session.correct_machine(machine)
        machine_check = MachineCheck(
            requested=machine,
            detected_in_question=detected,
            result="unknown" if not detected else "match",
        )

        if retrieval.warning == "machine_mismatch":
            other = "、".join(display_machine(item) for item in detected) or "另一机型"
            follow_up = (
                f"你问的是 {other}，但当前选择的是 {display_machine(machine)}。"
                "两者步骤不同，请确认机型后我再查对应资料。"
            )
            return self._finish(
                session,
                text,
                status="needs_clarification",
                answer="",
                citations=(),
                missing=("machine_conflict",),
                follow_up=follow_up,
                refusal=None,
                machine_check=MachineCheck(machine, detected, "mismatch"),
            )
        if retrieval.warning == "unsupported_machine_mentioned":
            return self._finish(
                session,
                text,
                status="refused",
                answer=UNSUPPORTED_ANSWER,
                citations=(),
                missing=(),
                follow_up=None,
                refusal="unsupported_machine",
                machine_check=machine_check,
            )
        if not retrieval.hits:
            return self._finish(
                session,
                text,
                status="refused",
                answer=NO_HITS_ANSWER,
                citations=(),
                missing=(),
                follow_up=None,
                refusal="no_reliable_source",
                machine_check=machine_check,
            )

        sources = build_sources(select_sources(retrieval.hits, self.max_per_doc))
        messages = build_messages(text, machine, sources, session.summary())
        raw = self.provider.complete(messages)
        payload = parse_model_payload(raw)
        status = _normalize_status(payload.get("status"))
        answer = str(payload.get("answer") or "").strip()
        citations, _dropped = validate_citations(payload.get("citations"), sources, machine=machine)
        missing = _normalize_missing(payload.get("missing_information"))
        follow_up = _optional_text(payload.get("follow_up_question"))
        refusal = _normalize_refusal(payload.get("refusal_reason"))

        if status == "answered" and not citations:
            status = "insufficient_evidence"
            answer = BAD_CITATIONS_ANSWER
            missing = missing or ("other",)
        elif status == "answered" and _states_uncertainty(answer):
            # The model listed related facts but concluded it cannot judge:
            # that is "insufficient evidence", not a supported answer.
            status = "insufficient_evidence"
            missing = missing or ("other",)

        return self._finish(
            session,
            text,
            status=status,
            answer=answer,
            citations=citations,
            missing=missing,
            follow_up=follow_up,
            refusal=refusal,
            machine_check=machine_check,
            usage=getattr(self.provider, "last_usage", None),
        )

    def _finish(
        self,
        session: Session,
        question: str,
        *,
        status: str,
        answer: str,
        citations: tuple[Citation, ...],
        missing: tuple[str, ...],
        follow_up: str | None,
        refusal: str | None,
        machine_check: MachineCheck,
        usage: dict[str, int] | None = None,
    ) -> ChatResult:
        if status == "answered":
            answer = answer or "无法给出回答。"
        elif status == "needs_clarification":
            citations = ()
            follow_up = follow_up or DEFAULT_FOLLOW_UP
            missing = missing or ("other",)
        elif status == "insufficient_evidence":
            citations = ()
            answer = answer or BAD_CITATIONS_ANSWER
            missing = missing or ("other",)
        else:
            citations = ()
            refusal = refusal or "no_reliable_source"
            answer = answer or DEFAULT_REFUSAL_ANSWER

        if status != "answered":
            answer = CITATION_MARKER_RE.sub("", answer).strip()

        session.record_turn(question, status)
        return ChatResult(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            session_id=session.session_id,
            status=status,
            answer=answer,
            citations=citations,
            missing_information=missing,
            follow_up_question=follow_up,
            refusal_reason=refusal,
            machine_check=machine_check,
            session=session.summary(),
            usage=usage,
        )


def _normalize_status(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in VALID_STATUSES else "insufficient_evidence"


def _normalize_missing(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text in VALID_MISSING and text not in seen:
            seen.append(text)
    return tuple(seen)


def _normalize_refusal(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in VALID_REFUSALS else None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _states_uncertainty(answer: str) -> bool:
    return any(phrase in answer for phrase in UNCERTAIN_CONCLUSION_PHRASES)
