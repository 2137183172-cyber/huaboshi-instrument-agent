from __future__ import annotations

import re
from typing import Any

from backend.knowledge_catalog import load_scenarios, score_scenario
from backend.local_catalog import get_local_device_detail


REQUEST_MARKERS = ("方案", "流程", "怎么做", "如何做", "如何开展", "全流程", "研究路线")
# Full scenario output is intentionally an explicit, opt-in capability. Keep
# generic how-to questions on the normal graph/product workflow.
SCENARIO_REQUEST_MARKERS = (
    "场景", "方案", "应用场景", "应用方案", "应用",
    "实施方案", "完整方案", "实验方案", "研究方案",
    "实验流程", "工作流程", "研究路线", "全流程",
)
SCENARIO_STRONG_PLAN_MARKERS = (
    "实施方案", "完整方案", "实验方案", "研究方案", "实验流程",
    "工作流程", "研究路线", "全流程",
)
DETAIL_MARKERS = ("介绍", "详情", "参数", "配置", "报价", "价格", "多少钱")
SCENARIO_TERMS = (
    "中医药", "中药", "临床前", "肿瘤早筛", "伴随诊断", "多光谱", "高光谱", "气味", "异味",
    "生物样本库", "微生物", "酶活", "类器官", "外泌体", "细胞打印", "激光显微切割",
    "微区组学", "植物抗逆", "植物病理", "DNA合成", "基因编辑", "突变体库", "高通量基因合成",
    "合成生物学", "分子育种", "转基因", "空间组学", "空间原位", "细胞治疗", "细胞生产",
    "作物育种", "种子表型", "蛋白互作", "药敏", "流式细胞", "小动物体内", "NGS", "建库", "测序",
)
SCENARIO_NAVIGATION_MARKERS = (
    "场景方案", "方案推荐", "有哪些方案", "有什么方案", "方案有哪些",
    "场景", "方案", "应用场景", "应用方案", "应用",
)
PRODUCT_SELECTION_MARKERS = ("推荐", "选型", "产品", "设备", "仪器", "型号")
SCENARIO_NAVIGATION_OPTIONS = (
    "中医药研究方案",
    "临床前药物研发综合方案",
    "类器官研究综合方案",
    "空间组学/组织原位多重检测方案",
    "NGS靶向测序方案",
    "细胞治疗/细胞生产工艺方案",
    "蛋白互作筛选方案",
    "中药材/茶叶/食品品质多光谱检测方案",
)
RELATION_ORDER = ("核心设备", "必选设备", "可选设备", "通用辅助设备", "替代设备", "前置设备", "下游设备", "不兼容设备")
SCENARIO_SCOPE_TERMS = (
    "适合哪些样本", "适合什么样本", "适用哪些样本", "样本范围", "样本类型有哪些",
    "有哪些应用场景", "适合哪些应用", "用于哪些场景", "可以做什么实验",
    "方案有哪些应用", "方案能做什么", "方案用于哪些场景",
)

# A plan is a workflow, so "continue" should be able to open the equipment
# layer without falling back to a broad keyword search. These phrases are
# intentionally narrower than the ordinary product-selection vocabulary.
SCENARIO_EQUIPMENT_TERMS = (
    "核心设备选型", "方案设备选型", "设备如何选型", "各步骤的设备",
    "各环节的设备", "方案设备", "设备配置", "实施路径", "上下游如何衔接",
    "上下游怎么衔接", "上下游衔接", "需要哪些设备", "本环节设备", "环节设备",
)

SCENARIO_EQUIPMENT_LIMIT = 4
RELATION_PRIORITY = {
    "核心设备": 100,
    "必选设备": 80,
    "可选设备": 45,
    "替代设备": 35,
    "通用辅助设备": 20,
    "前置设备": 20,
    "下游设备": 20,
}

BOUNDARY_MARKER = re.compile(r"边界说明\s*[:：].*$", re.S)


def _strip_boundary_text(value: Any) -> str:
    """Remove internal boundary annotations before scenario content is exposed."""
    text = " ".join(str(value or "").split())
    match = BOUNDARY_MARKER.search(text)
    if match:
        text = text[:match.start()].rstrip(" ；;。")
    return text


