"""Detect official safety, tool and applicability sections."""

import re

SAFETY_HEADING_RE = re.compile(
    r"安全提示|安全须知|安全说明|安全警告|注意事项|重要提醒|警告|"
    r"所需工具|所需材料|工具和材料|工具与材料|工具|前期操作|适用条件|适用范围|前置条件|前提"
)


def is_safety_heading(heading_path: tuple[str, ...]) -> bool:
    return any(SAFETY_HEADING_RE.search(part) for part in heading_path)


def safety_rank(heading_path: tuple[str, ...]) -> int:
    return safety_category(heading_path)


def safety_category(heading_path: tuple[str, ...]) -> int:
    """0 = safety warning, 1 = tools/materials, 2 = preconditions, 3 = other."""
    text = " ".join(heading_path)
    if "安全" in text or "警告" in text or "注意" in text:
        return 0
    if "工具" in text or "材料" in text:
        return 1
    if "前期" in text or "适用" in text or "前提" in text:
        return 2
    return 3
