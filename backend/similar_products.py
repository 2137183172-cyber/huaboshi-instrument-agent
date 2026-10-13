import re
from typing import Any, Dict, List

from backend.local_catalog import (
    KEYWORDS,
    find_local_product,
    load_products,
    product_evidence,
    product_text,
    score_product,
)


SIMILAR_QUERY_PREFIX = "相似产品推荐："

SIMILAR_FOLLOWUP_KEYWORDS = [
    "类似",
    "相似",
    "同类",
    "替代",
    "备选",
    "其他产品",
    "其他类似",
    "还有其他",
    "还有别的",
    "还有吗",
    "换一个",
    "换几款",
]


def is_similar_followup_text(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text or len(text) > 60:
        return False
    return any(keyword in text for keyword in SIMILAR_FOLLOWUP_KEYWORDS)


def build_contextual_similar_query(base_device: str, followup: str, last_query: str | None = None) -> str:
    parts = [
        f"{SIMILAR_QUERY_PREFIX}基准产品「{base_device}」",
        f"用户追问「{(followup or '').strip()}」",
    ]
    if last_query:
        parts.append(f"上一轮需求「{last_query.strip()}」")
    return "；".join(parts)


def is_similar_products_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    return text.startswith(SIMILAR_QUERY_PREFIX)


def parse_similar_query(user_query: str) -> Dict[str, str]:
    text = (user_query or "").strip()

    def extract(label: str) -> str:
        match = re.search(rf"{label}「([^」]+)」", text)
        return match.group(1).strip() if match else ""

    return {
        "base_device": extract("基准产品"),
        "followup": extract("用户追问"),
        "last_query": extract("上一轮需求"),
    }


def _shared_values(base: Dict[str, Any], candidate: Dict[str, Any], field: str) -> List[str]:
    base_values = [x for x in base.get(field, []) if x]
    candidate_values = [x for x in candidate.get(field, []) if x]
    return [x for x in candidate_values if x in base_values]


def _similarity_score(base: Dict[str, Any], candidate: Dict[str, Any], context_query: str) -> int:
    score = 0

    if candidate.get("category") and candidate.get("category") == base.get("category"):
        score += 35

    shared_tasks = _shared_values(base, candidate, "tasks")
    shared_capabilities = _shared_values(base, candidate, "capabilities")
    score += len(shared_tasks) * 18
    score += len(shared_capabilities) * 16

    base_text = product_text(base)
    candidate_text = product_text(candidate)
    for keyword in KEYWORDS:
        if keyword in base_text and keyword in candidate_text:
            score += 6

    if context_query:
        score += score_product(context_query, candidate)

    return score


def find_similar_products(base_device: str, context_query: str = "", limit: int = 5) -> List[Dict[str, Any]]:
    base_product = find_local_product(base_device)
    if not base_product:
        return []

    scored = []
    base_name = base_product.get("name")
    for candidate in load_products():
        if candidate.get("name") == base_name:
            continue

        score = _similarity_score(base_product, candidate, context_query)
        if score <= 0:
            continue
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)

    results = []
    for score, product in scored[:limit]:
        results.append({
            "name": product.get("name"),
            "product_code": product.get("product_code"),
            "category": product.get("category"),
            "capabilities": product.get("capabilities", []),
            "tasks": product.get("tasks", []),
            "overview": product.get("overview", ""),
            "advantages": product.get("advantages", ""),
            "applications": product.get("applications", ""),
            "similarity_score": score,
        })
    return results


def build_similar_workflow_result(user_query: str, slots: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = parse_similar_query(user_query)
    base_device = context.get("base_device", "")
    context_query = " ".join([context.get("last_query", ""), context.get("followup", "")]).strip()
    base_product = find_local_product(base_device)

    if not base_product:
        return {
            "intent": "similar",
            "user_query": user_query,
            "slots": slots or {},
            "result": {
                "error": "未找到上一轮基准产品，无法检索类似产品",
                "base_device": base_device,
                "candidate_devices": [],
                "evidence_chunks": [],
            },
        }

    candidates = find_similar_products(base_device, context_query=context_query, limit=5)
    evidence_chunks = []
    for candidate in candidates:
        product = find_local_product(candidate.get("name", ""))
        if product:
            evidence_chunks.extend(product_evidence(product)[:2])

    return {
        "intent": "similar",
        "user_query": user_query,
        "slots": slots or {},
        "result": {
            "base_device": base_product.get("name"),
            "base_category": base_product.get("category"),
            "base_tasks": base_product.get("tasks", []),
            "base_capabilities": base_product.get("capabilities", []),
            "context_query": context_query,
            "candidate_devices": candidates,
            "evidence_chunks": evidence_chunks,
            "source": "local_catalog",
        },
    }