def _compact(value: Any, limit: int = 280) -> str:
    text = _strip_boundary_text(value)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _table_origin(value: Any) -> str:
    """Keep only the public origin labels used by the scenario table."""
    text = _compact(value, 40).replace("自研", "")
    return text.strip(" /、,，|")


def _relation_lines(step: dict[str, Any], relation: str) -> list[str]:
    lines = []
    for item in step.get("relations", {}).get(relation, []):
        if not isinstance(item, dict):
            continue
        # Relationship sections list equipment identities. Detailed usage belongs
        # in the equipment table and must not replace the device name here.
        text = _compact(item.get("name"), 240)
        if text and text not in lines:
            lines.append(text)
    return lines


def _equipment_rows(step: dict[str, Any]) -> list[dict[str, str]]:
    """Build rows from the source document, enriching them with product details."""
    rows = []
    raw_devices = step.get("devices", [])
    if not isinstance(raw_devices, list):
        raw_devices = step.get("relations", {}).get("核心设备", [])

    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        name = _compact(item.get("name"), 160)
        if not name or name == "无":
            continue
        detail = get_local_device_detail(name) or {}
        description = _compact(item.get("description"), 360)
        vendor_match = __import__("re").search(r"（([^（）]+)）\s*$", description)
        inferred_brand = vendor_match.group(1) if vendor_match else ""
        rows.append({
            "name": _compact(detail.get("name") or name, 160),
            "brand": _compact(detail.get("brand_vendor") or inferred_brand, 80),
            "model": _compact(detail.get("product_code"), 80),
            "applications": _compact(
                detail.get("applications") or detail.get("overview") or description,
                360,
            ),
            "origin": _table_origin(detail.get("origin") or ("外部过渡设备" if item.get("external") else "")),
            "description": description,
            "step_no": str(step.get("step_no") or ""),
        })
    return rows


def _scenario_score(query: str, scenario: dict[str, Any]) -> int:
    score, _ = score_scenario(query, scenario)
    query_text = (query or "").casefold()
    scenario_id = str(scenario.get("scenario_id") or "").casefold()
    title = str(scenario.get("title") or "").casefold()
    compact_query = re.sub(r"\s+", "", query_text)
    if scenario_id and re.search(rf"(?<![a-z0-9-]){re.escape(scenario_id)}(?![a-z0-9-])", compact_query):
        score += 240
    if title and (title in query_text or query_text in title):
        score += 180
    # Normalize common user wording to the official scenario vocabulary.
    scenario_source_text = " ".join(
        str(scenario.get(field) or "")
        for field in ("title", "applications", "positioning", "sample_scope")
    ).casefold()
    for query_term, scenario_term in (("中药", "中医药"), ("药物筛选", "临床前"), ("活体成像", "小动物体内")):
        if query_term in query_text and scenario_term in scenario_source_text:
            score += 80
    for field in ("title", "applications", "positioning", "sample_scope"):
        value = str(scenario.get(field) or "").casefold()
        if not value:
            continue
        for phrase in ("类器官", "克隆", "微生物", "酶活", "蛋白", "空间组学", "单细胞", "建库", "测序", "细胞培养", "药敏", "植物", "质谱"):
            if phrase in query_text and phrase in value:
                score += 18
    return score


def _is_explicit_device_detail_query(query: str) -> bool:
    text = (query or "").strip()
    if not any(marker in text for marker in DETAIL_MARKERS):
        return False
    # "介绍一下类器官的应用" is a research-direction request, while a named
    # product's application question should remain on the detail route.
    if any(marker in text for marker in ("应用", "场景")) and not _mentions_known_product(text):
        return False
    return not any(marker in text for marker in REQUEST_MARKERS)


def _mentions_known_product(query: str) -> bool:
    """Use the catalog name resolver only for product-specific application questions."""
    try:
        from backend.device_name_extractor import extract_device_name

        return bool(extract_device_name(query))
    except Exception:
        return False


def _is_product_application_query(query: str) -> bool:
    text = (query or "").strip()
    if not _mentions_known_product(text) or not any(marker in text for marker in ("应用", "场景")):
        return False
    return not any(marker in text for marker in SCENARIO_STRONG_PLAN_MARKERS)


