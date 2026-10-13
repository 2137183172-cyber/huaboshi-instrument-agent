"""Conversation continuity and user-facing guidance helpers."""

from __future__ import annotations

from typing import Any

from backend.session_memory import (
    ACTIVE_OBJECT_LABELS,
    SLOT_LABELS,
    get_session_context,
    next_topic_stage,
)


def _text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip() if text else ""


def _answer_text(value: Any, limit: int = 1400) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit].rstrip() if text else ""


def _unique(values: list[Any], limit: int = 4) -> list[str]:
    result = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _action(
    label: str,
    message: str,
    action: str | None = None,
    action_value: str | None = None,
) -> dict[str, str]:
    item = {"label": label, "message": message}
    if action:
        item["action"] = action
    if action_value:
        item["action_value"] = action_value
    return item


TOPIC_ACTIONS = {
    "spatial_omics": {
        "default": [
            ("确认样本与前处理", "我想先看空间组学的样本准备与质控"),
            ("查看空间蛋白检测", "我想先看空间蛋白检测环节"),
            ("查看完整研究方案", "这个方向的完整方案怎么配置"),
        ],
        "sample": [
            ("比较 FFPE 与新鲜组织", "FFPE 和新鲜组织做空间组学有什么区别"),
            ("查看核心检测设备", "我想看空间组学的核心检测设备"),
            ("查看完整研究方案", "这个方向的完整方案怎么配置"),
        ],
        "analysis": [
            ("查看图像分析环节", "我想先看空间组学的图像与数据分析"),
            ("查看正交验证", "我想了解空间组学的正交验证环节"),
            ("查看完整研究方案", "这个方向的完整方案怎么配置"),
        ],
    },
    "organoid": {
        "default": [
            ("查看培养与维护", "我想先看类器官的培养与维护环节"),
            ("查看动态成像", "我想先看类器官的动态成像与分析"),
            ("查看药敏方案", "我想先看类器官药敏与终点验证"),
        ],
        "culture": [
            ("比较培养设备", "类器官培养维护有哪些设备可以选"),
            ("查看动态成像", "我想继续看类器官的动态成像与分析"),
            ("查看完整研究方案", "类器官研究的完整方案怎么配置"),
        ],
        "imaging": [
            ("查看成像分析设备", "类器官成像分析有哪些设备可以选"),
            ("查看药敏环节", "我想继续看类器官药敏与终点验证"),
            ("查看完整研究方案", "类器官研究的完整方案怎么配置"),
        ],
        "drug": [
            ("查看培养维护设备", "类器官药敏前的培养维护有哪些设备"),
            ("查看成像分析设备", "类器官药敏需要哪些成像分析设备"),
            ("查看完整研究方案", "类器官研究的完整方案怎么配置"),
        ],
    },
    "flow_cytometry": {
        "default": [
            ("确认样本制备", "我想先看流式检测的样本制备与组织解离"),
            ("比较激光配置", "单激光和多激光光谱流式怎么选"),
            ("查看免疫分型应用", "我想看流式细胞分析的免疫分型应用"),
        ],
        "prep": [
            ("查看组织解离设备", "流式检测前的组织解离有哪些设备"),
            ("查看上机检测配置", "我想继续看流式上机检测配置"),
            ("查看完整流程", "流式细胞分析的完整流程怎么配置"),
        ],
        "analysis": [
            ("比较激光配置", "单激光和多激光光谱流式怎么选"),
            ("查看免疫分型应用", "我想看流式细胞分析的免疫分型应用"),
            ("查看完整流程", "流式细胞分析的完整流程怎么配置"),
        ],
    },
}


def _topic_action_key(context: dict[str, Any]) -> str:
    stage = _text(context.get("current_stage"), 80)
    topic_id = _text(context.get("topic_id"), 80)
    if topic_id == "spatial_omics":
        if "原位" in stage or "检测" in stage:
            return "sample"
        if "图像" in stage or "空间数据" in stage:
            return "analysis"
        if "验证" in stage:
            return "analysis"
        return "default"
    if topic_id == "flow_cytometry" and "门控" in stage:
        return "analysis"
    if any(term in stage for term in ("培养", "维护", "接种")):
        return "culture"
    if any(term in stage for term in ("成像", "图像", "分析")):
        return "analysis" if context.get("topic_id") == "flow_cytometry" else "imaging"
    if any(term in stage for term in ("药敏", "终点", "验证")):
        return "drug"
    if any(term in stage for term in ("样本", "解离", "染色", "上机")):
        return "prep"
    if any(term in stage for term in ("原位", "检测")):
        return "sample"
    return "default"


