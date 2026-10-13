from time import perf_counter

from backend.graph_tools import (
    find_devices_by_task,
    find_devices_by_capability,
    find_devices_by_constraint,
    search_devices_fallback,
)
from backend.local_catalog import local_recommend
from backend.knowledge_catalog import reviewed_catalog_is_authoritative
from backend.reviewed_graph import enrich_recommendation
from backend.rag.retriever import retrieve_chunks


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 1)


def is_broad_capability_query(user_query: str) -> bool:
    text = user_query or ""
    capability_hits = sum(1 for keyword in ["高通量", "自动化", "批量", "样本", "处理"] if keyword in text)
    specific_hits = sum(1 for keyword in ["单细胞", "空间组学", "NGS", "建库", "测序", "蛋白", "细胞培养", "外泌体", "质谱"] if keyword in text)
    return capability_hits >= 3 and specific_hits == 0


def hybrid_recommend(user_query: str) -> dict:
    """
    最小版混合检索：
    1. 先用图谱找候选设备
    2. 再针对候选设备查文档证据
    3. 返回结构化结果给大模型
    """

    started_at = perf_counter()
    diagnostics = {
        "retrieval_source": "neo4j_rag",
    }

    # This catalog includes manual entries and the expanded structured records.
    local_started_at = perf_counter()
    local_result = local_recommend(user_query, limit=5)
    diagnostics["local_catalog_ms"] = elapsed_ms(local_started_at)

    if reviewed_catalog_is_authoritative():
        # Only a graph with the exact current product AND scenario fingerprint is usable.
        used_graph = enrich_recommendation(user_query, local_result)
        diagnostics["retrieval_source"] = "reviewed_neo4j_graph" if used_graph else "reviewed_product_knowledge"
        diagnostics["retrieval_total_ms"] = elapsed_ms(started_at)
        local_result["diagnostics"] = diagnostics
        return local_result

    if is_broad_capability_query(user_query):
        diagnostics["retrieval_source"] = "local_catalog_fast"
        diagnostics["retrieval_total_ms"] = elapsed_ms(started_at)
        local_result["diagnostics"] = diagnostics
        local_result["fast_reason"] = "broad_capability_query"
        return local_result

    # 先做一个很简单的规则路由，后面再换成 LangGraph
    candidates = []

    candidate_started_at = perf_counter()
    try:
        # 任务类关键词
        if "单细胞" in user_query or "空间组学" in user_query:
            candidates = find_devices_by_task("单细胞")
            if not candidates:
                candidates = find_devices_by_task("空间")
        elif "NGS" in user_query or "建库" in user_query or "测序" in user_query:
            candidates = find_devices_by_task("测序")
            if not candidates:
                candidates = find_devices_by_task("建库")
        elif "高通量" in user_query:
            candidates = find_devices_by_capability("高通量")
        elif "自动化" in user_query:
            candidates = find_devices_by_capability("自动化")
        else:
            # 兜底：模糊设备名/关键词搜索
            candidates = search_devices_fallback(user_query)
    except Exception as e:
        diagnostics["candidate_lookup_ms"] = elapsed_ms(candidate_started_at)
        diagnostics["retrieval_source"] = "local_catalog"
        diagnostics["neo4j_error"] = str(e)
        diagnostics["retrieval_total_ms"] = elapsed_ms(started_at)
        local_result["fallback_reason"] = str(e)
        local_result["diagnostics"] = diagnostics
        return local_result

    diagnostics["candidate_lookup_ms"] = elapsed_ms(candidate_started_at)

    # Use the expanded local catalog as the primary ranking. Neo4j-only
    # candidates are retained as supplementary results.
    merged_candidates = []
    seen_names = set()
    for candidate in local_result.get("candidate_devices", []) + candidates:
        name = str(candidate.get("name") or "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        merged_candidates.append(candidate)
    candidates = merged_candidates[:5]
    product_names = [x["name"] for x in candidates if x.get("name")]

    # 针对候选设备做 RAG 检索
    rag_started_at = perf_counter()
    try:
        evidence_chunks = retrieve_chunks(
            query_text=user_query,
            product_names=product_names,
            top_k=5
        )
    except Exception as e:
        diagnostics["rag_retrieval_ms"] = elapsed_ms(rag_started_at)
        diagnostics["retrieval_source"] = "local_catalog"
        diagnostics["rag_error"] = str(e)
        diagnostics["retrieval_total_ms"] = elapsed_ms(started_at)
        local_result["diagnostics"] = diagnostics
        local_result["candidate_devices"] = candidates or local_result["candidate_devices"]
        local_result["fallback_reason"] = str(e)
        return local_result

    diagnostics["rag_retrieval_ms"] = elapsed_ms(rag_started_at)
    diagnostics["retrieval_total_ms"] = elapsed_ms(started_at)

    return {
        "user_query": user_query,
        "candidate_devices": candidates,
        "evidence_chunks": (local_result.get("evidence_chunks", []) + evidence_chunks)[:8],
        "diagnostics": diagnostics,
    }
