import re
from typing import Any

from backend.agent import normalize_evidence_items, normalize_result
from backend.llm_service import model_config


SAMPLE_QUERY_PATTERNS = [
    "适合哪些样本",
    "适合什么样本",
    "适用哪些样本",
    "适用什么样本",
    "支持哪些样本",
    "支持什么样本",
    "处理哪些样本",
    "能处理什么样本",
    "能处理哪些样本",
    "可处理什么样本",
    "可处理哪些样本",
    "什么类型的样本",
    "哪些类型的样本",
    "样本类型是什么",
    "样本类型有哪些",
    "适用样本",
    "样本范围",
]


def detect_detail_focus(user_query: str) -> str | None:
    text = re.sub(r"\s+", "", str(user_query or ""))
    if any(pattern in text for pattern in SAMPLE_QUERY_PATTERNS):
        return "samples"
    return None


def _unique_strings(values: list[Any]) -> list[str]:
    result = []
    for value in values:
        text = " ".join(str(value or "").split()).strip("；;，,、。 ")
        if text and text not in result:
            result.append(text)
    return result


def _sample_items(result: dict) -> list[str]:
    samples = _unique_strings(result.get("sample_types", []))
    source_text = " ".join(
        str(result.get(field) or "")
        for field in ["overview", "applications", "summary"]
    )

    # Some product records describe microbiology samples in the approved source
    # text even when the structured sample_types field is incomplete.
    if "微生物" in source_text and not any("微生物" in item for item in samples):
        samples.append("微生物检测样本")
    return samples


def _format_sample_label(sample: str) -> str:
    replacements = {
        "DNA/RNA/核酸建库样本": "核酸类样本（DNA、RNA 或核酸反应产物）",
        "血浆/血清/蛋白样本": "蛋白质类样本（包括血浆、血清等蛋白样本）",
    }
    return replacements.get(sample, sample)


def build_sample_scope_result(user_query: str, workflow_result: dict) -> dict:
    result = workflow_result.get("result", {})
    device_name = str(result.get("name") or "该设备")
    samples = [_format_sample_label(item) for item in _sample_items(result)]

    if samples:
        lines = [f"根据产品资料，{device_name}适用于以下样本："]
        lines.extend(f"{index}. {sample}" for index, sample in enumerate(samples, 1))

        overview = str(result.get("overview") or "")
        applications = str(result.get("applications") or "")
        if "MALDI-TOF" in overview and "点样" in (overview + applications):
            lines.append(
                "该设备主要完成 MALDI-TOF 靶标板点样。具体样本浓度、基质配方和前处理要求，"
                "当前资料未明确，需按检测方法进一步确认。"
            )
        else:
            lines.append("具体样本状态、体积及前处理要求，仍需结合实验方法和实际配置确认。")
        answer = "\n".join(lines)
        need_more_info = []
    else:
        answer = (
            f"当前产品资料未明确列出{device_name}支持的具体样本类型。"
            "为避免误导，需要结合产品说明书或由应用工程师进一步确认。"
        )
        need_more_info = ["请补充计划处理的样本名称和检测方法，以便核对适配性。"]

    evidence = normalize_evidence_items(result.get("evidence_chunks", []))
    return normalize_result({
        "intent": "detail",
        "answer_focus": "samples",
        "subject_device": device_name,
        "answer": answer,
        "recommended_devices": [],
        "need_more_info": need_more_info,
        "clarifying_questions": [],
        "related_questions": [
            f"{device_name}的点样通量是多少？",
            f"{device_name}有哪些自动化功能？",
        ],
        "disclaimer": "回答仅基于当前产品资料，未公开的样本条件需进一步确认。",
        "evidence": evidence[:2],
        "generation_source": "local_catalog",
        "model_name": model_config()["name"],
        "query": user_query,
    })


def build_focused_detail_result(user_query: str, workflow_result: dict) -> dict | None:
    focus = detect_detail_focus(user_query)
    if focus == "samples":
        return build_sample_scope_result(user_query, workflow_result)
    return None
