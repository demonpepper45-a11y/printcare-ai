"""Answer exact HMS meaning queries from visible official titles."""

import re

from printcare.assistant.context import Source
from printcare.assistant.policy import needs_guide_only
from printcare.retrieval.tokenize import extract_hms_codes


def find_hms_definition(question: str, sources: list[Source]) -> tuple[Source, str] | None:
    codes = extract_hms_codes(question)
    if len(codes) != 1:
        return None
    for source in sorted(sources, key=lambda item: "/zh/" not in item.hit.source_url):
        if extract_hms_codes(source.hit.title) != codes:
            continue
        parts = re.split(r"[:：]", source.hit.title, maxsplit=1)
        if len(parts) != 2:
            continue
        # Some official titles append "please check ..." after the fault
        # definition. Return only the definition, not that instruction.
        meaning = re.split(r"请|\bplease\b", parts[1], maxsplit=1, flags=re.I)[0]
        meaning = meaning.strip().rstrip("，,。.;； ")
        action = re.search(
            r"更换|安装|检查|操作|步骤|\b(?:check|install|reinstall|replace|remove|measure)\b",
            meaning,
            re.I,
        )
        if meaning and len(meaning) <= 200 and not action and not needs_guide_only(meaning):
            return source, meaning
    return None
