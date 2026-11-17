"""Structured fault ticket extracted from the user's description.

The ticket keeps only what the user actually said. Unknown fields stay empty so
the assistant can ask about the few fields that change the next diagnostic step
instead of dumping a generic questionnaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from printcare.retrieval.tokenize import extract_hms_codes

FIELD_LABELS = {
    "symptom": "现象",
    "error_code": "错误码",
    "filament": "耗材",
    "feed_method": "供料方式",
    "stage": "发生阶段",
    "attempted_steps": "已经尝试",
}

FLOW_QUESTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "no_extrusion": (
        ("error_code", "屏幕上是否显示错误码或提示？"),
        ("feed_method", "耗材是外置料架还是 AMS lite 供料？"),
    ),
    "clog": (
        ("feed_method", "耗材是外置料架还是 AMS lite 供料？"),
        ("error_code", "屏幕上是否显示错误码或提示？"),
        ("filament", "当前使用的是什么耗材？"),
    ),
    "heatbed": (
        ("error_code", "屏幕上是否显示错误码或提示？"),
        ("stage", "热床是在准备阶段还是打印过程中不升温？"),
    ),
    "first_layer": (
        ("feed_method", "耗材是外置料架还是 AMS lite 供料？"),
        ("filament", "当前使用的是什么耗材？"),
    ),
    "hms": (("stage", "错误码是在什么操作阶段出现的？"),),
    "generic": (
        ("error_code", "屏幕上是否显示错误码或提示？"),
        ("symptom", "具体是什么现象、在什么阶段出现？"),
    ),
}

DETAILED_REQUEST_RE = re.compile(r"清理|拆|检查|步骤|怎么处理|堵塞|卡住|如何解决")


@dataclass(frozen=True)
class FaultTicket:
    machine: str
    symptom: str | None = None
    error_code: str | None = None
    filament: str | None = None
    feed_method: str | None = None
    stage: str | None = None
    attempted_steps: tuple[str, ...] = ()
    flow: str = "generic"
    asked: tuple[str, ...] = ()

    @property
    def missing(self) -> tuple[str, ...]:
        values = {
            "symptom": self.symptom,
            "error_code": self.error_code,
            "filament": self.filament,
            "feed_method": self.feed_method,
            "stage": self.stage,
            "attempted_steps": self.attempted_steps,
        }
        return tuple(key for key, value in values.items() if not value)

    def clarification_fields(self) -> tuple[str, ...]:
        fields = [
            field
            for field, _question in FLOW_QUESTIONS.get(self.flow, FLOW_QUESTIONS["generic"])
            if not _value_for(self, field) and field not in self.asked
        ]
        return tuple(fields)

    def should_clarify(self, question: str) -> bool:
        """Only vague no-extrusion descriptions preempt the normal answer flow."""
        if self.flow != "no_extrusion":
            return False
        if DETAILED_REQUEST_RE.search(question):
            return False
        return bool(self.clarification_fields())

    def clarification_text(self) -> str:
        fields = self.clarification_fields()
        questions = [
            question
            for field, question in FLOW_QUESTIONS.get(self.flow, FLOW_QUESTIONS["generic"])
            if field in fields
        ]
        if not questions:
            return ""
        questions = [question.rstrip("？?；; ") + "？" for question in questions]
        joined = " ".join(f"{index}）{question}" for index, question in enumerate(questions, 1))
        return f"为了继续排查，请先确认：{joined}"

    def mark_asked(self) -> FaultTicket:
        fields = self.clarification_fields()
        asked = tuple(dict.fromkeys([*self.asked, *fields]))
        return replace(self, asked=asked)

    def missing_information(self) -> tuple[str, ...]:
        mapping = {
            "symptom": "phenomenon",
            "error_code": "error_code",
            "feed_method": "feed_method",
            "filament": "filament_material",
            "stage": "stage",
            "attempted_steps": "already_tried",
        }
        return tuple(mapping[field] for field in self.clarification_fields() if field in mapping)

    def to_dict(self) -> dict[str, object]:
        return {
            "machine": self.machine,
            "symptom": self.symptom,
            "error_code": self.error_code,
            "filament": self.filament,
            "feed_method": self.feed_method,
            "stage": self.stage,
            "attempted_steps": list(self.attempted_steps),
            "flow": self.flow,
            "asked": list(self.asked),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object] | None) -> FaultTicket | None:
        if not payload:
            return None
        return cls(
            machine=str(payload.get("machine") or ""),
            symptom=_optional(payload.get("symptom")),
            error_code=_optional(payload.get("error_code")),
            filament=_optional(payload.get("filament")),
            feed_method=_optional(payload.get("feed_method")),
            stage=_optional(payload.get("stage")),
            attempted_steps=tuple(str(item) for item in payload.get("attempted_steps") or ()),
            flow=str(payload.get("flow") or "generic"),
            asked=tuple(str(item) for item in payload.get("asked") or ()),
        )


def update_ticket(
    previous: FaultTicket | None,
    question: str,
    machine: str,
) -> FaultTicket:
    """Merge new user text into the previous ticket without erasing known fields."""
    symptom = _extract_symptom(question)
    error_code = _extract_error_code(question)
    filament = _extract_filament(question)
    feed_method = _extract_feed_method(question)
    stage = _extract_stage(question)
    attempted = _extract_attempted(question)

    if previous is None or previous.machine != machine:
        previous = None

    if previous is not None:
        symptom = symptom or previous.symptom
        error_code = error_code or previous.error_code
        filament = filament or previous.filament
        feed_method = feed_method or previous.feed_method
        stage = stage or previous.stage
        attempted = tuple(dict.fromkeys([*previous.attempted_steps, *attempted]))
        asked = previous.asked
    else:
        asked = ()

    merged_symptom = symptom or (previous.symptom if previous else None)
    flow = _classify_flow(f"{merged_symptom or ''} {question}", error_code)
    if flow == "generic" and previous is not None:
        flow = previous.flow

    return FaultTicket(
        machine=machine,
        symptom=merged_symptom,
        error_code=error_code,
        filament=filament,
        feed_method=feed_method,
        stage=stage,
        attempted_steps=attempted,
        flow=flow,
        asked=asked,
    )


def _value_for(ticket: FaultTicket, field: str) -> object:
    return {
        "symptom": ticket.symptom,
        "error_code": ticket.error_code,
        "filament": ticket.filament,
        "feed_method": ticket.feed_method,
        "stage": ticket.stage,
    }.get(field) or (ticket.attempted_steps if field == "attempted_steps" else None)


def _optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _extract_symptom(question: str) -> str | None:
    text = question.strip()
    text = re.sub(r"(?i)\bA1\s*mini\b|\bA1\b", " ", text)
    clauses = [item.strip() for item in re.split(r"[，,。；;！？!?\n]", text) if item.strip()]
    symptom_re = re.compile(
        r"不出料|没出料|不挤出|断料|挤不出|堵|卡住|热床|床温|不加热|不升温|"
        r"首层|第一层|不粘|层纹|拉丝|漏料|错误码|HMS|报警|异响",
        re.I,
    )
    chosen = next((clause for clause in clauses if symptom_re.search(clause)), None)
    if chosen is None:
        chosen = clauses[0] if clauses else ""
    chosen = re.sub(r"^(请问|我的|打印机)\s*", "", chosen).strip()
    chosen = re.sub(
        r"(怎么处理|怎么办|如何解决|怎么做|怎么修|怎么清理|如何清理|呢|吗|？|\?)\s*$",
        "",
        chosen,
    ).strip()
    chosen = re.sub(r"(怎么|如何|怎样)[^，。]*$", "", chosen).strip()
    chosen = re.sub(r"\s+", " ", chosen)
    if not chosen or _is_short_answer(chosen):
        return None
    return chosen[:60]


def _is_short_answer(question: str) -> bool:
    text = question.strip()
    if len(text) > 24:
        return False
    return not re.search(r"不出料|没出料|不挤出|堵|热床|首层", text, re.I)


def _extract_error_code(question: str) -> str | None:
    codes = extract_hms_codes(question)
    if codes:
        return codes[0]
    if re.search(r"没有(任何)?错误码|无错误码|不显示错误码|没有报错", question):
        return "无"
    return None


def _extract_filament(question: str) -> str | None:
    match = re.search(r"(?i)\b(PLA|PETG|ABS|ASA|TPU|TPE|PVA|PA|PC)\b|尼龙", question)
    return match.group(0).upper() if match else None


def _extract_feed_method(question: str) -> str | None:
    if re.search(r"(?i)AMS\s*lite|AMS Lite", question):
        return "AMS lite"
    if re.search(r"(?i)\bAMS\b", question):
        return "AMS"
    if re.search(r"外置料架|外挂料架|外置料盘|料架|external spool|spool holder", question, re.I):
        return "外置料架"
    if re.search(r"不知道|不确定|不清楚", question):
        return "未知"
    return None


def _extract_stage(question: str) -> str | None:
    if re.search(r"首层|第一层", question):
        return "首层"
    if re.search(r"打印中|打印时|打印过程|打印过程中", question):
        return "打印中"
    if re.search(r"准备|预热|调平|开机|待机", question):
        return "准备中"
    if re.search(r"打印后|完成后", question):
        return "打印后"
    if re.search(r"换料|装料|上料", question):
        return "换料/装料"
    return None


def _extract_attempted(question: str) -> tuple[str, ...]:
    steps: list[str] = []
    for clause in re.split(r"[，,。；;\n]", question):
        clause = clause.strip()
        if not clause or re.search(r"怎么|如何|是否|吗|？|\?", clause):
            continue
        if not re.search(r"已|尝试|试过|重新|重启|清洁|清理|更换|校准|拧|插|装料|上料", clause):
            continue
        cleaned = re.sub(r"^(已经?|尝试|试过|重新)\s*[:：]?\s*", "", clause).strip()
        cleaned = re.sub(r"^(已经?|尝试)\s*", "", cleaned).strip()
        if cleaned:
            steps.append(cleaned[:40])
    if re.search(r"未解决|没解决|仍然|还是", question) and steps:
        steps = [f"{steps[0]}（未解决）", *steps[1:]]
    return tuple(dict.fromkeys(steps))[:5]


def _classify_flow(question: str, error_code: str | None) -> str:
    if error_code and error_code != "无":
        return "hms"
    if re.search(r"热床|床温|不加热|不升温", question):
        return "heatbed"
    if re.search(r"首层|第一层", question):
        return "first_layer"
    if re.search(r"堵|卡住|残料|黏连|粘连", question):
        return "clog"
    if re.search(r"不出料|没出料|不挤出|断料|空打|挤不出", question):
        return "no_extrusion"
    return "generic"
