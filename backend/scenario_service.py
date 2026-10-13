from __future__ import annotations

import re
from typing import Any

from backend.knowledge_catalog import load_scenarios, score_scenario
from backend.local_catalog import get_local_device_detail


REQUEST_MARKERS = ("方案", "流程", "怎么做", "如何做", "如何开展", "全流程", "研究路线")
# Full scenario output is intentionally an explicit, opt-in capability. Keep
# generic how-to questions on the normal graph/product workflow.
SCENARIO_REQUEST_MARKERS = (
    "场景方案", "实施方案", "完整方案", "实验方案", "研究方案",
    "实验流程", "工作流程", "研究路线", "全流程",
)
DETAIL_MARKERS = ("介绍", "详情", "参数", "配置", "报价", "价格", "多少钱")
SCENARIO_TERMS = (
    "中医药", "中医", "四诊", "中药", "临床前", "肿瘤早筛", "伴随诊断", "多光谱", "高光谱", "气味", "异味",
    "生物样本库", "微生物", "酶活", "类器官", "外泌体", "细胞打印", "激光显微切割",
    "微区组学", "植物抗逆", "植物病理", "DNA合成", "基因编辑", "突变体库", "高通量基因合成",
    "合成生物学", "分子育种", "转基因", "空间组学", "空间原位", "细胞治疗", "细胞生产",
    "作物育种", "种子表型", "蛋白互作", "药敏", "小动物体内", "NGS", "建库", "测序",
)
SCENARIO_NAVIGATION_MARKERS = ("场景方案", "方案推荐", "有哪些方案", "有什么方案", "方案有哪些")
PRODUCT_SELECTION_MARKERS = ("推荐", "选型", "产品", "设备", "仪器", "型号")
SCENARIO_TOPIC_ALIASES = {
    "类器官": "S17",
    "类器官研究": "S17",
    "类器官培养": "S17",
    "分子育种": "S07",
    "转基因检测": "S07",
    "单细胞空间组学": "S16",
    "空间转录组": "S16",
    "空间原位": "S16",
    "空间组学": "S16",
    "细胞治疗": "S20",
    "细胞生产": "S20",
    "外泌体": "S21",
    "蛋白互作": "S11",
    "酶活": "S12",
    "生物样本库": "S33",
}
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


