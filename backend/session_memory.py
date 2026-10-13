import re
from typing import Dict, Any

from backend.device_name_extractor import extract_device_name
from backend.demand_profile import parse_demand
from backend.slot_extractor import extract_slots
from backend.similar_products import build_contextual_similar_query, is_similar_followup_text

SESSION_STORE: Dict[str, Dict[str, Any]] = {}
MAX_RECENT_TURNS = 4

SLOT_LABELS = {
    "task": "实验任务",
    "sample_type": "样本",
    "workflow_stage": "实验环节",
    "throughput": "通量",
    "automation": "自动化要求",
    "resolution": "分辨率",
    "budget": "预算",
}

SLOT_REPLY_PREFIXES = (
    "样本是",
    "样本为",
    "样本：",
    "样本:",
    "通量是",
    "通量为",
    "通量：",
    "通量:",
    "预算是",
    "预算为",
    "预算：",
    "预算:",
    "我有",
    "我们有",
    "主要是",
    "重点是",
    "想先看",
)

STAGE_REPLY_TERMS = (
    "样本准备",
    "样本制备",
    "接种",
    "培养",
    "维护",
    "换液",
    "传代",
    "灌流",
    "成像",
    "图像分析",
    "数据分析",
    "检测",
    "染色",
    "上机",
    "门控",
    "药敏",
    "药物筛选",
    "终点验证",
    "正交验证",
)

TOPIC_REFERENCE_TERMS = (
    "这个方向",
    "该方向",
    "这个主题",
    "该主题",
    "这个研究",
    "该研究",
    "这个方案",
    "该方案",
)

CONTINUATION_TERMS = ("继续了解", "接着看", "下一步", "继续看看", "继续")

# Short utterances are common in a chat UI. They only become meaningful when
# there is an active conversation object, so they are kept out of the generic
# product router and resolved here with the current state.
ACKNOWLEDGEMENT_TERMS = (
    "好的", "好", "明白了", "了解了", "收到", "谢谢", "感谢", "行", "可以",
    "好的谢谢", "明白谢谢",
)
MORE_CANDIDATE_TERMS = (
    "再推荐几个", "再推荐几款", "再列几个", "再列几款", "还有别的吗",
    "还有其他产品", "还有其他设备", "换几个", "换几款", "更多产品",
    "更多设备", "多列几个", "再看看别的", "其他替代品",
)
PRODUCT_REFERENCE_TERMS = (
    "这个呢", "这个怎么样", "这个可以吗", "就这个", "选这个", "这款呢",
    "这款怎么样", "它呢", "它怎么样", "这个产品呢", "这台呢",
)
CONTEXT_SWITCH_TERMS = ("换个方向", "换一个方向", "不是这个", "都不对", "重新选择")

SCENARIO_EQUIPMENT_REFERENCE_TERMS = (
    "核心设备选型", "方案设备选型", "设备如何选型", "各步骤的设备",
    "各环节的设备", "方案设备", "设备配置", "实施路径", "上下游如何衔接",
    "上下游怎么衔接", "上下游衔接",
)

ACTIVE_OBJECT_LABELS = {
    "topic": "研究方向",
    "stage": "实验环节",
    "scenario": "场景方案",
    "scenario_equipment": "方案设备选型",
    "product": "具体产品",
    "recommendation": "候选产品",
    "comparison": "产品对比",
    "catalog": "产品目录",
}

TOPIC_STAGE_SEQUENCE = {
    "spatial_omics": ("样本准备与质控", "原位多重检测", "图像与空间数据分析", "正交验证"),
    "organoid": ("样本准备与接种", "培养与维护", "动态成像与分析", "药敏与终点验证"),
    "flow_cytometry": ("单细胞样本制备", "抗体面板与染色", "上机采集与光谱解析", "门控与结果解释"),
}

DEVICE_FOLLOWUP_KEYWORDS = [
    "价格",
    "多少钱",
    "报价",
    "费用",
    "参数",
    "配置",
    "规格",
    "尺寸",
    "通量",
    "分辨率",
    "耗材",
    "试剂",
    "售后",
    "维护",
    "保修",
    "交付",
    "应用",
    "优势",
    "缺点",
    "卖点",
    "客户介绍",
    "样本",
    "原理",
    "流程",
    "兼容",
    "配套",
    "软件",
    "输入",
    "输出",
]

DETAIL_FOLLOWUP_KEYWORDS = [
    "详细介绍",
    "详细说说",
    "展开说说",
    "展开讲讲",
    "多讲讲",
    "具体介绍",
    "具体说说",
    "介绍一下",
    "讲详细点",
    "说详细点",
    "再详细",
]

SUPPLEMENT_KEYWORDS = [
    "样本",
    "预算",
    "通量",
    "自动化",
    "半自动",
    "全自动",
    "组织切片",
    "培养细胞",
    "血浆",
    "血清",
    "类器官",
    "FFPE",
    "贴壁细胞",
    "悬浮细胞",
    "分辨率",
    "空间分辨率",
    "处理数量",
    "样本数量",
    "纳米",
    "nm",
    "um",
    "μm",
    "≤",
    ">",
    "以上",
    "以内",
]

RATIONALE_FOLLOWUP_KEYWORDS = ["为什么推荐", "为什么选", "推荐理由", "为什么适合"]
ORDINAL_DEVICE_MARKERS = {
    0: ("第一个", "第一款", "第一台", "第1个", "1号", "前者"),
    1: ("第二个", "第二款", "第二台", "第2个", "2号", "后者"),
    2: ("第三个", "第三款", "第三台", "第3个", "3号"),
}

BARE_DETAIL_FOLLOWUPS = {
    "样本呢",
    "通量呢",
    "参数呢",
    "规格呢",
    "预算呢",
    "自动化呢",
    "分辨率呢",
    "原理呢",
    "优势呢",
    "应用呢",
    "流程呢",
    "耗材呢",
    "兼容性呢",
}

