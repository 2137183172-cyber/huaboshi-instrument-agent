import json
import os
import copy
from time import perf_counter
from collections import OrderedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from backend.state import AgentState
from backend.router import route_intent
from backend.slot_extractor import extract_slots
from backend.workflow import run_workflow
from backend.catalog_answer import build_catalog_result, is_catalog_query
from backend.agent import (
    build_fallback_answer,
    build_fit_tags,
    build_selection_notes,
    build_source_pages,
    normalize_evidence_items,
    normalize_result,
)
from backend.llm_service import generate_json, model_config
from backend.product_publication import public_payload, reviewed_fact_answer
from backend.price_lead import build_price_lead_result, is_price_query
from backend.query_guard import build_uninformative_query_result, is_uninformative_query
from backend.scenario_service import build_scenario_guidance_result, build_scenario_navigation_result, build_scenario_result

load_dotenv()
RESULT_CACHE_MAX = int(os.getenv("RESULT_CACHE_MAX", "128"))
RESULT_CACHE: OrderedDict[str, dict] = OrderedDict()
LLM_CANDIDATE_LIMIT = max(1, int(os.getenv("LLM_PROMPT_CANDIDATE_LIMIT", "3")))
LLM_EVIDENCE_LIMIT = max(1, int(os.getenv("LLM_PROMPT_EVIDENCE_LIMIT", "6")))
LLM_EVIDENCE_TEXT_LIMIT = max(80, int(os.getenv("LLM_PROMPT_EVIDENCE_TEXT_LIMIT", "320")))


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 1)


def collect_workflow_diagnostics(workflow_result: dict) -> dict:
    diagnostics = {}
    if isinstance(workflow_result.get("diagnostics"), dict):
        diagnostics.update(workflow_result["diagnostics"])

    result = workflow_result.get("result", {})
    if isinstance(result, dict) and isinstance(result.get("diagnostics"), dict):
        diagnostics.update(result["diagnostics"])

    return diagnostics


def attach_diagnostics(result: dict, diagnostics: dict) -> dict:
    existing = result.get("diagnostics", {})
    if not isinstance(existing, dict):
        existing = {}
    result["diagnostics"] = {
        **existing,
        **diagnostics,
    }
    return result


