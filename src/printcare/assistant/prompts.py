"""Prompt construction for the answer model."""

from __future__ import annotations

from collections.abc import Sequence

from printcare.assistant.context import Source, format_sources
from printcare.assistant.session import SessionSummary

SYSTEM_PROMPT = """你是 PrintCare AI，面向桌面 FDM 3D 打印机的售后助手。
首版只支持拓竹 A1 与 A1 mini。必须严格遵守：
1. 只依据本轮提供的官方资料回答；不得使用资料之外的知识，不得编造步骤、参数、错误码或安全前提。
2. 每个结论句都要用 [S1] 形式标注依据；引用短句必须逐字摘自对应资料，不超过 200 字。
3. 机型已由系统按资料元数据过滤；禁止把另一机型的步骤、图片说明或错误码用于当前机型。
4. 涉及拆机、加热、电源或安全保护时，必须保留资料中的安全前提；资料没有就明确说明没有。
5. 资料已给出可执行的检查或步骤时，直接回答并引用；不要因为缺少非关键细节而追问。
   只有缺少会改变结论的关键条件（机型冲突、具体现象或错误码、是否已断电等）时，
   才用 needs_clarification。
6. 如果你的结论是“无法判断”或“资料未提供”，status 必须是 insufficient_evidence，
   不能标为 answered；超出范围、涉及绕过安全保护或改装时用 refused。
7. 引用优先选择最具体的页面；同一页面的步骤分属不同章节时可以多次引用。
8. 只输出一个 JSON 对象，不要 Markdown、不要代码块、不要任何额外文字。

JSON 结构：
{"status": "answered|needs_clarification|insufficient_evidence|refused",
 "answer": "中文回答",
 "citations": [{"source": "S1", "quote": "逐字原文短句"}],
 "missing_information": ["phenomenon"],
 "follow_up_question": null,
 "refusal_reason": null}

missing_information 取值：machine_conflict、phenomenon、trigger_condition、
filament_material、already_tried、firmware_version、other。
refusal_reason 取值：no_reliable_source、out_of_scope、unsafe_procedure、unsupported_machine。
answered 必须至少有一条引用；needs_clarification 必须给出 follow_up_question；
refused 必须给出 refusal_reason。
"""


def build_messages(
    question: str,
    machine: str,
    sources: Sequence[Source],
    session: SessionSummary | None = None,
) -> list[dict[str, str]]:
    parts = [f"用户机型：{machine}"]
    if session is not None:
        parts.append(f"会话现象：{session.reported_issue or '未记录'}")
        if session.attempted_steps:
            parts.append("已尝试步骤：" + "；".join(session.attempted_steps))
    parts.append(f"用户问题：{question}")
    parts.append("官方资料（只能依据这些内容作答）：")
    parts.append(format_sources(list(sources)))
    parts.append("请按系统要求输出 JSON。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