# These phrases describe a scope question, not a new sample value. Keeping
# them separate prevents "它适合哪些样本" from being treated as a slot reply.
SCOPE_FOLLOWUP_TERMS = (
    "适合哪些样本",
    "适合什么样本",
    "适用哪些样本",
    "适用什么样本",
    "支持哪些样本",
    "支持什么样本",
    "处理哪些样本",
    "能处理哪些样本",
    "能处理什么样本",
    "样本类型有哪些",
    "哪些应用场景",
    "适合哪些应用",
    "适用哪些应用",
    "可以做什么实验",
    "能做什么实验",
)

CONCRETE_SAMPLE_TERMS = (
    "FFPE",
    "肿瘤组织",
    "新鲜组织",
    "冰冻组织",
    "组织切片",
    "外周血",
    "全血",
    "血浆",
    "血清",
    "骨髓",
    "贴壁细胞",
    "悬浮细胞",
    "培养细胞",
    "类器官样本",
    "3D细胞模型",
    "DNA",
    "RNA",
    "核酸样本",
    "蛋白样本",
    "组织芯片",
)

# Strong direction terms are used only to clear an old research topic when a
# user explicitly moves to a different domain. Generic words such as "设备"
# and "自动化" are intentionally excluded.
RESEARCH_DIRECTION_TERMS = {
    "ngs": ("NGS", "文库制备", "靶向测序", "测序建库"),
    "protein": ("蛋白组学", "蛋白质组学", "蛋白互作"),
    "maldi": ("MALDI", "靶标板点样"),
    "nucleic_acid": ("核酸提取", "核酸纯化"),
    "exosome": ("外泌体",),
    "animal_imaging": ("动物活体成像", "小动物活体", "活体成像"),
}


def _new_context() -> Dict[str, Any]:
    return {
        "last_device": None,
        "current_product": None,
        "last_devices": [],
        "candidate_devices": [],
        "last_query": None,
        "last_raw_query": None,
        "last_intent": None,
        "last_answer_focus": None,
        "last_action": None,
        "last_action_value": None,
        "topic_id": None,
        "topic_title": None,
        "scenario_id": None,
        "scenario_title": None,
        "scenario_sample_scope": None,
        "active_object": None,
        "active_object_name": None,
        "active_stage_index": None,
        "current_stage": None,
        "known_slots": {},
        "pending_slot": None,
        "last_input_was_slot_reply": False,
        "last_slot_key": None,
        "last_slot_keys": [],
        "last_slot_values": {},
        "scenario_devices": [],
        "turn_count": 0,
        "recent_turns": [],
    }


def _clean_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip() if text else ""


def _unique(values: list[Any], limit: int = 8) -> list[str]:
    result = []
    for value in values:
        text = _clean_text(value, 160)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _action_for_intent(intent: str) -> str:
    return {
        "topic_overview": "open_topic",
        "topic_stage": "select_stage",
        "scenario_plan": "open_scenario",
        "scenario_scope": "view_scope",
        "scenario_equipment": "compare_candidates",
        "recommend": "recommend",
        "recommendation": "recommend",
        "similar": "more_candidates",
        "detail": "select_product",
        "compare": "compare_candidates",
        "acknowledgement": "continue",
    }.get(intent, intent or "")


def _action_value_for_result(result: dict, intent: str) -> str:
    if intent == "detail":
        return _clean_text(result.get("subject_device"), 180)
    if intent == "topic_stage":
        return _clean_text(result.get("active_stage"), 120)
    if intent in {"scenario_plan", "scenario_scope", "scenario_equipment"}:
        for key in ("scenario_plan", "scenario_context"):
            value = result.get(key)
            if isinstance(value, dict) and value.get("title"):
                return _clean_text(value.get("title"), 180)
    devices = result.get("recommended_devices")
    if isinstance(devices, list):
        names = [item.get("name") for item in devices if isinstance(item, dict)]
        return "、".join(_unique(names, 3))
    return ""


def _topic_profile(text: str) -> dict[str, Any] | None:
    # Import lazily to keep the topic catalog independent from session memory.
    try:
        from backend.topic_service import detect_research_topic

        return detect_research_topic(text)
    except Exception:
        return None


def _research_context_key(text: str) -> str | None:
    """Return a conservative domain key for detecting an explicit topic switch."""
    profile = _topic_profile(text)
    if profile and profile.get("id"):
        return f"topic:{profile['id']}"

    compact = re.sub(r"\s+", "", str(text or "")).casefold()
    for key, terms in RESEARCH_DIRECTION_TERMS.items():
        if any(str(term).casefold() in compact for term in terms):
            return f"domain:{key}"
    if "流式细胞" in compact or "光谱流式" in compact:
        return "topic:flow_cytometry"
    return None


def _has_explicit_sample_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if any(term.casefold() in compact.casefold() for term in CONCRETE_SAMPLE_TERMS):
        return True
    if any(marker in compact for marker in ("样本是", "样本为", "我的样本", "我们样本", "样本：", "样本:")):
        return True
    # Short answers such as "用肿瘤组织" or "处理血浆" are common after a
    # clarification chip, even when the word "样本" is omitted.
    return any(compact.startswith(prefix) for prefix in ("用", "使用", "采用", "处理")) and any(
        term.casefold() in compact.casefold() for term in CONCRETE_SAMPLE_TERMS
    )