def compact_text(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def compact_string_list(value, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact_text(item, 100) for item in value if str(item).strip()][:limit]


def compact_workflow_for_llm(workflow_result: dict) -> dict:
    """Keep ranking evidence while removing verbose fields the model must not regenerate."""
    raw_result = workflow_result.get("result", {})
    if not isinstance(raw_result, dict):
        raw_result = {}

    raw_candidates = raw_result.get("candidate_devices", [])
    if not raw_candidates and raw_result.get("name"):
        # Detail queries return a single device rather than a ranked candidate list.
        raw_candidates = [raw_result]

    candidates = []
    for item in raw_candidates[:LLM_CANDIDATE_LIMIT]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        candidates.append({
            "name": item.get("name"),
                "product_code": item.get("product_code"),
                "brand_vendor": item.get("brand_vendor", ""),
                "supplier_name": item.get("supplier_name", ""),
                "brand_name": item.get("brand_name", ""),
                "key_specs": compact_string_list(item.get("key_specs"), 8),
                "product_configuration": compact_text(item.get("product_configuration"), 500),
                "brochure_url": item.get("brochure_url"),
            "category": item.get("category"),
            "capabilities": compact_string_list(item.get("capabilities"), 5),
            "tasks": compact_string_list(item.get("tasks"), 5),
            "sample_types": compact_string_list(item.get("sample_types"), 4),
            "match_reasons": compact_string_list(item.get("match_reasons"), 4),
            "automation_level": item.get("automation_level"),
            "throughput_level": item.get("throughput_level"),
            "overview": compact_text(item.get("overview"), 220),
            "applications": compact_text(item.get("applications"), 260),
        })

    evidence = []
    for item in raw_result.get("evidence_chunks", [])[:LLM_EVIDENCE_LIMIT]:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        evidence.append({
            "product_name": item.get("product_name"),
            "page": item.get("page"),
            "score": item.get("score"),
            "text": compact_text(item.get("text"), LLM_EVIDENCE_TEXT_LIMIT),
        })

    compact_result = {
        "base_device": raw_result.get("base_device"),
        "base_category": raw_result.get("base_category"),
        "candidate_devices": candidates,
        "evidence_chunks": evidence,
    }
    return {
        "intent": workflow_result.get("intent", "recommend"),
        "user_query": compact_text(workflow_result.get("user_query"), 500),
        "slots": workflow_result.get("slots", {}),
        "result": compact_result,
    }


def build_grounded_llm_prompt(workflow_result: dict) -> str:
    payload = public_payload(compact_workflow_for_llm(workflow_result))
    return f"""
你是华博士，生物产品选型顾问。只根据给定候选和证据回答，不得新增产品或参数。
产品详情、证据和参数由系统确定，你只负责生成简洁专业的结论、推荐理由和追问。

仅输出 JSON：
{{
  "answer": "先给结论，再用简洁自然语言说明依据",
  "recommended_devices": [
    {{"name": "必须逐字选自候选名称", "reasons": ["2到4条理由"], "matched_reason": "一句命中说明"}}
  ],
  "need_more_info": [],
  "clarifying_questions": [{{"id": "字段名", "question": "问题", "options": ["短选项"]}}],
  "related_questions": ["最多3条"]
}}

规则：
1. 先直接回答用户正在问的对象，再给出选型结论；用户问“适合哪些样本”时，必须先列出候选资料明确支持的样本类型，不要改答设备介绍。
2. 需求明确时最多推荐3个候选；已有候选产品时先展示产品，不要额外追问。仅当用户明确要求推荐或选型、但缺少实验任务时，才提出1个产品方向追问；选项必须互斥且可由当前产品目录回答。
3. similar 意图必须排除 base_device，只从 candidate_devices 选择。
4. 理由必须能由候选标签或 evidence_chunks 支撑，不得暴露内部评分字段。
5. answer 控制在300字内，理由每条控制在60字内。
6. 缺失字段显示“-”，不能猜测或把其他字段充作缺失字段。产品编号、产业编号、记录键和库内产品数量均不向客户展示；型号不等于编号，可以展示。内部参考报价不得输出。来源厂家/供货单位不能自动认定为制造商。

输入：
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
""".strip()


def find_grounded_device(devices: list[dict], name: str) -> dict | None:
    normalized = " ".join((name or "").split()).casefold()
    if not normalized:
        return None
    for item in devices:
        candidate = " ".join(str(item.get("name") or "").split()).casefold()
        if candidate == normalized:
            return item
    for item in devices:
        candidate = " ".join(str(item.get("name") or "").split()).casefold()
        if normalized in candidate or candidate in normalized:
            return item
    return None


def merge_grounded_model_result(model_result: dict, fallback: dict) -> dict:
    """Accept model prose only; retain all product facts from the grounded fallback."""
    merged = copy.deepcopy(fallback)
    if not isinstance(model_result, dict):
        return merged

    answer = model_result.get("answer")
    if isinstance(answer, str) and answer.strip():
        merged["answer"] = compact_text(answer, 1200)

    for key in ["need_more_info", "clarifying_questions", "related_questions"]:
        value = model_result.get(key)
        if isinstance(value, list):
            merged[key] = value

    if isinstance(model_result.get("recommended_devices"), list):
        grounded_devices = fallback.get("recommended_devices", [])
        selected = []
        for model_device in model_result["recommended_devices"][:3]:
            if not isinstance(model_device, dict):
                continue
            grounded = find_grounded_device(grounded_devices, str(model_device.get("name") or ""))
            if grounded is None:
                continue
            device = copy.deepcopy(grounded)
            reasons = model_device.get("reasons")
            if isinstance(reasons, list):
                clean_reasons = [compact_text(item, 120) for item in reasons if str(item).strip()][:4]
                if clean_reasons:
                    device["reasons"] = clean_reasons
            matched_reason = model_device.get("matched_reason")
            if isinstance(matched_reason, str) and matched_reason.strip():
                device["matched_reason"] = compact_text(matched_reason, 180)
            selected.append(device)
        if selected or not model_result["recommended_devices"]:
            merged["recommended_devices"] = selected

    return normalize_result(merged)


def get_cached_result(cache_key: str) -> dict | None:
    result = RESULT_CACHE.get(cache_key)
    if result is None:
        return None
    RESULT_CACHE.move_to_end(cache_key)
    cached = copy.deepcopy(result)
    cached["cached"] = True
    return cached


def set_cached_result(cache_key: str, result: dict) -> None:
    if result.get("answer", "").startswith("知识图谱或文档检索服务暂时不可用"):
        return

    cached = copy.deepcopy(result)
    cached.pop("diagnostics", None)
    RESULT_CACHE[cache_key] = cached
    RESULT_CACHE.move_to_end(cache_key)
    while len(RESULT_CACHE) > RESULT_CACHE_MAX:
        RESULT_CACHE.popitem(last=False)


def route_node(state: AgentState) -> AgentState:
    user_query = state["user_query"]
    state["intent"] = route_intent(user_query)
    return state


def slot_node(state: AgentState) -> AgentState:
    user_query = state["user_query"]
    state["slots"] = extract_slots(user_query)
    return state


def workflow_node(state: AgentState) -> AgentState:
    user_query = state["user_query"]
    started_at = perf_counter()
    try:
        state["workflow_result"] = run_workflow(user_query)
    except Exception as e:
        state["error"] = str(e)
        state["workflow_result"] = {
            "intent": state.get("intent", "recommend"),
            "slots": state.get("slots", {}),
            "result": {
                "error": "知识图谱或文档检索服务暂时不可用",
                "detail": str(e),
            },
        }
    diagnostics = state["workflow_result"].setdefault("diagnostics", {})
    if isinstance(diagnostics, dict):
        diagnostics["workflow_node_ms"] = elapsed_ms(started_at)
    return state


def build_detail_result_from_workflow(workflow_result: dict) -> dict:
    result = workflow_result.get("result", {})

    if result.get("error"):
        return normalize_result({
            "intent": "detail",
            "answer": "未找到明确设备，请提供更完整的设备名称。",
            "recommended_devices": [],
            "need_more_info": ["请提供设备完整名称。"],
            "related_questions": [],
            "disclaimer": "内容由AI生成，仅供参考。"
        })

    overview = result.get("overview") or ""
    advantages = result.get("advantages") or ""
    applications = result.get("applications") or ""

    description_parts = [
        "【产品简介】" + (overview or "-"),
        "【产品优势】" + (advantages or "-"),
        "【应用场景】" + (applications or "-"),
    ]
    full_description = "\n\n".join(description_parts)
    evidence = normalize_evidence_items(result.get("evidence_chunks", []))

    answer = f"可以，下面是《{result.get('name')}》的产品介绍。"
    if overview:
        answer += " " + overview[:150].rstrip() + ("..." if len(overview) > 150 else "")

    return normalize_result({
        "intent": "detail",
        "answer": answer,
        "recommended_devices": [
            {
                "name": result.get("name"),
                "product_code": result.get("product_code"),
                "industrial_code": result.get("industrial_code") or result.get("product_code"),
                "brochure_url": result.get("brochure_url"),
                "reasons": ["该设备已在图谱和文档中命中，可查看完整详情。"],
                "capabilities": [x for x in result.get("capabilities", []) if x],
                "tasks": [x for x in result.get("tasks", []) if x],
                "overview": overview,
                "advantages": advantages,
                "applications": applications,
                "description": full_description,
                "matched_reason": "该设备名称已明确命中图谱与产品详情。",
                "fit_tags": build_fit_tags(result),
                "selection_notes": build_selection_notes(result),
                "source_pages": build_source_pages(evidence),
                "evidence": evidence
            }
        ],
        "need_more_info": [],
        "related_questions": ["这台设备适合哪些样本？", "这台设备和其他方案有什么区别？"],
        "disclaimer": "内容由AI生成，仅供参考。",
        "generation_source": "fallback",
        "model_name": model_config()["name"],
    })


def merge_detail_defaults(model_result: dict, fallback: dict) -> dict:
    fallback_devices = fallback.get("recommended_devices", [])
    model_devices = model_result.get("recommended_devices", [])
    if not fallback_devices or not model_devices:
        return model_result

    defaults = fallback_devices[0]
    device = model_devices[0]
    if not isinstance(device, dict):
        return model_result

    for key in [
        "name",
        "product_code",
        "industrial_code",
        "brochure_url",
        "capabilities",
        "tasks",
        "overview",
        "advantages",
        "applications",
        "matched_reason",
        "fit_tags",
        "selection_notes",
        "source_pages",
        "evidence",
    ]:
        if not device.get(key):
            device[key] = defaults.get(key)

    return model_result


def build_service_error_result(workflow_result: dict) -> dict:
    result = workflow_result.get("result", {})
    detail = result.get("detail", "")
    return normalize_result({
        "intent": workflow_result.get("intent", "recommend"),
        "answer": "知识图谱或文档检索服务暂时不可用，暂时无法完成产品匹配。请确认 Neo4j 已启动并且连接配置正确。",
        "recommended_devices": [],
        "need_more_info": ["请先启动 Neo4j 服务，或检查 NEO4J_URI、用户名和密码配置。"],
        "related_questions": ["如何启动 Neo4j？", "如何检查图谱连接配置？"],
        "disclaimer": detail or "内容由AI生成，仅供参考。",
        "generation_source": "fallback",
        "model_name": model_config()["name"],
        "model_error": detail,
    })


def answer_node(state: AgentState) -> AgentState:
    answer_started_at = perf_counter()
    user_query = state["user_query"]
    workflow_result = state["workflow_result"]
    diagnostics = collect_workflow_diagnostics(workflow_result)

    if workflow_result.get("result", {}).get("error") == "知识图谱或文档检索服务暂时不可用":
        result = build_service_error_result(workflow_result)
        state["final_result"] = attach_diagnostics(result, {
            **diagnostics,
            "llm_generation_ms": 0,
            "answer_build_ms": elapsed_ms(answer_started_at),
        })
        return state

    fallback = normalize_result(build_fallback_answer(user_query, workflow_result))
    fallback["generation_source"] = "fallback"
    fallback["model_name"] = model_config()["name"]
    prompt = build_grounded_llm_prompt(workflow_result)
    model_settings = model_config()
    llm_started_at = perf_counter()
    model_result, error = generate_json(prompt)
    diagnostics["llm_generation_ms"] = elapsed_ms(llm_started_at)
    diagnostics["llm_prompt_chars"] = len(prompt)
    diagnostics["llm_output_mode"] = "compact_grounded"
    diagnostics["llm_timeout_seconds"] = model_settings.get("timeout_seconds")
    diagnostics["llm_max_retries"] = model_settings.get("max_retries")
    if model_result:
        result = merge_grounded_model_result(model_result, fallback)
        result["generation_source"] = "llm"
        result["model_name"] = model_settings["name"]
        state["final_result"] = attach_diagnostics(result, {
            **diagnostics,
            "answer_build_ms": elapsed_ms(answer_started_at),
        })
    else:
        fallback["model_error"] = error or "model returned empty output"
        state["error"] = fallback["model_error"]
        state["final_result"] = attach_diagnostics(fallback, {
            **diagnostics,
            "answer_build_ms": elapsed_ms(answer_started_at),
        })

    return state


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("route", route_node)
    graph.add_node("slot", slot_node)
    graph.add_node("workflow", workflow_node)
    graph.add_node("answer", answer_node)

    graph.set_entry_point("route")
    graph.add_edge("route", "slot")
    graph.add_edge("slot", "workflow")
    graph.add_edge("workflow", "answer")
    graph.add_edge("answer", END)

    return graph.compile()


app_graph = build_graph()


def run_graph_workflow(user_query: str) -> dict:
    started_at = perf_counter()

    def finish(result: dict, route: str, cache_hit: bool = False) -> dict:
        diagnostics = {
            "graph_route": route,
            "cache_hit": cache_hit,
            "graph_total_ms": elapsed_ms(started_at),
        }
        if route in {"catalog", "price_lead", "scenario_plan", "scenario_guidance", "scenario_navigation", "uninformative_guard", "cache"}:
            diagnostics["llm_generation_ms"] = 0
        return attach_diagnostics(result, diagnostics)

    cache_key = " ".join((user_query or "").split())
    if is_catalog_query(user_query):
        return finish(build_catalog_result(user_query), "catalog")

    if is_price_query(user_query):
        return finish(build_price_lead_result(user_query), "price_lead")

    fact_answer = reviewed_fact_answer(user_query)
    if fact_answer:
        return finish(fact_answer, "reviewed_product_fields")

    scenario_result = build_scenario_result(user_query)
    if scenario_result:
        return finish(scenario_result, "scenario_plan")

    scenario_guidance = build_scenario_guidance_result(user_query)
    if scenario_guidance:
        return finish(scenario_guidance, "scenario_guidance")

    scenario_navigation = build_scenario_navigation_result(user_query)
    if scenario_navigation:
        return finish(scenario_navigation, "scenario_navigation")

    if is_uninformative_query(user_query):
        return finish(build_uninformative_query_result(user_query), "uninformative_guard")

    if cache_key:
        cached = get_cached_result(cache_key)
        if cached:
            return finish(cached, "cache", cache_hit=True)

    state = app_graph.invoke({"user_query": user_query})
    result = state["final_result"]
    finish(result, "langgraph")
    if cache_key:
        set_cached_result(cache_key, result)
    return result