def _compact(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


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
        if 'record_ids' in item:
            from backend.scenario_device_rows import reviewed_equipment_row
            rows.append(reviewed_equipment_row(item, step))
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
            "brand": _compact(detail.get("brand_vendor") if detail else inferred_brand, 80),
            "model": _compact(detail.get("product_code"), 80),
            "industrial_code": _compact(detail.get("industrial_code"), 80),
            "technical_specs": _compact("；".join(detail.get("key_specs", [])), 420),
            "applications": _compact(
                detail.get("applications") or detail.get("overview") or description,
                360,
            ),
            "origin": _compact(detail.get("origin") or ("外部过渡设备" if item.get("external") else ""), 40),
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
    for alias, scenario_id_target in SCENARIO_TOPIC_ALIASES.items():
        if alias in query_text and scenario_id == scenario_id_target.casefold():
            score += 260
    # Normalize common user wording to the official scenario vocabulary.
    scenario_source_text = " ".join(
        str(scenario.get(field) or "")
        for field in ("title", "applications", "positioning", "sample_scope")
    ).casefold()
    for query_term, scenario_term in (("药物筛选", "临床前"), ("活体成像", "小动物体内")):
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
    return any(marker in text for marker in DETAIL_MARKERS) and not any(marker in text for marker in REQUEST_MARKERS)


def _should_match_scenario(query: str) -> bool:
    text = (query or "").strip()
    if not text or _is_explicit_device_detail_query(text):
        return False
    # Scenario plans are opt-in. Topic words such as "类器官" or "药敏"
    # should continue through the regular graph workflow unless the user
    # explicitly asks for a plan/process, or names a scenario directly.
    if bool(re.search(r"\bS(?:\d+|-[A-Z0-9]+)\b", text, re.I)):
        return True
    scenario_topic = any(term in text for term in SCENARIO_TERMS)
    explicit_plan_phrase = any(marker in text for marker in SCENARIO_REQUEST_MARKERS)
    if explicit_plan_phrase and scenario_topic:
        return True
    # A named research topic plus "方案" is a direct plan request, unless the
    # user is explicitly asking for product recommendation or equipment choice.
    if scenario_topic and "方案" in text:
        return not any(marker in text for marker in PRODUCT_SELECTION_MARKERS)
    return False


def _is_topic_only_scenario_query(query: str) -> bool:
    text = (query or "").strip()
    if not text or _is_explicit_device_detail_query(text):
        return False
    if any(marker in text for marker in PRODUCT_SELECTION_MARKERS):
        return False
    if any(marker in text for marker in SCENARIO_REQUEST_MARKERS):
        return False
    if "方案" in text:
        return False
    return any(term in text for term in SCENARIO_TOPIC_ALIASES) or any(term in text for term in SCENARIO_TERMS)


def is_scenario_navigation_query(query: str) -> bool:
    """Detect a request to browse plans without selecting a research topic yet."""
    text = (query or "").strip()
    if not text or any(term in text for term in SCENARIO_TERMS):
        return False
    return any(marker in text for marker in SCENARIO_NAVIGATION_MARKERS)


def build_scenario_navigation_result(query: str) -> dict[str, Any] | None:
    if not is_scenario_navigation_query(query):
        return None
    from backend.scenario_selection import option_titles

    return {
        "intent": "scenario_navigation",
        "answer": "有的。当前已收录多个科研场景方案。请选择一个方向，我会继续展示对应的实施步骤和相关产品设备。",
        "recommended_devices": [],
        "need_more_info": ["请选择需要查看的场景方案。"],
        "clarifying_title": "选择场景方案",
        "clarifying_questions": [{
            "id": "scenario_direction",
            "question": "请选择需要查看的场景方案",
            "options": option_titles(),
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


def match_scenario(query: str, allow_topic_only: bool = False) -> dict[str, Any] | None:
    text = (query or "").strip()
    if not _should_match_scenario(text) and not (allow_topic_only and _is_topic_only_scenario_query(text)):
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
    threshold = 18 if allow_topic_only else 16
    return scenario if score >= threshold else None


def _safe_customer_questions(title: str) -> list[str]:
    topic = title.replace("综合方案", "方案").replace("研究方案", "研究")
    return [
        f"查看{topic}的完整场景方案",
        f"我该从{topic}的哪一步开始配置设备？",
        f"按我的样本和通量细化{topic}设备清单",
    ]


def _related_device_cards_from_scenario(scenario: dict[str, Any], query: str = "", limit: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, str]] = []
    query_context = " ".join([
        str(query or ""),
        str(scenario.get("title") or ""),
        str(scenario.get("applications") or ""),
    ])
    blocked_terms = ()
    single_cell_spatial = "单细胞" in query_context and "空间" in query_context
    if single_cell_spatial:
        blocked_terms = ("激光捕获", "激光显微切割", "LCM", "共聚焦", "激光共聚焦")

    for raw_step in scenario.get("steps", []):
        if not isinstance(raw_step, dict):
            continue
        for row in _equipment_rows(raw_step):
            name_text = f"{row.get('name', '')} {row.get('applications', '')} {row.get('description', '')}"
            if any(term in name_text for term in blocked_terms):
                continue
            if row.get("name") and all(row.get("name") != existing.get("name") for existing in rows):
                rows.append(row)
    if single_cell_spatial:
        def priority(row: dict[str, str]) -> int:
            text = f"{row.get('name', '')} {row.get('applications', '')} {row.get('description', '')}"
            score = 0
            for term, weight in (
                ("DEMO-INSTRUMENT-197", 120),
                ("空间组学", 95),
                ("原位", 80),
                ("TissueFAXS", 75),
                ("光谱流式", 50),
                ("Lymacyte", 45),
            ):
                if term in text:
                    score += weight
            for term in ("样本库", "Nesty", "科研数据盒子", "低温"):
                if term in text:
                    score -= 80
            return score
        rows.sort(key=priority, reverse=True)

    cards = []
    for row in rows[:limit]:
        detail = get_local_device_detail(row.get("name", "")) or {}
        cards.append({
            "name": detail.get("name") or row.get("name"),
            "product_code": detail.get("product_code") if detail else row.get("model"),
            "industrial_code": detail.get("industrial_code"),
            "reasons": [
                f"来自《{scenario.get('title')}》场景方案的相关设备",
                row.get("applications") or row.get("description") or "用于支撑该场景的关键流程节点",
            ][:2],
            "capabilities": detail.get("capabilities", []),
            "tasks": detail.get("tasks", []),
            "overview": detail.get("overview") or row.get("description", ""),
            "advantages": detail.get("advantages", ""),
            "applications": detail.get("applications") or row.get("applications", ""),
            "description": row.get("description", ""),
            "matched_reason": f"与《{scenario.get('title')}》场景流程相关",
            "fit_tags": [],
            "selection_notes": ["宽泛场景下先按研究步骤确认样本类型、通量和读出指标，再进入具体型号选型。"],
            "source_pages": [],
            "evidence": [],
        })
    return cards


def build_scenario_guidance_result(query: str) -> dict[str, Any] | None:
    scenario = match_scenario(query, allow_topic_only=True)
    if scenario is None:
        return None

    steps = [
        _compact(step.get("name"), 80)
        for step in scenario.get("steps", [])
        if isinstance(step, dict) and step.get("name")
    ][:5]
    if "单细胞" in query and "空间" in query:
        steps = [
            step for step in steps
            if not any(term in step for term in ("激光", "LCM", "微切割", "微区"))
        ][:5]
    title = _compact(scenario.get("title"), 140)
    chain = " → ".join(steps) if steps else "样本准备 → 检测分析 → 数据解释 → 报告输出"
    return {
        "intent": "scenario_guidance",
        "answer": (
            f"你问的是一个较宽泛的研究方向，我先匹配到《{title}》。"
            f"建议先按完整场景理解，而不是直接随机选单台产品。核心链路可概括为：{chain}。"
            "如果你需要，我可以继续展开完整步骤，或按样本类型、通量和预算收敛到具体设备清单。"
        ),
        "recommended_devices": _related_device_cards_from_scenario(scenario, query=query, limit=4),
        "need_more_info": ["如需精确选型，请补充样本类型、通量规模、检测终点和自动化要求。"],
        "clarifying_questions": [],
        "related_questions": _safe_customer_questions(title),
        "disclaimer": "场景引导用于科研和技术服务沟通，具体设备配置需结合样本、通量、预算和实验终点确认。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }


def build_scenario_result(query: str) -> dict[str, Any] | None:
    # Clinical TCM and herbal chemistry are separate published routes. Resolve
    # them before legacy keyword scoring can send herbal questions back to S1.
    from backend.scenario_names import candidates
    from backend.published_scenarios import reviewed_plan
    matches = candidates(query)
    if len(matches) == 1 and matches[0]['id'] in ('S1', 'topic-02'):
        plan = reviewed_plan(matches[0]['id'])
        if plan:
            return {'intent': 'scenario_plan', 'answer': '《' + plan['title'] + '》',
                    'scenario_plan': plan, 'recommended_devices': [], 'need_more_info': [],
                    'clarifying_questions': [], 'related_questions': [],
                    'generation_source': 'scenario_catalog', 'model_error': ''}
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
            "output": _compact(raw_step.get("output"), 260),
            "boundary": _compact(raw_step.get("boundary"), 260),
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
            f"按我的样本类型和通量调整《{plan['title']}》",
            f"《{plan['title']}》中哪些设备是核心必选？",
            f"基于《{plan['title']}》生成一版采购沟通清单",
        ],
        "disclaimer": "方案内容来自企业场景方案库，仅供科研和技术服务参考。",
        "generation_source": "scenario_catalog",
        "model_error": "",
    }