def _is_scope_question(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(term in compact for term in SCOPE_FOLLOWUP_TERMS)


def _reset_research_context(ctx: Dict[str, Any]) -> None:
    """Clear stale selection state while retaining the short transcript."""
    for key, value in {
        "last_device": None,
        "current_product": None,
        "last_devices": [],
        "candidate_devices": [],
        "last_query": None,
        "topic_id": None,
        "topic_title": None,
        "scenario_id": None,
        "scenario_title": None,
        "scenario_sample_scope": None,
        "active_object": None,
        "active_object_name": None,
        "active_stage_index": None,
        "current_stage": None,
        "known_slots": {},
        "pending_slot": None,
        "last_slot_key": None,
        "last_slot_keys": [],
        "last_slot_values": {},
        "scenario_devices": [],
    }.items():
        ctx[key] = value


def _clear_non_product_context(ctx: Dict[str, Any]) -> None:
    """Remove active research references while retaining the transcript."""
    for key, value in {
        "last_device": None,
        "current_product": None,
        "last_devices": [],
        "candidate_devices": [],
        "last_query": None,
        "topic_id": None,
        "topic_title": None,
        "scenario_id": None,
        "scenario_title": None,
        "scenario_sample_scope": None,
        "active_object": None,
        "active_object_name": None,
        "active_stage_index": None,
        "current_stage": None,
        "known_slots": {},
        "pending_slot": None,
        "last_slot_key": None,
        "last_slot_keys": [],
        "last_slot_values": {},
        "scenario_devices": [],
    }.items():
        ctx[key] = value


def _safe_device_name(text: str) -> str | None:
    try:
        return extract_device_name(text)
    except Exception:
        return None


def _extract_sample_value(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    patterns = (
        ("FFPE组织切片", ("FFPE",)),
        ("肿瘤组织", ("肿瘤组织", "肿瘤样本")),
        ("新鲜组织", ("新鲜组织",)),
        ("冰冻组织", ("冰冻组织",)),
        ("外周血", ("外周血",)),
        ("骨髓", ("骨髓",)),
        ("血浆/血清", ("血浆", "血清")),
        ("培养细胞", ("培养细胞", "贴壁细胞", "悬浮细胞")),
        ("类器官/3D细胞模型", ("类器官", "3D细胞", "三维细胞")),
        ("核酸样本", ("DNA", "RNA", "核酸")),
        ("蛋白样本", ("蛋白", "肽段")),
        ("组织切片", ("组织切片", "组织芯片")),
    )
    for value, markers in patterns:
        if any(marker.casefold() in compact.casefold() for marker in markers):
            return value
    return None


def _extract_stage_value(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    rules = (
        ("样本准备与接种", ("样本准备", "样本制备", "组织解离", "接种")),
        ("培养与维护", ("培养环节", "培养维护", "长期培养", "换液", "传代", "灌流")),
        ("动态成像与分析", ("动态成像", "成像分析", "图像分析", "形态分析")),
        ("原位多重检测", ("原位检测", "多重检测", "空间蛋白检测", "空间转录检测")),
        ("药敏与终点验证", ("药敏", "药物筛选", "终点验证", "功能评价")),
        ("抗体面板与染色", ("抗体面板", "面板设计", "染色")),
        ("上机采集与光谱解析", ("上机采集", "上机检测", "光谱解析")),
        ("门控与结果解释", ("门控", "结果解释", "数据解读")),
        ("图像与空间数据分析", ("空间数据分析", "空间分析", "图像与数据分析")),
        ("正交验证", ("正交验证", "验证环节")),
    )
    for value, markers in rules:
        if any(marker in compact for marker in markers):
            return value
    # A plain "培养" or "成像" is useful only when it is clearly an action.
    if "培养" in compact:
        return "培养与维护"
    if "成像" in compact:
        return "动态成像与分析"
    if "药敏" in compact or "药物筛选" in compact:
        return "药敏与终点验证"
    return None


def _extract_slot_values(text: str) -> dict[str, Any]:
    text = str(text or "")
    slots = extract_slots(text)
    demand = parse_demand(text)
    values: dict[str, Any] = {}

    task = slots.get("task") or (demand.get("tasks") or [None])[0]
    if task:
        values["task"] = _clean_text(task, 100)

    sample = _extract_sample_value(text)
    # A scope question contains words such as "类器官" and "样本", but it is
    # asking for the supported range rather than declaring the user's sample.
    if _is_scope_question(text) or not _has_explicit_sample_signal(text):
        sample = None
    if not sample and _has_explicit_sample_signal(text):
        sample = slots.get("sample_type") or (demand.get("sample_types") or [None])[0]
    if sample:
        values["sample_type"] = _clean_text(sample, 100)

    stage = _extract_stage_value(text)
    if stage:
        values["workflow_stage"] = stage

    if any(term in text for term in ("全自动", "无人值守", "减少人工")):
        values["automation"] = "优先全自动"
    elif "半自动" in text:
        values["automation"] = "可接受半自动"
    elif any(term in text for term in ("手动", "人工操作")):
        values["automation"] = "人工操作可接受"
    elif demand.get("automation"):
        values["automation"] = "有自动化要求"

    throughput = slots.get("throughput")
    if throughput:
        values["throughput"] = throughput
    elif any(term in text for term in ("高通量", "大批量", "批量", "样本量大", "384")):
        values["throughput"] = "高通量/批量处理"
    elif any(term in text for term in ("中通量", "24-96")):
        values["throughput"] = "常规批次"
    elif any(term in text for term in ("低通量", "少量", "1-12")):
        values["throughput"] = "低通量"

    resolution = slots.get("resolution") or demand.get("resolution")
    if resolution:
        values["resolution"] = _clean_text(resolution, 80)

    budget = slots.get("budget") or demand.get("budget")
    if budget:
        values["budget"] = _clean_text(budget, 80)
    else:
        budget_match = re.search(r"(?:预算|价格)?\s*(30万以内|30\s*[-至]\s*50万|50万以上|100万以上|预算不限)", text)
        if budget_match:
            values["budget"] = re.sub(r"\s+", "", budget_match.group(1))

    return {key: value for key, value in values.items() if value not in (None, "", False)}


def _merge_slots(ctx: Dict[str, Any], text: str) -> dict[str, Any]:
    known = dict(ctx.get("known_slots") or {})
    known.update(_extract_slot_values(text))
    ctx["known_slots"] = known
    return known


def get_session_context(session_id: str) -> Dict[str, Any]:
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = _new_context()
    return SESSION_STORE[session_id]


def clear_session_context(session_id: str) -> bool:
    if session_id in SESSION_STORE:
        del SESSION_STORE[session_id]
        return True
    return False


def reset_active_context(session_id: str) -> Dict[str, Any]:
    """Start a new research direction while keeping the short transcript."""
    ctx = get_session_context(session_id)
    _clear_non_product_context(ctx)
    ctx["last_action"] = "reset"
    ctx["last_action_value"] = ""
    return ctx


def update_session_context(
    session_id: str,
    result: dict,
    user_query: str | None = None,
    *,
    raw_query: str | None = None,
    resolved_query: str | None = None,
    action: str | None = None,
    action_value: str | None = None,
):
    """Update short-term conversation state without breaking the old call shape."""
    ctx = get_session_context(session_id)
    result = result if isinstance(result, dict) else {}
    raw = _clean_text(raw_query if raw_query is not None else user_query, 2000)
    resolved = _clean_text(
        resolved_query if resolved_query is not None else user_query or raw,
        2400,
    )
    had_prior_turn = int(ctx.get("turn_count") or 0) > 0
    previous_topic_id = ctx.get("topic_id")
    previous_scenario_id = ctx.get("scenario_id")
    profile = _topic_profile(raw or resolved)
    topic_id = str(profile.get("id") or "").strip() if profile else ""

    # An explicitly new research direction should not inherit products from the
    # previous direction. The recent transcript is retained for continuity.
    new_context_key = _research_context_key(raw)
    previous_context_key = (
        f"topic:{previous_topic_id}" if previous_topic_id
        else f"scenario:{previous_scenario_id}" if previous_scenario_id
        else None
    )
    if (
        had_prior_turn
        and new_context_key
        and previous_context_key
        and new_context_key not in {previous_context_key, f"scenario:{previous_scenario_id}"}
    ):
        _reset_research_context(ctx)

    intent = str(result.get("intent") or "")
    # Standalone questions outside the product domain must not keep displaying
    # or reusing the previous research direction. The short transcript is kept
    # so the user can still see what was discussed on the page.
    is_contextual_general = any(term in raw for term in TOPIC_REFERENCE_TERMS)
    if intent in {"weather", "human_support", "model_identity", "catalog", "scenario_navigation"}:
        _clear_non_product_context(ctx)
    elif intent == "general" and not is_contextual_general and not profile:
        _clear_non_product_context(ctx)

    ctx["last_intent"] = intent or result.get("intent")
    ctx["last_answer_focus"] = result.get("answer_focus")
    ctx["last_raw_query"] = raw or ctx.get("last_raw_query")
    ctx["last_action"] = _clean_text(action, 50) or _action_for_intent(intent)
    ctx["last_action_value"] = _clean_text(action_value, 180) or _action_value_for_result(result, intent)

    if profile:
        ctx["topic_id"] = profile.get("id") or ctx.get("topic_id")
        ctx["topic_title"] = profile.get("title") or ctx.get("topic_title")
        if profile.get("scenario_id"):
            ctx["scenario_id"] = profile.get("scenario_id")
        if profile.get("scenario_title"):
            ctx["scenario_title"] = profile.get("scenario_title")

    research_path = result.get("research_path")
    if isinstance(research_path, dict):
        ctx["topic_id"] = research_path.get("topic_id") or ctx.get("topic_id")
        ctx["topic_title"] = research_path.get("title") or ctx.get("topic_title")
        ctx["scenario_id"] = research_path.get("scenario_id") or ctx.get("scenario_id")
        ctx["scenario_title"] = research_path.get("scenario_title") or ctx.get("scenario_title")
        ctx["scenario_sample_scope"] = (
            research_path.get("sample_scope") or ctx.get("scenario_sample_scope")
        )
    scenario_plan = result.get("scenario_plan")
    if isinstance(scenario_plan, dict):
        ctx["scenario_id"] = scenario_plan.get("scenario_id") or ctx.get("scenario_id")
        ctx["scenario_title"] = scenario_plan.get("title") or ctx.get("scenario_title")
        ctx["scenario_sample_scope"] = (
            scenario_plan.get("sample_scope") or ctx.get("scenario_sample_scope")
        )
    scenario_context = result.get("scenario_context")
    if isinstance(scenario_context, dict):
        ctx["scenario_id"] = scenario_context.get("scenario_id") or ctx.get("scenario_id")
        ctx["scenario_title"] = scenario_context.get("title") or ctx.get("scenario_title")
        ctx["scenario_sample_scope"] = (
            scenario_context.get("sample_scope") or ctx.get("scenario_sample_scope")
        )

    incoming_slots = _extract_slot_values(raw)
    was_slot_reply = bool(
        raw and is_supplement_query(raw, ctx) and (
            had_prior_turn or ctx.get("last_query") or ctx.get("pending_slot")
        )
    )
    if incoming_slots:
        _merge_slots(ctx, raw)
    if was_slot_reply and incoming_slots:
        ctx["last_slot_key"] = next(iter(incoming_slots))
        ctx["last_slot_keys"] = list(incoming_slots)
        ctx["last_slot_values"] = dict(incoming_slots)
    elif not was_slot_reply:
        ctx["last_slot_key"] = None
        ctx["last_slot_keys"] = []
        ctx["last_slot_values"] = {}

    stage = incoming_slots.get("workflow_stage")
    if not stage:
        stage = result.get("active_stage") or result.get("current_stage")
    if stage:
        ctx["current_stage"] = _clean_text(stage, 120)

    if isinstance(research_path, dict):
        active_step = research_path.get("active_step")
        try:
            if active_step is not None:
                ctx["active_stage_index"] = max(0, int(active_step) - 1)
        except (TypeError, ValueError):
            pass

    previous_candidates = _unique(
        ctx.get("candidate_devices") or ctx.get("last_devices") or [],
        5,
    )
    subject_device = result.get("subject_device")
    if isinstance(subject_device, str) and subject_device.strip():
        ctx["current_product"] = subject_device.strip()
        ctx["last_device"] = subject_device.strip()

    context_devices = result.get("_context_devices", [])
    context_names = _unique(context_devices, 5) if isinstance(context_devices, list) else []
    devices = result.get("recommended_devices", [])
    visible_names = _unique([
        item.get("name")
        for item in devices
        if isinstance(item, dict) and item.get("name")
    ], 5) if isinstance(devices, list) else []

    scenario_plan_value = result.get("scenario_plan")
    scenario_names = []
    if isinstance(scenario_plan_value, dict):
        equipment_rows = scenario_plan_value.get("equipment_table", [])
        if isinstance(equipment_rows, list):
            scenario_names = _unique(
                [
                    item.get("name")
                    for item in equipment_rows
                    if isinstance(item, dict) and item.get("name")
                ],
                5,
            )
            if scenario_names:
                ctx["scenario_devices"] = scenario_names

    if intent in {"scenario_plan", "scenario_navigation", "scenario_scope"} and not visible_names:
        # A scenario response is a workflow context, not a product selection.
        # Do not let a product from an earlier turn answer a later "这个方案".
        ctx["last_device"] = None
        ctx["last_devices"] = scenario_names or (
            list(ctx.get("scenario_devices") or [])
            if intent == "scenario_scope" else []
        )
        ctx["current_product"] = None
        ctx["candidate_devices"] = []

    if intent in {"recommend", "recommendation", "similar", "scenario_equipment"}:
        candidate_names = context_names or visible_names
        if candidate_names:
            ctx["candidate_devices"] = candidate_names
            ctx["last_devices"] = candidate_names
        if intent != "detail":
            ctx["current_product"] = None
    elif intent == "detail":
        # A detail answer must not destroy the shortlist that the user may
        # still refer to with “第二个” or “比较前两款”.
        if not ctx.get("current_product") and (context_names or visible_names):
            ctx["current_product"] = (context_names or visible_names)[0]
        if not ctx.get("candidate_devices"):
            ctx["candidate_devices"] = context_names or visible_names or previous_candidates
        ctx["last_devices"] = _unique(ctx.get("candidate_devices") or [], 5)
    elif intent == "compare":
        if context_names or visible_names:
            ctx["candidate_devices"] = context_names or visible_names
            ctx["last_devices"] = context_names or visible_names
    elif intent in {"topic_overview", "topic_stage"}:
        # Topic cards are not selected products yet, but keeping their names
        # lets the user refer to a visible card by ordinal after the overview.
        if visible_names:
            ctx["candidate_devices"] = visible_names
            ctx["last_devices"] = visible_names
        ctx["current_product"] = None

    if intent in {"recommend", "recommendation", "similar", "scenario_equipment"}:
        if visible_names:
            ctx["last_device"] = visible_names[0]
        elif context_names:
            ctx["last_device"] = context_names[0]
    elif intent == "detail" and ctx.get("current_product"):
        ctx["last_device"] = ctx["current_product"]

    # Keep the type of the current conversational object explicit. A topic
    # overview may contain product cards, but a bare "它" after that overview
    # still refers to the topic until the user selects a product.
    if intent == "topic_overview":
        ctx["active_object"] = "topic"
        ctx["active_object_name"] = ctx.get("topic_title")
    elif intent == "topic_stage":
        ctx["active_object"] = "stage"
        ctx["active_object_name"] = ctx.get("current_stage")
    elif intent in {"scenario_plan", "scenario_scope"}:
        ctx["active_object"] = "scenario"
        ctx["active_object_name"] = ctx.get("scenario_title")
    elif intent == "scenario_equipment":
        ctx["active_object"] = "scenario_equipment"
        ctx["active_object_name"] = ctx.get("scenario_title")
    elif intent == "scenario_navigation":
        ctx["active_object"] = None
        ctx["active_object_name"] = None
    elif intent == "detail":
        ctx["active_object"] = "product" if ctx.get("current_product") else None
        ctx["active_object_name"] = ctx.get("current_product")
    elif intent in {"recommend", "recommendation", "similar"}:
        ctx["active_object"] = "recommendation" if ctx.get("last_devices") else None
        ctx["active_object_name"] = ctx.get("last_device")
    elif intent == "compare":
        ctx["active_object"] = "comparison"
        ctx["active_object_name"] = "、".join(ctx.get("last_devices") or [])
    elif intent == "catalog":
        ctx["active_object"] = "catalog"
        ctx["active_object_name"] = "产品目录"

    if raw and not was_slot_reply and intent in {
        "recommend", "recommendation", "topic_overview", "topic_stage",
        "scenario_plan", "scenario_equipment", "scenario_navigation", "clarify",
    }:
        ctx["last_query"] = raw
    elif raw and not ctx.get("last_query") and intent not in {"error", "weather", "human_support", "acknowledgement"}:
        ctx["last_query"] = raw

    questions = result.get("clarifying_questions")
    if isinstance(questions, list) and questions and isinstance(questions[0], dict):
        ctx["pending_slot"] = _clean_text(questions[0].get("id"), 80) or None
    elif intent in {"topic_overview", "topic_stage"} and not ctx.get("current_stage"):
        ctx["pending_slot"] = "workflow_stage"
    elif intent == "acknowledgement":
        pass
    else:
        ctx["pending_slot"] = None
    ctx["last_input_was_slot_reply"] = was_slot_reply
    if raw:
        ctx["turn_count"] = int(ctx.get("turn_count") or 0) + 1
        turns = list(ctx.get("recent_turns") or [])
        turns.append({
            "user": raw,
            "resolved": resolved if resolved and resolved != raw else "",
            "intent": intent,
            "answer": _clean_text(result.get("answer"), 360),
            "devices": (context_names or visible_names)[:3],
        })
        ctx["recent_turns"] = turns[-MAX_RECENT_TURNS:]


def restore_session_context(session_id: str) -> Dict[str, Any]:
    """Rebuild lightweight context from the persisted transcript after a restart."""
    ctx = get_session_context(session_id)
    if int(ctx.get("turn_count") or 0) > 0:
        return ctx
    try:
        from backend.conversation_store import get_conversation

        conversation = get_conversation(session_id)
    except Exception:
        conversation = None
    if not conversation:
        return ctx

    pending_user = None
    for message in conversation.get("messages", [])[-(MAX_RECENT_TURNS * 2 + 2):]:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            pending_user = message.get("content") or ""
            continue
        if message.get("role") != "assistant" or pending_user is None:
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {"intent": message.get("intent"), "answer": message.get("content", "")}
        update_session_context(
            session_id,
            payload,
            raw_query=str(pending_user),
            resolved_query=str(pending_user),
        )
        pending_user = None
    return ctx


def build_model_context(session_id: str) -> Dict[str, Any]:
    """Return a compact, non-sensitive context object for the answer prompt."""
    ctx = get_session_context(session_id)
    return {
        "active_object": _clean_text(ctx.get("active_object"), 40),
        "active_object_name": _clean_text(ctx.get("active_object_name"), 180),
        "topic_id": _clean_text(ctx.get("topic_id"), 80),
        "topic_title": _clean_text(ctx.get("topic_title"), 100),
        "scenario_id": _clean_text(ctx.get("scenario_id"), 80),
        "scenario_title": _clean_text(ctx.get("scenario_title"), 140),
        "scenario_sample_scope": _clean_text(ctx.get("scenario_sample_scope"), 180),
        "current_stage": _clean_text(ctx.get("current_stage"), 100),
        "active_stage_index": ctx.get("active_stage_index"),
        "last_raw_query": _clean_text(ctx.get("last_raw_query"), 260),
        "last_intent": _clean_text(ctx.get("last_intent"), 50),
        "last_answer_focus": _clean_text(ctx.get("last_answer_focus"), 50),
        "last_action": _clean_text(ctx.get("last_action"), 50),
        "last_action_value": _clean_text(ctx.get("last_action_value"), 180),
        "current_product": _clean_text(ctx.get("current_product"), 180),
        "pending_slot": _clean_text(ctx.get("pending_slot"), 60),
        "known_slots": {
            key: _clean_text(value, 120)
            for key, value in (ctx.get("known_slots") or {}).items()
            if key in SLOT_LABELS and value not in (None, "", False)
        },
        "last_devices": _unique(ctx.get("last_devices", []), 5),
        "candidate_devices": _unique(
            ctx.get("candidate_devices") or ctx.get("last_devices", []), 5
        ),
        "scenario_devices": _unique(ctx.get("scenario_devices", []), 5),
        "recent_turns": [
            {
                "user": _clean_text(item.get("user"), 240),
                "resolved": _clean_text(item.get("resolved"), 260),
                "assistant": _clean_text(item.get("answer"), 280),
                "intent": _clean_text(item.get("intent"), 40),
                "devices": _unique(item.get("devices", []), 3),
            }
            for item in (ctx.get("recent_turns") or [])[-MAX_RECENT_TURNS:]
            if isinstance(item, dict)
        ],
    }


def is_supplement_query(user_query: str, context: Dict[str, Any] | None = None) -> bool:
    text = (user_query or "").strip()
    if text in BARE_DETAIL_FOLLOWUPS:
        return False
    if not text or len(text) > 100:
        return False
    if _is_scope_question(text):
        return False
    if any(marker in text for marker in [
        "为什么", "怎么做", "如何", "哪个", "哪些设备", "哪些产品",
        "介绍", "对比", "区别", "多少", "范围", "有哪些", "是否",
        "能否", "适合", "支持", "能处理", "用于", "吗", "呢", "怎么样",
    ]):
        return False
    if text.startswith(("补充信息", "补充信", "补充：", "补充:")):
        return True

    # Navigation requests such as "先看培养环节" are not slot replies even
    # though they contain words like "培养" or "样本".
    if any(text.startswith(prefix) for prefix in ("我想先看", "我想看", "先看", "查看", "进入")):
        return False
    if is_topic_stage_query(text):
        return False

    # A bare topic name is a navigation choice, not a newly confirmed task or
    # sample. Explicit sample wording still takes precedence below.
    profile = _topic_profile(text)
    if profile and not _has_explicit_sample_signal(text):
        return False

    if context and context.get("pending_slot") and _extract_slot_values(text):
        return True
    if any(text.startswith(prefix) for prefix in SLOT_REPLY_PREFIXES):
        return bool(_extract_slot_values(text))

    intent_keywords = ["推荐", "介绍", "详情", "对比", "区别", "是什么", "哪些设备"]
    return len(text) <= 60 and any(x in text for x in SUPPLEMENT_KEYWORDS) and not any(x in text for x in intent_keywords)


def strip_supplement_prefix(user_query: str) -> str:
    text = (user_query or "").strip()
    for prefix in ["补充信息：", "补充信息:", "补充信：", "补充信:", "补充：", "补充:"]:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def is_device_followup_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text or len(text) > 40:
        return False

    if extract_device_name(text):
        return False

    return any(keyword in text for keyword in DEVICE_FOLLOWUP_KEYWORDS) or _is_scope_question(text)


def is_detail_followup_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text or len(text) > 40:
        return False

    if extract_device_name(text):
        return False

    return any(keyword in text for keyword in DETAIL_FOLLOWUP_KEYWORDS)


def is_candidate_followup_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text or len(text) > 60:
        return False

    keywords = [
        "哪个更适合",
        "哪个适合",
        "推荐哪个",
        "选哪个",
        "怎么选",
        "怎么选择",
        "这些设备",
        "这几个",
        "它们",
        "区别",
        "差异",
        "比较一下",
        "对比一下",
        "优先选",
        "便宜点",
        "更自动化",
        "适合我",
    ]
    return any(keyword in text for keyword in keywords)


def is_comparison_followup_query(user_query: str) -> bool:
    """Recognize comparisons that refer to the previous shortlist implicitly."""
    text = re.sub(r"\s+", "", str(user_query or ""))
    if not text:
        return False
    comparison_terms = (
        "对比", "比较", "区别", "差异", "哪个好", "怎么选", "优先选",
    )
    # General references such as “这几个设备” are handled by the existing
    # candidate-followup branch, which intentionally keeps its stable wording.
    # This helper is for ordinal comparisons that otherwise contain no product
    # name at all, especially the common “比较前两款设备”。
    reference_terms = ("前两", "前2", "第二个和第三个", "第一和第二", "第一款和第二款")
    return (
        any(term in text for term in comparison_terms)
        and any(term in text for term in reference_terms)
    )


def is_topic_stage_query(user_query: str) -> bool:
    text = re.sub(r"\s+", "", str(user_query or ""))
    return any(term in text for term in STAGE_REPLY_TERMS)


def is_topic_reference_query(user_query: str) -> bool:
    text = str(user_query or "")
    return any(term in text for term in TOPIC_REFERENCE_TERMS)


def is_topic_scope_query(user_query: str, context: Dict[str, Any] | None = None) -> bool:
    """Whether the user asks about the research direction rather than a product."""
    if not context or not context.get("topic_title") or not _is_scope_question(user_query):
        return False
    text = str(user_query or "")
    if is_topic_reference_query(text) or any(
        marker in text for marker in ("整个方向", "研究方向", "这个主题", "该主题")
    ):
        return True

    # After a topic overview/stage, a short question such as "它适合哪些样本"
    # refers to the research direction unless the user explicitly selects a
    # product or an ordinal card.
    active_object = str(context.get("active_object") or "")
    if active_object in {"topic", "stage"}:
        if any(marker in text for marker in ("第一个", "第二个", "第三个", "这台设备", "这个产品", "这款设备")):
            return False
        return True
    return False


def is_scenario_scope_query(
    user_query: str,
    context: Dict[str, Any] | None = None,
) -> bool:
    text = str(user_query or "")
    if not _is_scope_question(text):
        return False
    if any(marker in text for marker in ("这个方案", "该方案", "方案适合", "方案的样本")):
        return True
    if context and str(context.get("active_object") or "") == "scenario":
        if any(marker in text for marker in ("第一个", "第二个", "第三个", "这台设备", "这个产品", "这款设备")):
            return False
        return True
    return False


def is_scenario_equipment_reference(user_query: str) -> bool:
    text = re.sub(r"\s+", "", str(user_query or ""))
    return bool(text) and any(term in text for term in SCENARIO_EQUIPMENT_REFERENCE_TERMS)


def is_pronoun_detail_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text or len(text) > 40:
        return False
    has_pronoun = any(term in text for term in ("它", "这台", "这个设备", "这个产品", "这款", "该设备"))
    return has_pronoun and any(term in text for term in ("怎么样", "如何", "好吗", "呢", "介绍", "详情"))


def is_acknowledgement_query(user_query: str) -> bool:
    text = re.sub(r"[\s，。！？!,.]+", "", str(user_query or ""))
    return bool(text) and text in ACKNOWLEDGEMENT_TERMS


def is_more_candidate_query(user_query: str) -> bool:
    text = re.sub(r"\s+", "", str(user_query or ""))
    if not text or len(text) > 40:
        return False
    return any(term in text for term in MORE_CANDIDATE_TERMS)


def is_product_reference_query(user_query: str) -> bool:
    text = re.sub(r"[\s，。！？!,.]+", "", str(user_query or ""))
    if not text or len(text) > 30:
        return False
    return text in PRODUCT_REFERENCE_TERMS or (
        any(term in text for term in ("这个", "这款", "它", "这台"))
        and any(term in text for term in ("呢", "怎么样", "可以吗", "就这个"))
    )


def is_context_switch_query(user_query: str) -> bool:
    text = re.sub(r"\s+", "", str(user_query or ""))
    return text in CONTEXT_SWITCH_TERMS or any(text.startswith(term) for term in CONTEXT_SWITCH_TERMS)


def is_continuation_query(user_query: str) -> bool:
    text = re.sub(r"\s+", "", str(user_query or ""))
    return text in CONTINUATION_TERMS or text in {
        "然后呢", "那下一步呢", "接下来呢", "接下来怎么做", "接着来",
        "好继续", "好的继续", "再往下看",
    } or any(text.startswith(term) for term in ("继续了解", "接着看", "下一步", "接下来"))


def next_topic_stage(context: Dict[str, Any]) -> str | None:
    sequence = TOPIC_STAGE_SEQUENCE.get(str(context.get("topic_id") or ""))
    if not sequence:
        return None
    current = str(context.get("current_stage") or "")
    if not current:
        return sequence[0]
    for index, stage in enumerate(sequence):
        if stage in current:
            # Reaching the last stage is a natural hand-off to the complete
            # plan rather than repeating the same stage forever.
            return sequence[index + 1] if index + 1 < len(sequence) else None
    return sequence[0]


def is_contextual_slot_reply(user_query: str, context: Dict[str, Any] | None = None) -> bool:
    return is_supplement_query(user_query, context)


def resolve_ordinal_device(user_query: str, device_names: list[str]) -> tuple[str | None, str | None]:
    text = (user_query or "").strip()
    for index, markers in ORDINAL_DEVICE_MARKERS.items():
        if index >= len(device_names):
            continue
        marker = next((item for item in markers if item in text), None)
        if marker:
            return device_names[index], marker
    return None, None


def resolve_query_with_context(user_query: str, session_id: str) -> str:
    user_query = (user_query or "").strip()
    ctx = get_session_context(session_id)
    last_device = ctx.get("last_device")
    last_devices = ctx.get("candidate_devices") or ctx.get("last_devices") or []
    current_product = ctx.get("current_product") or (
        ctx.get("last_device") if ctx.get("active_object") == "product" else None
    )
    last_query = ctx.get("last_query")
    topic_title = ctx.get("topic_title")
    scenario_title = ctx.get("scenario_title")
    last_intent = str(ctx.get("last_intent") or "")

    if not user_query:
        return user_query

    # A new explicit product or research topic should remain the source of
    # truth; do not prepend stale context to it.
    explicit_device = _safe_device_name(user_query)
    try:
        from backend.general_query import detect_non_product_intent

        if detect_non_product_intent(user_query) in {"weather", "human_support", "model_identity"}:
            return user_query
    except Exception:
        pass

    # An explicitly named new research direction is the source of truth. Do
    # not attach an old topic to it before the context updater can reset state.
    explicit_profile = _topic_profile(user_query)
    if explicit_profile and topic_title:
        explicit_id = str(explicit_profile.get("id") or "")
        if explicit_id and explicit_id != str(ctx.get("topic_id") or ""):
            return user_query
    if (
        topic_title
        and _research_context_key(user_query)
        and _research_context_key(user_query) != f"topic:{ctx.get('topic_id')}"
        and not explicit_device
    ):
        return user_query

    active_object = str(ctx.get("active_object") or "")

    if is_context_switch_query(user_query):
        return user_query

    # Keep the original task and explicitly exclude the previous shortlist so
    # a “再推荐几个” turn is a genuine continuation rather than a reset.
    if is_more_candidate_query(user_query) and last_devices:
        base_query = last_query or topic_title or scenario_title or "当前实验需求"
        excluded = "、".join(last_devices[:5])
        return f"{base_query}：请再推荐2至3款不同的替代产品，排除{excluded}"

    # Natural-language comparisons such as “比较前两款设备” do not contain
    # product names. Resolve them against the retained shortlist so the
    # comparison workflow receives the same explicit names as a UI click.
    if len(last_devices) >= 2 and is_comparison_followup_query(user_query):
        return f"对比：{last_devices[0]} 和 {last_devices[1]} 有什么区别？"

    # Stage selections are more specific than a pending generic clarification.
    # Keep the current research direction while routing the stage to the topic
    # catalog instead of treating it as a fresh unrelated product search.
    if topic_title and not explicit_device and is_topic_stage_query(user_query):
        return f"{topic_title}：{user_query}"

    if topic_title and not explicit_device and any(
        marker in user_query for marker in ("完整方案", "场景方案", "实施方案", "研究路线", "全流程")
    ):
        return f"{topic_title}完整方案"

    if scenario_title and not explicit_device and is_scenario_scope_query(user_query, ctx):
        return f"{scenario_title}：{user_query}"

    # Keep explicit plan equipment questions attached to the active scenario.
    # The scenario-specific workflow can then return several related products
    # instead of sending the query to the generic keyword recommender.
    if scenario_title and not explicit_device and (
        is_scenario_equipment_reference(user_query)
        or (
            active_object in {"scenario", "scenario_equipment"}
            and any(marker in user_query for marker in ("这个方案", "该方案"))
        )
    ):
        return f"{scenario_title}：{user_query}"

    # A bare scope question after a topic overview belongs to the direction as
    # a whole, not to the first product card shown below it.
    if topic_title and not explicit_device and is_topic_scope_query(user_query, ctx):
        return f"{topic_title}：{user_query}"

    if topic_title and not explicit_device and is_topic_reference_query(user_query):
        return f"{topic_title}：{user_query}"

    # Resolve conversational product references before generic device/detail
    # keyword handling. “这个呢” normally means the primary card, while an
    # explicitly selected product has priority over the shortlist.
    if is_product_reference_query(user_query):
        if current_product:
            rewritten = user_query
            for pronoun in ("这个产品", "这个设备", "这台设备", "这款设备", "这个型号", "这款", "这个", "它", "这台"):
                rewritten = rewritten.replace(pronoun, current_product)
            return rewritten if rewritten != user_query else f"介绍一下{current_product}"
        if active_object == "recommendation" and last_devices:
            primary = last_devices[0]
            return f"介绍一下{primary}"
        if active_object in {"topic", "stage", "scenario", "scenario_equipment"}:
            base = topic_title or scenario_title
            if base:
                return f"{base}：{user_query}"

    if scenario_title and not explicit_device and active_object in {"scenario", "scenario_equipment"} and is_continuation_query(user_query):
        return f"{scenario_title}的核心设备选型"

    if last_device and active_object == "product" and is_continuation_query(user_query):
        return f"关于{last_device}，请继续介绍它的应用场景和选型边界"

    if topic_title and not explicit_device and active_object in {"topic", "stage", "comparison"} and is_continuation_query(user_query):
        next_stage = next_topic_stage(ctx)
        if next_stage:
            return f"{topic_title}：我想继续看{next_stage}"
        return f"{topic_title}完整方案"

    if last_devices and active_object == "recommendation" and is_continuation_query(user_query):
        names = last_devices[:2]
        if len(names) >= 2:
            return f"对比：{names[0]} 和 {names[1]} 有什么区别？"
        if names:
            return f"介绍一下{names[0]}的适用样本和应用场景"

    # A declared condition (for example, "样本是肿瘤组织") is a response to
    # the previous turn's missing information. Resolve it before the generic
    # device-keyword branch, which also contains the word "样本".
    if is_supplement_query(user_query, ctx):
        if topic_title:
            base_query = topic_title
            if ctx.get("current_stage"):
                base_query += f"：{ctx['current_stage']}"
        else:
            base_query = last_query
        if base_query:
            return f"{base_query}\n补充信息：{strip_supplement_prefix(user_query)}"

    # Resolve ordinal and comparison references before treating words such as
    # "样本" or "通量" as newly supplied slots.
    if last_devices:
        ordinal_device, ordinal_marker = resolve_ordinal_device(user_query, last_devices)
        if ordinal_device and ordinal_marker:
            if len((user_query or "").strip()) <= len(ordinal_marker) + 2:
                return f"介绍一下{ordinal_device}"
            return user_query.replace(ordinal_marker, ordinal_device)

        if is_candidate_followup_query(user_query):
            names = "、".join(last_devices)
            return f"根据上一轮候选设备（{names}），请给出选型建议：{user_query}"

    if last_device and any(keyword in user_query for keyword in RATIONALE_FOLLOWUP_KEYWORDS):
        context = f"结合上一轮需求「{last_query}」，" if last_query else ""
        return f"{context}为什么推荐{last_device}？"

    if last_device and is_similar_followup_text(user_query):
        return build_contextual_similar_query(last_device, user_query, last_query)

    if last_device:
        pronouns = ["这台设备", "这个设备", "这个产品", "这个型号", "它", "该设备", "这款设备", "这款"]
        rewritten = user_query
        replaced = False

        for pronoun in pronouns:
            if pronoun in rewritten:
                rewritten = rewritten.replace(pronoun, last_device)
                replaced = True

        if replaced:
            return rewritten

        if is_device_followup_query(user_query) or is_pronoun_detail_query(user_query):
            return f"关于{last_device}，{user_query}"

        if is_detail_followup_query(user_query):
            return f"介绍一下{last_device}"

    return user_query
