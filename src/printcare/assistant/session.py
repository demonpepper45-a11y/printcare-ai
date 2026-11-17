"""Conversation state for multi-turn troubleshooting."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    machine: str
    reported_issue: str | None
    attempted_steps: tuple[str, ...]
    updated_at: str


@dataclass
class Session:
    session_id: str
    machine: str
    reported_issue: str | None = None
    attempted_steps: list[str] = field(default_factory=list)
    fault_ticket: dict[str, object] | None = None
    corrections: list[dict[str, str]] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def create(cls, machine: str) -> Session:
        return cls(session_id=f"s_{uuid.uuid4().hex[:16]}", machine=machine, updated_at=_now())

    def summary(self) -> SessionSummary:
        return SessionSummary(
            session_id=self.session_id,
            machine=self.machine,
            reported_issue=self.reported_issue,
            attempted_steps=tuple(self.attempted_steps),
            updated_at=self.updated_at,
        )

    def correct_machine(self, machine: str) -> None:
        if machine == self.machine:
            return
        self.corrections.append(
            {"field": "machine", "from": self.machine, "to": machine, "at": _now()}
        )
        self.machine = machine
        self.history.clear()
        self.reported_issue = None
        self.attempted_steps.clear()
        self.fault_ticket = None
        self.updated_at = _now()

    def record_turn(self, question: str, status: str, *, record_issue: bool = True) -> None:
        if record_issue and not self.reported_issue:
            self.reported_issue = question.strip()[:200]
        self.history.append({"question": question.strip()[:200], "status": status})
        self.history = self.history[-5:]
        self.updated_at = _now()

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "machine": self.machine,
            "reported_issue": self.reported_issue,
            "attempted_steps": list(self.attempted_steps),
            "fault_ticket": self.fault_ticket,
            "corrections": list(self.corrections),
            "history": list(self.history),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Session:
        return cls(
            session_id=str(payload["session_id"]),
            machine=str(payload["machine"]),
            reported_issue=payload.get("reported_issue") or None,
            attempted_steps=[str(item) for item in payload.get("attempted_steps") or []],
            fault_ticket=payload.get("fault_ticket") or None,
            corrections=list(payload.get("corrections") or []),
            history=list(payload.get("history") or []),
            updated_at=str(payload.get("updated_at") or ""),
        )

    @classmethod
    def load(cls, path: Path) -> Session:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
