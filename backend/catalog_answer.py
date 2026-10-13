from typing import Any

from backend.local_catalog import load_products
from backend.llm_service import model_config

CATALOG_KEYWORDS = [
    "多少种设备", "多少个设备", "多少设备", "设备数量",
    "多少种产品", "多少个产品", "多少产品", "产品数量",
    "设备目录", "产品目录",
    "有哪些设备", "有哪些产品", "有什么设备", "有什么产品", "都有什么产品", "都有哪些产品",
]


def is_catalog_query(user_query: str) -> bool:
    text = (user_query or "").strip()
    if not text:
        return False
    return any(keyword in text for keyword in CATALOG_KEYWORDS)


def build_catalog_result(user_query: str) -> dict[str, Any]:
    from backend.scenario_selection import option_titles
    products = load_products()
    categories = []
    for product in products:
        category = product.get("category") or "未分类"
        if category not in categories:
            categories.append(category)
    category_text = "、".join(categories[:12])
    sample_names = [product.get("name") for product in products[:8] if product.get("name")]

    answer = "当前产品目录覆盖生命科学仪器、样本处理、细胞、分子、影像、软件平台等方向。"
    if category_text:
        answer += f"主要分类包括：{category_text}。"
    if sample_names:
        answer += " 代表产品包括：" + "、".join(sample_names) + "等。"

    return {
        "intent": "catalog",
        "answer": answer,
        "recommended_devices": [],
        "need_more_info": [],
        "clarifying_questions": [],
        "related_questions": option_titles()[:6],
        "disclaimer": "产品目录仍以审核后的主数据表和正式产品资料为准。",
        "generation_source": "local_catalog",
        "model_name": model_config()["name"],
        "catalog_summary": {
            "categories": categories,
        },
    }