def _topic_actions(context: dict[str, Any]) -> list[dict[str, str]]:
    topic_id = _text(context.get("topic_id"), 80)
    groups = TOPIC_ACTIONS.get(topic_id)
    if not groups:
        return []
    choices = list(groups.get(_topic_action_key(context), groups["default"]))
    active_object = str(context.get("active_object") or "")
    topic_title = _text(context.get("topic_title"), 100)
    if active_object == "stage" and topic_title:
        following_stage = next_topic_stage(context)
        if following_stage:
            choices[0] = (
                f"继续看{following_stage}",
                f"{topic_title}：我想继续看{following_stage}",
            )
        else:
            choices[0] = (
                "查看完整实施方案",
                f"{topic_title}完整方案",
            )
    actions = []
    for label, message in choices:
        if "查看" in label and any(term in label for term in ("环节", "培养", "成像", "验证", "检测")):
            stage = label.replace("查看", "", 1).replace("环节", "").strip()
            actions.append(_action(label, message, "select_stage", stage))
        elif "完整" in label or "方案" in label:
            actions.append(_action(label, message, "open_scenario"))
        else:
            actions.append(_action(label, message))
    return actions


def _recommendation_actions(result: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    devices = result.get("recommended_devices")
    names = [
        item.get("name")
        for item in devices
        if isinstance(item, dict) and item.get("name")
    ] if isinstance(devices, list) else []
    names = _unique(names, 3)
    if not names:
        return []

    actions = []
    primary = names[0]
    actions.append(_action("查看主推荐适用样本", f"{primary}适合哪些样本？", "select_product", primary))
    if len(names) >= 2:
        actions.append(_action("比较前两款设备", "这几个设备有什么区别？", "compare_candidates", "、".join(names[:2])))
    if context.get("known_slots", {}).get("throughput"):
        actions.append(_action("查看实验流程衔接", f"{primary}在实验流程中的上游和下游是什么？", "select_product", primary))
    else:
        actions.append(_action("再推荐其他产品", "再推荐几个不同的替代产品", "more_candidates"))
    return actions[:3]


def _detail_actions(result: dict[str, Any]) -> list[dict[str, str]]:
    device = _text(result.get("subject_device"), 160)
    if not device:
        return []
    return [
        _action("查看适用样本", f"{device}适合哪些样本？", "select_product", device),
        _action("查看应用场景", f"{device}适合哪些应用场景？", "select_product", device),
        _action("查看实验流程", f"{device}的操作流程和上下游是什么？", "select_product", device),
    ]


def _scenario_actions(result: dict[str, Any]) -> list[dict[str, str]]:
    plan = result.get("scenario_plan")
    context = result.get("scenario_context")
    if not isinstance(plan, dict) and not isinstance(context, dict):
        return []
    title = _text(
        (plan or {}).get("title") if isinstance(plan, dict) else (context or {}).get("title"),
        140,
    ) or "这个方案"
    if _text(result.get("intent"), 50) == "scenario_equipment":
        return [
            _action("按样本和通量调整", "按我的样本类型和通量调整这个方案", "adjust_scenario"),
            _action("查看完整实施路径", f"{title}的完整实施路径", "open_scenario"),
            _action("继续看下一环节", "继续了解", "continue"),
        ]
    return [
        _action("按我的样本调整方案", "按我的样本类型和通量调整这个方案", "adjust_scenario"),
        _action("查看方案设备选型", f"{title}中各步骤的核心设备如何选型？", "compare_candidates"),
        _action("查看下一步实施路径", f"{title}的实施路径和上下游如何衔接？", "open_scenario"),
    ]


def _guide_actions() -> list[dict[str, str]]:
    return [
        _action("浏览场景方案", "有哪些场景方案可以参考？"),
        _action("浏览产品目录", "查看产品目录"),
    ]


def _catalog_actions() -> list[dict[str, str]]:
    from backend.scenario_selection import choices
    return [_action(c['title'],c['title'],'scenario_choice',c['key']) for c in choices()[:6]]


def _acknowledgement_actions(context: dict[str, Any]) -> list[dict[str, str]]:
    active = str(context.get("active_object") or "")
    if active == "product" and context.get("current_product"):
        product = _text(context.get("current_product"), 160)
        return [
            _action("继续看适用样本", f"{product}适合哪些样本？", "select_product", product),
            _action("继续看应用场景", f"{product}适合哪些应用场景？", "select_product", product),
        ]
    if active in {"topic", "stage"}:
        return _topic_actions(context)[:2]
    if active in {"recommendation", "comparison"}:
        return [_action("继续比较候选", "这几个设备有什么区别？", "compare_candidates")]
    if active.startswith("scenario"):
        return [_action("继续查看方案设备", "继续了解", "continue")]
    return []


def build_acknowledgement_result(context: dict[str, Any]) -> dict[str, Any]:
    """A lightweight hand-off for “好的/谢谢”, without restarting retrieval."""
    active = str(context.get("active_object") or "")
    name = _text(context.get("active_object_name"), 160)
    if active == "product" and name:
        answer = f"好的，后面继续围绕“{name}”展开。你可以直接查看它的适用样本、应用场景或实验流程。"
    elif active in {"topic", "stage"} and name:
        answer = f"好的，继续沿着“{name}”这个方向看，不重新开始筛选。"
    elif active and name:
        answer = f"好的，继续围绕“{name}”推进。"
    else:
        answer = "好的，你可以继续补充实验任务、样本或希望查看的实验环节。"
    return {
        "intent": "acknowledgement",
        "answer": answer,
        "recommended_devices": [],
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [],
        "disclaimer": "",
        "generation_source": "conversation_context",
        "model_error": "",
    }


def build_next_actions(result: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    intent = _text(result.get("intent"), 50)
    if intent == "guide":
        return _guide_actions()
    if intent == "catalog":
        return _catalog_actions()
    if intent in {"weather", "human_support", "model_identity", "general", "error"}:
        return []
    if intent == "acknowledgement":
        return _acknowledgement_actions(context)
    if intent == "scenario_plan":
        return []
    if intent in {"scenario_scope", "scenario_equipment"}:
        return _scenario_actions(result)
    if intent == "detail":
        return _detail_actions(result)
    if intent in {"topic_overview", "topic_stage"} or (
        context.get("active_object") in {"topic", "stage"}
        and intent not in {"weather", "human_support", "model_identity", "general"}
    ):
        actions = _topic_actions(context)
        if actions:
            return actions
    return _recommendation_actions(result, context)


def _confirmed_items(context: dict[str, Any]) -> list[dict[str, str]]:
    known = context.get("known_slots") or {}
    items = []
    for key in ("task", "sample_type", "workflow_stage", "throughput", "automation", "resolution", "budget"):
        value = _text(known.get(key), 120)
        if value:
            items.append({"label": SLOT_LABELS.get(key, key), "value": value})
    return items[:5]


def public_conversation_context(context: dict[str, Any]) -> dict[str, Any]:
    active_object = _text(context.get("active_object"), 40)
    active = bool(active_object and active_object in ACTIVE_OBJECT_LABELS)
    return {
        "active": active,
        "object_type": active_object if active else "",
        "object_label": ACTIVE_OBJECT_LABELS.get(active_object, "") if active else "",
        "object_name": _text(context.get("active_object_name"), 180) if active else "",
        "topic": _text(context.get("topic_title"), 100) if active else "",
        "scenario": _text(context.get("scenario_title"), 140) if active else "",
        "stage": _text(context.get("current_stage"), 100) if active else "",
        "confirmed": _confirmed_items(context) if active else [],
        "turn_count": int(context.get("turn_count") or 0),
    }


def _slot_acknowledgement(context: dict[str, Any]) -> str:
    values = context.get("last_slot_values") or {}
    keys = context.get("last_slot_keys") or list(values)
    latest = []
    for key in keys:
        value = _text(values.get(key), 120)
        if value:
            latest.append(f"{SLOT_LABELS.get(key, key)}为{value}")
    if not latest:
        return "已记下这项条件。"
    return "已记下：" + "；".join(latest[:3]) + "。"


def apply_conversation_guidance(
    result: dict[str, Any],
    session_id: str,
    raw_query: str,
) -> dict[str, Any]:
    """Attach only user-facing continuity data after the grounded answer is built."""
    context = get_session_context(session_id)
    result["conversation_context"] = public_conversation_context(context)
    result["next_actions"] = build_next_actions(result, context)
    if _text(result.get("intent"), 50) == "scenario_plan":
        result["need_more_info"] = []
        result["clarifying_questions"] = []
        result["related_questions"] = []

    if context.get("last_input_was_slot_reply") and str(raw_query or "").strip():
        answer = _answer_text(result.get("answer"), 1400)
        acknowledgement = _slot_acknowledgement(context)
        latest_values = [
            _text(value, 80)
            for value in (context.get("last_slot_values") or {}).values()
            if _text(value, 80)
        ]
        already_acknowledged = "已记下" in answer or "结合你补充" in answer or any(
            value in answer for value in latest_values
        )
        if answer and acknowledgement not in answer and not already_acknowledged:
            result["answer"] = f"{acknowledgement}\n{answer}"
    return result