def _should_match_scenario(query: str) -> bool:
    text = (query or "").strip()
    if not text or _is_explicit_device_detail_query(text) or _is_product_application_query(text):
        return False
    # A research topic plus any scenario/application marker opens the matching
    # workflow plan. Product-selection wording remains on the product route.
    if bool(re.search(r"\bS(?:\d+|-[A-Z0-9]+)\b", text, re.I)):
        return True
    scenario_topic = any(term in text for term in SCENARIO_TERMS)
    explicit_plan_phrase = any(marker in text for marker in SCENARIO_REQUEST_MARKERS)
    if explicit_plan_phrase and scenario_topic:
        if (
            any(marker in text for marker in PRODUCT_SELECTION_MARKERS)
            and not any(marker in text for marker in SCENARIO_STRONG_PLAN_MARKERS)
        ):
            return False
        return True
    # A named research topic plus a bare plan/application word is a direct plan
    # request, unless the user explicitly asks for equipment recommendations.
    if scenario_topic and any(marker in text for marker in ("场景", "方案", "应用")):
        return not any(marker in text for marker in PRODUCT_SELECTION_MARKERS)
    return False


def is_scenario_navigation_query(query: str) -> bool:
    """Detect a request to browse plans without selecting a research topic yet."""
    text = (query or "").strip()
    if (
        not text
        or any(term in text for term in SCENARIO_TERMS)
        or _mentions_known_product(text)
        or _is_explicit_device_detail_query(text)
    ):
        return False
    return any(marker in text for marker in SCENARIO_NAVIGATION_MARKERS)


