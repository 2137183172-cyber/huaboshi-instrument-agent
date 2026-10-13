from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.agent import normalize_result
from backend.local_catalog import get_local_device_detail
from backend.text_cleanup import clean_source_text


TOPIC_PROFILES_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "knowledge"
    / "topic_profiles_v1.json"
)

CUSTOMER_FOLLOWUP_BLOCKLIST = (
    "请您",
    "请告诉我",
    "请提供",
    "请补充",
    "能否请您",
    "方便说明",
    "您希望",
    "您更关注",
    "您计划",
    "您准备",
    "您是否",
    "您的样本",
    "您的预算",
    "您需要",
)

SAMPLE_MARKERS = ("哪些样本", "什么样本", "适合样本", "样本类型", "样本要求")
APPLICATION_MARKERS = ("应用场景", "有哪些应用", "有什么应用", "能做什么", "用于什么")

# Stage terms are deliberately narrower than topic aliases. A topic-only
# question should show the overview; a stage term should open the matching
# branch of the research workflow.
TOPIC_STAGE_HINTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "spatial_omics": (
        ("样本准备", "样本制备", "组织质控", "切片", "染色"),
        ("原位检测", "多重检测", "空间蛋白检测", "空间转录检测"),
        ("图像分析", "空间数据分析", "空间分析", "成像定量"),
        ("正交验证", "验证环节"),
    ),
    "organoid": (
        ("样本准备", "样本制备", "组织解离", "接种"),
        ("培养", "维护", "换液", "传代", "灌流", "长期培养"),
        ("动态成像", "成像分析", "形态分析", "生长观察"),
        ("药敏", "药物筛选", "终点验证", "功能评价"),
    ),
    "flow_cytometry": (
        ("样本制备", "组织解离", "单细胞悬液"),
        ("抗体面板", "面板设计", "染色"),
        ("上机采集", "上机检测", "光谱解析"),
        ("门控", "结果解释", "数据解读"),
    ),
}


