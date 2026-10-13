from time import perf_counter

from backend.router import route_intent
from backend.slot_extractor import extract_slots
from backend.hybrid_service import hybrid_recommend
from backend.graph_tools import get_device_detail
from backend.local_catalog import get_local_device_detail
from backend.knowledge_catalog import reviewed_catalog_is_authoritative
from backend.device_name_extractor import extract_device_name
from backend.similar_products import build_similar_workflow_result, is_similar_products_query


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 1)


def run_workflow(user_query: str) -> dict:
    started_at = perf_counter()
    route_started_at = perf_counter()
    intent = route_intent(user_query)
    route_ms = elapsed_ms(route_started_at)
    slot_started_at = perf_counter()
    slots = extract_slots(user_query)
    slot_ms = elapsed_ms(slot_started_at)

    diagnostics = {
        "intent": intent,
        "route_intent_ms": route_ms,
        "slot_extract_ms": slot_ms,
    }

    if is_similar_products_query(user_query):
        result = build_similar_workflow_result(user_query, slots)
        result["diagnostics"] = {
            **diagnostics,
            "workflow_total_ms": elapsed_ms(started_at),
        }
        return result

    if intent == "detail":
        device_name = extract_device_name(user_query)

        if not device_name:
            return {
                "intent": intent,
                "slots": slots,
                "diagnostics": {
                    **diagnostics,
                    "workflow_total_ms": elapsed_ms(started_at),
                },
                "result": {
                    "error": "未识别出明确设备名称"
                }
            }

        detail_started_at = perf_counter()
        local_detail = get_local_device_detail(device_name)
        if local_detail:
            detail = local_detail
        elif reviewed_catalog_is_authoritative():
            detail = {"error": "当前审核产品资料未命中该设备"}
        else:
            try:
                detail = get_device_detail(device_name)
            except Exception as e:
                detail = {
                    "error": "图谱不可用，且本地产品手册未找到该设备",
                    "detail": str(e),
                }
        diagnostics["detail_lookup_ms"] = elapsed_ms(detail_started_at)
        diagnostics["workflow_total_ms"] = elapsed_ms(started_at)
        return {
            "intent": intent,
            "user_query": user_query,
            "slots": slots,
            "diagnostics": diagnostics,
            "result": detail
        }

    if intent == "recommend":
        recommend_started_at = perf_counter()
        result = hybrid_recommend(user_query)
        diagnostics["recommend_workflow_ms"] = elapsed_ms(recommend_started_at)
        diagnostics["workflow_total_ms"] = elapsed_ms(started_at)
        return {
            "intent": intent,
            "user_query": user_query,
            "slots": slots,
            "diagnostics": diagnostics,
            "result": result
        }

    if intent == "compare":
        return {
            "intent": intent,
            "user_query": user_query,
            "slots": slots,
            "diagnostics": {
                **diagnostics,
                "workflow_total_ms": elapsed_ms(started_at),
            },
            "result": {
                "message": "设备对比功能下一步实现。"
            }
        }

    return {
        "intent": intent,
        "user_query": user_query,
        "slots": slots,
        "diagnostics": {
            **diagnostics,
            "workflow_total_ms": elapsed_ms(started_at),
        },
        "result": {}
    }