def build_scenario_navigation_result(query: str) -> dict[str, Any] | None:
    if not is_scenario_navigation_query(query):
        return None
    return {
        "intent": "scenario_navigation",
        "answer": "有的。当前已收录多个科研场景方案。请选择一个方向，我会继续展示对应的实施步骤和相关产品设备。",
        "recommended_devices": [],
        "need_more_info": ["请选择需要查看的场景方案。"],
        "clarifying_title": "选择场景方案",
        "clarifying_questions": [{
            "id": "scenario_direction",
            "question": "请选择需要查看的场景方案",
            "options": list(SCENARIO_NAVIGATION_OPTIONS),
        }],
        "related_questions": [
            "按实验任务推荐产品",
            "有什么产品",
            "请介绍一个具体产品",
        ],
        "disclaimer": "场景方案用于科研和技术服务参考，具体产品配置以实际实验需求为准。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }


def match_scenario(query: str) -> dict[str, Any] | None:
    text = (query or "").strip()
    if not _should_match_scenario(text):
        return None

    ranked = []
    for scenario in load_scenarios():
        score = _scenario_score(text, scenario)
        if score > 0:
            ranked.append((score, scenario))
    if not ranked:
        return None

    ranked.sort(key=lambda item: item[0], reverse=True)
    score, scenario = ranked[0]
    return scenario if score >= 16 else None


def is_scenario_scope_query(query: str) -> bool:
    text = re.sub(r"\s+", "", str(query or ""))
    return any(term in text for term in SCENARIO_SCOPE_TERMS)


def _scenario_from_reference(query: str) -> dict[str, Any] | None:
    """Prefer an explicitly named scenario over fuzzy keyword scoring."""
    text = re.sub(r"\s+", "", str(query or "")).casefold()
    if not text:
        return None

    exact_matches = []
    for scenario in load_scenarios():
        scenario_id = re.sub(r"\s+", "", str(scenario.get("scenario_id") or "")).casefold()
        title = re.sub(r"\s+", "", str(scenario.get("title") or "")).casefold()
        if scenario_id and scenario_id in text:
            exact_matches.append((2, len(scenario_id), scenario))
        elif title and title in text:
            exact_matches.append((1, len(title), scenario))
    if not exact_matches:
        return None
    exact_matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return exact_matches[0][2]


def build_scenario_scope_result(query: str) -> dict[str, Any] | None:
    """Answer a scope question about a plan without rendering the whole plan again."""
    if not is_scenario_scope_query(query):
        return None
    scenario = _scenario_from_reference(query) or match_scenario(query)
    if scenario is None:
        return None

    title = _compact(scenario.get("title"), 140)
    sample_scope = _compact(scenario.get("sample_scope"), 360)
    applications = _compact(scenario.get("applications"), 300)
    text = re.sub(r"\s+", "", str(query or ""))
    if "样本" in text:
        if sample_scope:
            answer = f"《{title}》适用的样本范围：{sample_scope}"
        else:
            answer = f"当前方案资料未明确列出《{title}》的具体样本范围。"
        answer += "具体样本状态和前处理要求仍需结合实验方法确认。"
        focus = "samples"
    else:
        if applications:
            answer = f"《{title}》主要覆盖：{applications}"
        else:
            answer = f"当前方案资料未明确列出《{title}》的具体应用场景。"
        answer += "如需落到设备选型，还需要结合实验环节和样本条件。"
        focus = "applications"

    return {
        "intent": "scenario_scope",
        "answer_focus": focus,
        "answer": answer,
        "scenario_context": {
            "scenario_id": scenario.get("scenario_id"),
            "title": title,
            "sample_scope": sample_scope,
        },
        "recommended_devices": [],
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [],
        "disclaimer": "内容来自当前场景方案资料，具体适配性需结合实际实验条件确认。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }


def is_scenario_equipment_query(query: str) -> bool:
    text = re.sub(r"\s+", "", str(query or ""))
    return bool(text) and any(term in text for term in SCENARIO_EQUIPMENT_TERMS)


def _scenario_for_equipment_query(query: str) -> dict[str, Any] | None:
    """Resolve a plan reference even when the query also contains "选型"."""
    scenario = _scenario_from_reference(query)
    if scenario:
        return scenario

    ranked = []
    for item in load_scenarios():
        score = _scenario_score(query, item)
        if score > 0:
            ranked.append((score, item))
    if not ranked:
        return None
    ranked.sort(key=lambda value: value[0], reverse=True)
    score, scenario = ranked[0]
    return scenario if score >= 16 else None


def _step_query_score(query: str, step: dict[str, Any]) -> int:
    text = re.sub(r"\s+", "", str(query or "")).casefold()
    name = re.sub(r"\s+", "", str(step.get("name") or "")).casefold()
    if not text or not name:
        return 0
    score = 0
    if name in text:
        score += 12

    name_parts = [part for part in re.split(r"[,，、/／和与及\s]+", name) if len(part) >= 2]
    score += sum(4 for part in name_parts if part in text)

    # These terms distinguish workflow stages while avoiding broad words such
    # as "方案" that occur in every plan title.
    stage_terms = (
        "样本", "切片", "质控", "解离", "接种", "培养", "换液", "维护", "成像",
        "形态", "药敏", "终点", "组织", "空间", "组学", "流式", "上机", "建库",
        "测序", "数据", "归档", "互作", "蛋白", "细胞", "动物", "验证",
    )
    score += sum(2 for term in stage_terms if term in text and term in name)
    return score


def _strip_scenario_reference(query: str, scenario: dict[str, Any]) -> str:
    """Remove the plan title so title words do not masquerade as a stage request."""
    text = str(query or "")
    title = str(scenario.get("title") or "").strip()
    references = [title, scenario.get("scenario_id")]
    # Some callers use the shorter profile title while the scenario catalog
    # stores a parenthetical qualifier. Remove meaningful title segments too.
    references.extend(
        part for part in re.split(r"[/／（）()、，,：:]", title) if len(part.strip()) >= 3
    )
    for reference in references:
        value = str(reference or "").strip()
        if value:
            text = text.replace(value, "")
    return re.sub(r"\s+", "", text)


def _relation_for_device(step: dict[str, Any], device_name: str) -> str:
    compact_name = re.sub(r"\s+", "", str(device_name or "")).casefold()
    for relation, items in (step.get("relations") or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = re.sub(
                r"\s+", "", str(item.get("name") or item.get("description") or "")
            ).casefold()
            if candidate and (candidate == compact_name or compact_name in candidate or candidate in compact_name):
                return str(relation)
    return "核心设备"


def _detail_match_score(source_name: str, detail: dict[str, Any]) -> int:
    source = re.sub(r"[\s\-_/，,；;：:（）()]+", "", str(source_name or "")).casefold()
    detail_name = re.sub(r"[\s\-_/，,；;：:（）()]+", "", str(detail.get("name") or "")).casefold()
    if not source or not detail_name:
        return 0
    score = 0
    if source in detail_name or detail_name in source:
        score += 20
    source_tokens = re.findall(r"[a-z][a-z0-9]{2,}", source)
    score += sum(12 for token in source_tokens if token in detail_name)
    # A long Chinese phrase is useful for names without a model token, while
    # short generic words such as "系统" are deliberately ignored.
    chinese_parts = [part for part in re.findall(r"[\u4e00-\u9fff]{3,}", source) if len(part) >= 3]
    score += sum(5 for part in chinese_parts if part in detail_name)
    return score


def _scenario_local_detail(name: str) -> dict[str, Any]:
    """Find a catalog detail without accepting a fuzzy hit from another family."""
    candidates = [str(name or "").strip()]
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(name or "")))
    best: tuple[int, dict[str, Any]] | None = None
    for candidate in candidates:
        detail = get_local_device_detail(candidate)
        if not detail:
            continue
        score = _detail_match_score(name, detail)
        if score < 10:
            continue
        if best is None or score > best[0]:
            best = (score, detail)
    return best[1] if best else {}


def _scenario_equipment_card(
    raw_device: dict[str, Any],
    step: dict[str, Any],
    relation: str,
) -> dict[str, Any] | None:
    raw_name = _compact(raw_device.get("name"), 160)
    if not raw_name or raw_name == "无" or raw_device.get("external"):
        return None

    if 'record_ids' in raw_device:
        from backend.scenario_device_rows import reviewed_equipment_row
        row = reviewed_equipment_row(raw_device, step)
        detail = {'name':row['name'], 'product_code':row['model'], 'brand_vendor':row['brand']}
    else:
        detail = _scenario_local_detail(raw_name)
    source_description = _compact(raw_device.get("description"), 300)
    vendor_match = re.search(r"（([^（）]+)）\s*$", source_description)
    name = _compact(detail.get("name") or raw_name, 160)
    step_name = _compact(step.get("name"), 100)
    reasons = [f"对应环节：{step_name}", f"方案定位：{relation}"]
    if source_description and source_description not in name:
        reasons.append(_compact(source_description, 120))

    evidence = detail.get("evidence_chunks", []) if isinstance(detail.get("evidence_chunks"), list) else []
    return {
        "name": name,
        "product_code": detail.get("product_code"),
        "category": detail.get("category"),
        "reasons": reasons[:3],
        "capabilities": detail.get("capabilities", []),
        "tasks": detail.get("tasks", []),
        "sample_types": detail.get("sample_types", []),
        "workflow_roles": detail.get("workflow_roles", []),
        "automation_level": detail.get("automation_level"),
        "throughput_level": detail.get("throughput_level"),
        "overview": _compact(detail.get("overview") or source_description, 240),
        "advantages": _compact(detail.get("advantages"), 200),
        "applications": _compact(detail.get("applications") or source_description, 260),
        "description": source_description,
        "matched_reason": f"可覆盖《{step_name}》中的{relation}职责。",
        "fit_tags": [],
        "selection_notes": [],
        "source_pages": detail.get("source_pages", []) if isinstance(detail.get("source_pages"), list) else [],
        "evidence": evidence[:2],
        "scenario_step": step_name,
        "scenario_relation": relation,
        "brand_vendor": detail.get("brand_vendor") or (vendor_match.group(1) if vendor_match else ""),
    }


def build_scenario_equipment_result(query: str) -> dict[str, Any] | None:
    """Return a small, cross-step equipment shortlist for an active plan."""
    if not is_scenario_equipment_query(query):
        return None
    scenario = _scenario_for_equipment_query(query)
    if scenario is None:
        return None

    stage_query = _strip_scenario_reference(query, scenario)
    scored_steps = []
    for step in scenario.get("steps", []):
        if not isinstance(step, dict):
            continue
        scored_steps.append((_step_query_score(stage_query, step), step))
    if not scored_steps:
        return None

    best_step_score = max(score for score, _ in scored_steps)
    selected_steps = [step for score, step in scored_steps if score > 0 and score >= best_step_score - 3]
    if not selected_steps:
        selected_steps = [step for _, step in scored_steps]

    rows = []
    for step in selected_steps:
        devices = step.get("devices", [])
        if not isinstance(devices, list):
            devices = step.get("relations", {}).get("核心设备", [])
        if not isinstance(devices, list):
            continue
        step_score = _step_query_score(stage_query, step)
        for raw_device in devices:
            if not isinstance(raw_device, dict) or raw_device.get("external"):
                continue
            relation = _relation_for_device(step, str(raw_device.get("name") or ""))
            card = _scenario_equipment_card(raw_device, step, relation)
            if not card:
                continue
            rows.append((
                RELATION_PRIORITY.get(relation, 10) + step_score * 8,
                str(step.get("step_no") or ""),
                card,
            ))

    rows.sort(key=lambda value: value[0], reverse=True)
    selected_cards = []
    seen_names = set()
    seen_steps = set()
    # Cover different workflow steps first; then fill remaining slots from the
    # strongest step when the user asked about one specific stage.
    for _, step_no, card in rows:
        key = re.sub(r"\s+", "", str(card.get("name") or "")).casefold()
        if not key or key in seen_names or step_no in seen_steps:
            continue
        selected_cards.append(card)
        seen_names.add(key)
        seen_steps.add(step_no)
        if len(selected_cards) >= SCENARIO_EQUIPMENT_LIMIT:
            break
    if len(selected_cards) < SCENARIO_EQUIPMENT_LIMIT:
        for _, _, card in rows:
            key = re.sub(r"\s+", "", str(card.get("name") or "")).casefold()
            if not key or key in seen_names:
                continue
            selected_cards.append(card)
            seen_names.add(key)
            if len(selected_cards) >= SCENARIO_EQUIPMENT_LIMIT:
                break

    title = _compact(scenario.get("title"), 140)
    selected_stage_names = [_compact(step.get("name"), 80) for step in selected_steps if step.get("name")]
    stage_hint = "、".join(selected_stage_names[:2])
    if selected_cards:
        answer = f"《{title}》需要按实验环节组合设备，不是一台仪器包办全部流程。"
        if stage_hint and best_step_score > 0:
            answer += f"针对{stage_hint}，先列出 {len(selected_cards)} 款直接相关的候选，便于比较主设备和流程衔接。"
        else:
            answer += f"先列出覆盖不同环节的 {len(selected_cards)} 款代表性设备，后续可再按样本和通量缩小范围。"
    else:
        answer = f"《{title}》的方案设备明细暂未整理出可直接匹配的产品，请先查看完整实施路径。"

    return {
        "intent": "scenario_equipment",
        "answer_focus": "scenario_equipment",
        "answer": answer,
        "scenario_context": {
            "scenario_id": scenario.get("scenario_id"),
            "title": title,
            "sample_scope": _compact(scenario.get("sample_scope"), 240),
            "selected_stages": selected_stage_names[:4],
        },
        "recommended_devices": selected_cards,
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [],
        "disclaimer": "设备职责来自当前场景方案资料，最终配置需结合样本、通量和厂商参数确认。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }


def build_scenario_result(query: str) -> dict[str, Any] | None:
    scenario = match_scenario(query)
    if scenario is None:
        return None

    steps = []
    equipment_table = []
    for raw_step in scenario.get("steps", []):
        if not isinstance(raw_step, dict):
            continue
        relations = {
            relation: _relation_lines(raw_step, relation)
            for relation in RELATION_ORDER
        }
        steps.append({
            "step_no": raw_step.get("step_no"),
            "name": _compact(raw_step.get("name"), 120),
            "samples": _compact(raw_step.get("samples"), 200),
            "goal": _compact(raw_step.get("goal"), 260),
            "handoff": _compact(raw_step.get("handoff"), 240),
            "role": _compact(raw_step.get("role"), 80),
            "capabilities": _compact(raw_step.get("capabilities"), 180),
            "relations": {key: value for key, value in relations.items() if value},
        })
        equipment_table.extend(_equipment_rows(raw_step))

    plan = {
        "scenario_id": scenario.get("scenario_id"),
        "title": _compact(scenario.get("title"), 140),
        "applications": _compact(scenario.get("applications"), 200),
        "target_customers": _compact(scenario.get("target_customers"), 220),
        "sample_scope": _compact(scenario.get("sample_scope"), 220),
        "steps": steps,
        "equipment_table": equipment_table,
    }
    return {
        "intent": "scenario_plan",
        "answer": f"已匹配《{plan['title']}》。以下给出完整实施路径，方案末尾附有设备明细表；点击产品名称可查看产品介绍。",
        "scenario_plan": plan,
        "recommended_devices": [],
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": [
            "这个方案中各步骤的设备如何选型？",
            "按我的样本类型和通量调整该方案",
            "这个方案的核心设备与替代设备有什么区别？",
        ],
        "disclaimer": "方案内容来自企业场景方案库，仅供科研和技术服务参考。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }
