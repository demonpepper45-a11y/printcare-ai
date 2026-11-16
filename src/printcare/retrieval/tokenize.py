"""Tokenisation and model detection for Chinese and mixed-language questions.

Chinese text has no spaces, so it is indexed with character bigrams (plus the
single character for one-character runs). ASCII words and HMS error codes are
kept as separate tokens so exact model names and codes stay distinguishable.
"""

from __future__ import annotations

import re

CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
HMS_RE = re.compile(
    r"(?i)(?<![0-9a-f])([0-9a-f]{4})[-_ ]([0-9a-f]{4})[-_ ]([0-9a-f]{4})[-_ ]([0-9a-f]{4})"
    r"(?![0-9a-f])"
)
MACHINE_RE = re.compile(r"(?i)(?<![a-z0-9])(a1[\s_-]*mini|a1(?![a-z0-9]))")
UNSUPPORTED_MODEL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(x1c|x1e|x1|p1p|p1s|a2l|h2d|h2s|p2s)(?![a-z0-9])"
)


def normalize_hms(code: str) -> str:
    """``HMS_0300-1800-0001-0001`` → ``0300_1800_0001_0001``."""
    groups = re.findall(r"[0-9a-fA-F]{4}", code)
    return "_".join(group.upper() for group in groups)


def extract_hms_codes(text: str) -> tuple[str, ...]:
    codes: list[str] = []
    for match in HMS_RE.finditer(text):
        code = normalize_hms(match.group(0))
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def detect_machines(text: str) -> tuple[str, ...]:
    """Return machine codes mentioned in the text, in order of appearance."""
    detected: list[str] = []
    for match in MACHINE_RE.finditer(text):
        token = match.group(1).lower()
        machine = "a1_mini" if "mini" in token else "a1"
        if machine not in detected:
            detected.append(machine)
    return tuple(detected)


def detect_unsupported_models(text: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(match.group(1).lower() for match in UNSUPPORTED_MODEL_RE.finditer(text))
    )


def tokenize(text: str) -> tuple[str, ...]:
    # Normalise a small, explicit domain vocabulary on both sides of retrieval.
    # This does not infer a fault or change model/HMS detection.
    text = re.sub(r"第一层|初始层", "首层", text)
    text = re.sub(r"(?<!同步)皮带", "同步带", text)
    tokens: list[str] = []
    for run in CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    tokens.extend(ASCII_TOKEN_RE.findall(text.lower()))
    tokens.extend(f"hms:{code}" for code in extract_hms_codes(text))
    return tuple(tokens)
