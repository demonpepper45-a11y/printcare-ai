"""Answer orchestration: retrieval, model call, citation checks and status mapping."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from printcare.assistant.context import (
    Citation,
    build_sources,
    parse_model_payload,
    select_sources,
    validate_citations,
)
from printcare.assistant.definitions import find_hms_definition
from printcare.assistant.policy import (
    is_definition_question,
    needs_guide_only,
    refuses_modification,
)
from printcare.assistant.prompts import build_messages
from printcare.assistant.provider import ModelProvider
from printcare.assistant.session import Session, SessionSummary
from printcare.retrieval.retriever import Retriever
from printcare.retrieval.tokenize import detect_machines, detect_unsupported_models

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
UNCERTAIN_CONCLUSION_RE = re.compile(
    r"(无法|不能)[^。！？\n]{0,12}(判断|确定|判定|给出结论|得出结论)"
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
        # Resolve an elliptical follow-up before retrieval, not just in the
        # model prompt. Check the current question first so context cannot hide
        # a conflicting or unsupported model mention.
        issue = session.reported_issue
        if (
            not retrieval.warning
            and issue
            and re.match(
                r"^(那|然后|还是|仍然|已经|已|刚才|如果|试过|换了|第一步|第二步|下一步)", text
            )
            and set(detect_machines(issue)) <= {machine}
            and not detect_unsupported_models(issue)
        ):
            retrieval = self.retriever.query(f"{issue}\n{text}", machine, limit=self.k)
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
        if refuses_modification(retrieval.query):
            return self._finish(
                session,
                text,
                status="refused",
                answer="首版不提供加装腔体加热或绕过安全保护的改装指导，请咨询设备官方支持。",
                citations=(),
                missing=(),
                follow_up=None,
                refusal="unsafe_procedure",
                machine_check=machine_check,
            )
        # A conjunction is a request about both topics. Search each explicitly;
        # do not let the dominant topic consume the entire source window.
        combined_query = retrieval.query
        if "热床" in combined_query and "电路" in combined_query:
            extra = self.retriever.query("电路故障", machine, limit=12)
            existing = {hit.chunk_id for hit in retrieval.hits}
            additions = tuple(
                hit for hit in extra.hits if "电路" in hit.title and hit.chunk_id not in existing
            )[:2]
            retrieval = replace(retrieval, hits=retrieval.hits + additions)
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
        if is_definition_question(text):
            definition = find_hms_definition(text, sources)
            if definition is not None:
                source, meaning = definition
                citations, _ = validate_citations(
                    [{"source": source.label, "quote": meaning}], sources, machine=machine
                )
                if citations:
                    return self._finish(
                        session,
                        text,
                        status="answered",
                        answer=f"该错误码的官方定义是：{meaning} [{source.label}]。",
                        citations=citations,
                        missing=(),
                        follow_up=None,
                        refusal=None,
                        machine_check=machine_check,
                    )
        messages = build_messages(text, machine, sources, session.summary())
        raw = self.provider.complete(messages)
        payload = parse_model_payload(raw)
        status = _normalize_status(payload.get("status"))
        answer = str(payload.get("answer") or "").strip()
        citations, _dropped = validate_citations(payload.get("citations"), sources, machine=machine)
        missing = _normalize_missing(payload.get("missing_information"))
        follow_up = _optional_text(payload.get("follow_up_question"))
        refusal = _normalize_refusal(payload.get("refusal_reason"))

        valid_chunks = {citation.chunk_id for citation in citations}
        valid_markers = {
            f"[{source.label}]" for source in sources if source.hit.chunk_id in valid_chunks
        }
        markers = set(CITATION_MARKER_RE.findall(answer))
        if status == "answered" and (not citations or not markers <= valid_markers):
            status = "insufficient_evidence"
            answer = BAD_CITATIONS_ANSWER
            missing = missing or ("other",)
        elif status == "answered" and _states_uncertainty(answer):
            # The model listed related facts but concluded it cannot judge:
            # that is "insufficient evidence", not a supported answer.
            status = "insufficient_evidence"
            missing = missing or ("other",)

        if status == "answered" and (
            needs_guide_only(answer) or ("热床" in text and "电路" in text)
        ):
            # Do not emit model-written invasive procedures until their safety
            # dependencies can be verified. Preserve only official guide titles.
            cited_docs = {citation.doc_id for citation in citations}
            chosen = []
            seen_docs = set()
            for source in sources:
                hit = source.hit
                requested_circuit = "电路" in text and "电路" in hit.title
                if (hit.doc_id in cited_docs or requested_circuit) and hit.doc_id not in seen_docs:
                    chosen.append(source)
                    seen_docs.add(hit.doc_id)
            answer = (
                "该问题涉及设备维护；当前仅提供官方指南入口，完整步骤及前置条件请在原文核对：\n"
            )
            answer += "\n".join(f"- {source.hit.title} [{source.label}]" for source in chosen)
            citations, _ = validate_citations(
                [{"source": source.label, "quote": source.hit.title[:200]} for source in chosen],
                sources,
                machine=machine,
            )
        elif status == "insufficient_evidence":
            # Dropping citation markers alone left uncited repair suggestions.
            answer = BAD_CITATIONS_ANSWER
        elif status == "refused":
            answer = DEFAULT_REFUSAL_ANSWER

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

        session.record_turn(question, status, record_issue=machine_check.result != "mismatch")
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
    return bool(UNCERTAIN_CONCLUSION_RE.search(answer))
