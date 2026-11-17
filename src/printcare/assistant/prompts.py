"""Prompt construction for the answer model."""

from __future__ import annotations

from collections.abc import Sequence

from printcare.assistant.context import Source, format_sources
from printcare.assistant.fault_ticket import FaultTicket
from printcare.assistant.policy import is_definition_question
from printcare.assistant.session import SessionSummary
from printcare.retrieval.safety import is_safety_heading

SYSTEM_PROMPT = """你是 PrintCare AI，面向桌面 FDM 3D 打印机的售后助手。
首版只支持拓竹 A1 与 A1 mini。必须严格遵守：
1. 只依据本轮提供的官方资料回答；不得使用资料之外的知识，不得编造步骤、参数、错误码或安全前提。
2. 每个结论句都要用 [S1] 形式标注依据；引用短句必须逐字摘自对应资料，不超过 200 字。
   摘录必须是连续原文，不得跳过图占位符或改写标点；每个来源摘一条最有用的短句即可。
   正文每个 [S编号] 都必须在 citations 中有有效摘录。
3. 机型已由系统按资料元数据过滤；禁止把另一机型的步骤、图片说明或错误码用于当前机型。
4. 涉及拆机、加热、电源或安全保护时，必须保留资料中的安全提示、所需工具和适用条件；
   资料缺少对应安全前提时，不得仅用“自行确认安全”后继续给出拆装、接线或带电测量步骤；
   可以概述官方排查方向并引用，具体操作引导查看完整官方指南或联系官方支持。
5. 资料已给出可执行的检查或步骤时，直接回答并引用；不要因为缺少非关键细节而追问。
   只有缺少会改变结论的关键条件（机型冲突、具体现象或错误码、是否已断电等）时，
   才用 needs_clarification。
6. 如果你的结论是“无法判断”或“资料未提供”，status 必须是 insufficient_evidence，
   不能标为 answered；实际请求绕过安全保护或改装时用 refused。
   用户明确否定改装意图，或引用他人危险说法询问含义，不等于要求执行；应回答其实际正常咨询。
7. 引用优先选择最具体的页面；同一页面的步骤分属不同章节时可以多次引用。
8. 保持官方步骤的先后顺序和适用条件；多种替代方法分别说明，禁止合并成连续操作。
   首选常规方案，临时方案必须明确标出；不要把带电与断电检查的条件混写。
9. 回答保持简洁，优先给关键判断与下一步，避免复述整篇指南。
10. 只输出一个 JSON 对象，不要 Markdown、不要代码块、不要任何额外文字。

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
    ticket: FaultTicket | None = None,
) -> list[dict[str, str]]:
    parts = [f"用户机型：{machine}"]
    if session is not None:
        parts.append(f"会话现象：{session.reported_issue or '未记录'}")
        if session.attempted_steps:
            parts.append("已尝试步骤：" + "；".join(session.attempted_steps))
    parts.append(f"用户问题：{question}")
    if ticket is not None:
        parts.append("当前故障单（已知信息）：")
        parts.append(_ticket_text(ticket))
        parts.append("回答时先用一句话确认故障单中的已知信息。")
        if ticket.asked:
            parts.append(
                "关键分支信息已收集；不要再追问耗材、阶段等非阻塞项，"
                "直接依据官方资料给出下一步排查方向或官方指南入口。"
            )
    if is_definition_question(question):
        parts.append("本轮只解释错误码或术语的含义；不主动添加维修、拆装、接线或测量步骤。")
    if any(is_safety_heading(source.hit.heading_path) for source in sources):
        parts.append(
            "本轮已附官方安全提示/所需工具/适用条件片段；涉及维护时必须保留并引用，"
            "不得声称资料未提供安全前提。"
        )
    parts.append("官方资料（只能依据这些内容作答）：")
    parts.append(format_sources(list(sources)))
    parts.append("请按系统要求输出 JSON。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _ticket_text(ticket: FaultTicket) -> str:
    lines = [
        f"机型：{ticket.machine}",
        f"现象：{ticket.symptom or '待确认'}",
        f"错误码：{ticket.error_code or '未知'}",
        f"耗材：{ticket.filament or '待确认'}",
        f"供料方式：{ticket.feed_method or '待确认'}",
        f"发生阶段：{ticket.stage or '待确认'}",
        f"已经尝试：{'；'.join(ticket.attempted_steps) or '待确认'}",
    ]
    return "\n".join(lines)
