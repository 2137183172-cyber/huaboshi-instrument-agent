from __future__ import annotations

import re
from typing import Any


SOURCE_NOISE_PATTERNS = (
    re.compile(r"\s*SynergiTech\s*智荟华科", re.IGNORECASE),
    re.compile(r"\s*更多(?:细胞|代谢|分子|蛋白|成像|动物|植物|生命科学|服务|其他)?类产品"),
    re.compile(r"\s*扫一扫[，,]?\s*关注公众号"),
    re.compile(r"\s*扫码添加微信"),
)

UNVERIFIED_FACT_MARKERS = (
    "从产品特性及同系列产品",
    "基于同系列产品定位推测",
    "推测，其用途",
    "推测，其应用",
    "可能适用于",
)


def clean_display_text(value: Any) -> str:
    """Normalize model text for plain-text chat rendering without losing paragraphs."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    text = re.sub(r"^```(?:json|markdown|text)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s*[*+]\s+", "- ", text)

    lines = []
    previous_blank = False
    for raw_line in text.split("\n"):
        line = " ".join(raw_line.split())
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False
    return "\n".join(lines).strip()


def clean_source_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    cut_positions = []
    for pattern in SOURCE_NOISE_PATTERNS:
        match = pattern.search(text)
        if match and match.start() > 0:
            cut_positions.append(match.start())

    if cut_positions:
        text = text[:min(cut_positions)]
    return text.rstrip("，,；;。 |")


def clean_verified_source_text(value: Any) -> str:
    text = clean_source_text(value)
    if any(marker in text for marker in UNVERIFIED_FACT_MARKERS):
        return ""
    return text