def _compact(value: Any, limit: int = 180) -> str:
    text = " ".join(clean_source_text(value).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，。；;：: ") + "…"


def _fold(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _sentence(value: Any, limit: int) -> str:
    text = _compact(value, limit)
    if text and text[-1] not in "。！？?!":
        text += "。"
    return text


@lru_cache(maxsize=1)
def load_topic_profiles() -> list[dict[str, Any]]:
    try:
        payload = json.loads(TOPIC_PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("topics", []) if isinstance(item, dict)]


def detect_research_topic(query: str) -> dict[str, Any] | None:
    text = _fold(query)
    if not text:
        return None

    matches = []
    for profile in load_topic_profiles():
        aliases = [alias for alias in profile.get("aliases", []) if _fold(alias) in text]
        if aliases:
            matches.append((max(len(_fold(alias)) for alias in aliases), profile))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def is_broad_topic_query(query: str, profile: dict[str, Any] | None = None) -> bool:
    profile = profile or detect_research_topic(query)
    if not profile:
        return False

    text = _fold(query)
    for term in profile.get("specific_product_terms", []):
        if _fold(term) and _fold(term) in text:
            return False
    return True


def normalize_customer_followups(values: Any, limit: int = 4) -> list[str]:
    if not isinstance(values, list):
        return []

    result = []
    for value in values:
        text = " ".join(str(value or "").replace("*", "").split()).strip()
        if not text or text.startswith(CUSTOMER_FOLLOWUP_BLOCKLIST):
            continue
        if any(marker in text for marker in ("检索结果", "召回结果", "知识库片段", "模型提示词")):
            continue
        if text[-1] not in "？?!！。":
            text += "？"
        if text not in result:
            result.append(text)
        if len(result) >= max(0, limit):
            break
    return result


def _conditional_products(query: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    text = _fold(query)
    selected = list(profile.get("products", []))
    for rule in profile.get("conditional_products", []):
        if not any(_fold(term) in text for term in rule.get("when_terms", [])):
            continue
        product = rule.get("product")
        if not isinstance(product, dict):
            continue
        if rule.get("replace_last") and selected:
            selected[-1] = product
        else:
            selected.append(product)
    return selected[:4]


def _device_card(item: dict[str, Any]) -> dict[str, Any]:
    detail = get_local_device_detail(str(item.get("name") or "")) or {}
    role = _compact(item.get("role"), 60)
    reason = _compact(item.get("reason"), 120)
    reasons = []
    if role:
        reasons.append(f"对应环节：{role}")
    if reason:
        reasons.append(reason)

    return {
        "name": detail.get("name") or item.get("name"),
        "product_code": detail.get("product_code"),
        "reasons": reasons,
        "capabilities": [],
        "tasks": [],
        "overview": _compact(item.get("summary") or detail.get("overview"), 150),
        "advantages": "",
        "applications": "",
        "description": "",
        "matched_reason": reason,
        "fit_tags": [],
        "selection_notes": [],
        "source_pages": [],
        "evidence": [],
    }


def _supplement_hints(query: str) -> list[tuple[str, str]]:
    """Extract explicit conditions supplied in a follow-up message."""
    text = re.sub(r"\s+", "", str(query or ""))
    if "补充信息" not in text:
        return []
    hints: list[tuple[str, str]] = []
    for label, markers in (
        ("样本", ("FFPE", "肿瘤组织", "新鲜组织", "冰冻组织", "血浆", "血清", "培养细胞", "贴壁细胞", "悬浮细胞")),
        ("通量", ("高通量", "大批量", "批量", "低通量", "中通量")),
        ("自动化要求", ("全自动", "半自动", "自动化", "无人值守")),
    ):
        marker = next((item for item in markers if item.casefold() in text.casefold()), None)
        if marker:
            hints.append((label, marker))
    return hints


def _supplement_hint(query: str) -> tuple[str, str] | None:
    """Backward-compatible accessor for callers needing the first condition."""
    hints = _supplement_hints(query)
    return hints[0] if hints else None


def _topic_answer(query: str, profile: dict[str, Any]) -> str:
    text = str(query or "")
    definition = _sentence(profile.get("definition"), 220)
    supplements = _supplement_hints(text)
    if supplements:
        condition_text = "、".join(
            f"{value}{'样本' if label == '样本' else label}"
            for label, value in supplements
        )
        if any(label == "样本" for label, _ in supplements):
            return (
                f"已记下你的条件：{condition_text}。下一步应优先确认样本准备、接种方式和后续培养配置。"
                "你可以先选择具体实验环节，我会据此缩小设备范围。"
            )
        if any(label == "通量" for label, _ in supplements):
            return f"已记下你的条件：{condition_text}。设备筛选会优先考虑批量处理能力，再确认实验环节和样本状态。"
        return f"已记下你的条件：{condition_text}。后续会优先比较能够覆盖目标环节的自动化方案。"
    if any(marker in text for marker in SAMPLE_MARKERS):
        return f"{_sentence(profile.get('sample_scope'), 220)}选型前还需确认样本保存方式、实验目标和预计通量。"
    if any(marker in text for marker in APPLICATION_MARKERS):
        return f"{_sentence(profile.get('applications'), 220)}具体配置应从样本制备、核心检测和数据分析三个层面确定。"

    stage_names = [
        _compact(stage.get("name"), 30)
        for stage in profile.get("stages", [])
        if isinstance(stage, dict) and stage.get("name")
    ]
    path = " → ".join(stage_names)
    return f"{definition}建议按“{path}”梳理需求，再选择各环节设备。"


def detect_topic_stage(query: str, profile: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
    profile = profile or detect_research_topic(query)
    if not profile:
        return None
    # A named product can contain stage words such as "培养" or "成像".
    # Once a specific product term is present, keep the request on the product
    # detail path instead of reopening a topic branch.
    if not is_broad_topic_query(query, profile):
        return None
    hints = TOPIC_STAGE_HINTS.get(str(profile.get("id") or ""), ())
    text = _fold(query)
    if not text or not hints:
        return None

    # Questions about the supported scope should be answered by the topic
    # overview, even when the wording also mentions a workflow stage.
    if any(marker in text for marker in SAMPLE_MARKERS + APPLICATION_MARKERS):
        return None

    # Do not turn a request for a complete plan into a single-stage answer.
    if any(marker in text for marker in ("完整方案", "场景方案", "实施方案", "研究路线", "全流程")):
        return None

    matches = []
    for index, terms in enumerate(hints):
        hit_terms = [term for term in terms if _fold(term) in text]
        if hit_terms:
            matches.append((max(len(_fold(term)) for term in hit_terms), index))
    if not matches:
        return None
    _, index = max(matches, key=lambda item: (item[0], -item[1]))
    stages = profile.get("stages", [])
    if index >= len(stages) or not isinstance(stages[index], dict):
        return None
    return index, stages[index]


def _stage_products(query: str, profile: dict[str, Any], stage_index: int) -> list[dict[str, Any]]:
    hints = TOPIC_STAGE_HINTS.get(str(profile.get("id") or ""), ())
    stage = (profile.get("stages") or [])[stage_index]
    stage_text = " ".join(
        str(stage.get(field) or "") for field in ("name", "goal")
    ).casefold()
    terms = list(hints[stage_index]) if stage_index < len(hints) else []
    ranked = []
    for item in _conditional_products(query, profile):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        product_text = " ".join(
            str(item.get(field) or "")
            for field in ("name", "role", "reason", "summary")
        ).casefold()
        score = sum(3 for term in terms if _fold(term) in product_text)
        score += sum(1 for word in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", stage_text) if word and word in product_text)
        if score:
            ranked.append((score, item))

    if not ranked:
        ranked = [(0, item) for item in _conditional_products(query, profile)]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked[:3]]


def build_topic_stage_result(query: str) -> dict[str, Any] | None:
    profile = detect_research_topic(query)
    match = detect_topic_stage(query, profile)
    if not profile or match is None:
        return None
    stage_index, stage = match
    stage_name = _compact(stage.get("name"), 80)
    goal = _sentence(stage.get("goal"), 220)
    products = [
        _device_card(item)
        for item in _stage_products(query, profile, stage_index)
        if isinstance(item, dict) and item.get("name")
    ]
    product_names = [item.get("name") for item in products if item.get("name")]
    supplements = _supplement_hints(query)
    if supplements:
        conditions = "、".join(
            f"{value}{'样本' if label == '样本' else label}"
            for label, value in supplements
        )
        answer = f"结合你补充的{conditions}，先看“{stage_name}”：{goal}"
    else:
        answer = f"先看“{stage_name}”：{goal}"
    if product_names:
        answer += f"这一环节可优先比较{('、'.join(product_names))}。"
    else:
        answer += "具体设备需要结合样本状态和处理规模进一步确定。"

    stages = []
    for index, raw_stage in enumerate(profile.get("stages", []), start=1):
        if not isinstance(raw_stage, dict):
            continue
        stages.append({
            "step_no": index,
            "name": _compact(raw_stage.get("name"), 60),
            "goal": _compact(raw_stage.get("goal"), 160),
            "active": index - 1 == stage_index,
        })

    return normalize_result({
        "intent": "topic_stage",
        "answer": answer,
        "answer_focus": "stage",
        "active_stage": stage_name,
        "research_path": {
            "topic_id": profile.get("id"),
            "title": profile.get("title"),
            "scenario_id": profile.get("scenario_id"),
            "scenario_title": profile.get("scenario_title"),
            "sample_scope": _compact(profile.get("sample_scope"), 220),
            "active_step": stage_index + 1,
            "next_stage": (
                _compact(profile.get("stages", [])[stage_index + 1].get("name"), 60)
                if stage_index + 1 < len(profile.get("stages", []))
                and isinstance(profile.get("stages", [])[stage_index + 1], dict)
                else ""
            ),
            "stages": stages,
        },
        "recommended_devices": products,
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [
            f"{profile.get('title')}的完整方案怎么配置？",
            f"{stage_name}还需要确认哪些条件？",
        ],
        "disclaimer": "回答基于当前已收录的研究主题和产品资料。",
        "generation_source": "topic_catalog",
        "model_error": "",
    })


def build_topic_overview_result(query: str) -> dict[str, Any] | None:
    profile = detect_research_topic(query)
    if not profile or not is_broad_topic_query(query, profile):
        return None

    stages = []
    for index, stage in enumerate(profile.get("stages", []), start=1):
        if not isinstance(stage, dict):
            continue
        stages.append({
            "step_no": index,
            "name": _compact(stage.get("name"), 60),
            "goal": _compact(stage.get("goal"), 160),
        })

    products = [
        _device_card(item)
        for item in _conditional_products(query, profile)
        if isinstance(item, dict) and item.get("name")
    ]
    result = normalize_result({
        "intent": "topic_overview",
        "answer": _topic_answer(query, profile),
        "research_path": {
            "topic_id": profile.get("id"),
            "title": profile.get("title"),
            "scenario_id": profile.get("scenario_id"),
            "scenario_title": profile.get("scenario_title"),
            "sample_scope": _compact(profile.get("sample_scope"), 220),
            "stages": stages,
        },
        "recommended_devices": products,
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": normalize_customer_followups(profile.get("followups", [])),
        "disclaimer": "",
        "generation_source": "topic_catalog",
        "model_error": "",
    })
    return result
