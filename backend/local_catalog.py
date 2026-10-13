import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from backend.demand_profile import parse_demand
from backend.knowledge_catalog import load_knowledge_products


RAW_DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_docs"


KEYWORDS = [
    "单细胞",
    "空间组学",
    "原位",
    "组织切片",
    "培养细胞",
    "类器官",
    "高通量",
    "自动化",
    "NGS",
    "测序",
    "建库",
    "蛋白",
    "质谱",
    "外泌体",
    "成像",
    "显微",
    "细胞培养",
    "动物活体",
    "核酸",
    "分子互作",
    "样本库",
]

HIGH_VALUE_TERMS = [
    "活细胞",
    "移液",
    "液体处理",
    "长期培养",
    "文库制备",
    "核酸提取",
    "组织切片",
    "类器官",
]

REQUIRED_CAPABILITY_TERMS = {
    "移液": ["移液", "液体处理", "液体工作站", "分液"],
    "液体处理": ["移液", "液体处理", "液体工作站", "分液"],
}


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def clean_text(text: str) -> str:
    return " ".join(str(text or "").split())


def unique_values(values: list[Any]) -> list[str]:
    result = []
    for value in values:
        item = clean_text(value)
        if item and item not in result:
            result.append(item)
    return result


def product_keys(product: Dict[str, Any]) -> set[str]:
    # Aliases may be generic phrases such as a workflow name, so only canonical
    # names and model codes are safe identity keys for catalog deduplication.
    values = [product.get("name"), product.get("product_code")]
    keys = {compact_text(value) for value in values if len(compact_text(value)) >= 3}

    # Model tokens with a number are sufficiently specific to bridge a manual
    # title and a structured-catalog title without merging generic aliases.
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", str(value or "")):
            if any(char.isdigit() for char in token):
                keys.add(token.casefold())
    return keys


def knowledge_product_to_catalog_item(record: Dict[str, Any]) -> Dict[str, Any]:
    source_pages = record.get("source_pages", [])
    page = source_pages[0] if source_pages else None
    return {
        "name": record.get("name", ""),
        "record_id": record.get("record_id", ""),
        "product_id": record.get("product_id", ""),
        "supplier_name": record.get("supplier_name", ""),
        "brand_name": record.get("brand_name", ""),
        "product_configuration": record.get("product_configuration", ""),
        "product_code": record.get("product_code") or None,
        "page": page,
        "category": record.get("category"),
        "brand_vendor": record.get("brand_vendor", ""),
        "origin": record.get("origin", ""),
        "subcategory": record.get("subcategory", ""),
        "overview": clean_text(record.get("overview")),
        "advantages": clean_text(record.get("advantages", "")),
        "applications": clean_text(record.get("applications", "")),
        "summary": clean_text(record.get("summary", "")),
        "aliases": unique_values(record.get("aliases", [])),
        "capabilities": unique_values(record.get("capabilities", [])),
        "tasks": unique_values(record.get("tasks", [])),
        "sample_types": unique_values(record.get("sample_types", [])),
        "workflow_roles": unique_values(record.get("workflow_roles", [])),
        "automation_level": record.get("automation_level") or "",
        "throughput_level": record.get("throughput_level") or "",
        "scenarios": unique_values(record.get("scenarios", [])),
        "input_materials": unique_values(record.get("input_materials", [])),
        "output_materials": unique_values(record.get("output_materials", [])),
        "key_specs": unique_values(record.get("key_specs", [])),
        "source_files": unique_values(record.get("source_files", [])),
        "source": "knowledge_v2",
    }


def merge_catalog_items(manual: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(manual)
    merged["aliases"] = unique_values(manual.get("aliases", []) + knowledge.get("aliases", []))
    for field in [
        "capabilities",
        "tasks",
        "sample_types",
        "workflow_roles",
        "scenarios",
        "input_materials",
        "output_materials",
        "key_specs",
        "source_files",
    ]:
        manual_values = unique_values(manual.get(field, []))
        merged[field] = manual_values or unique_values(knowledge.get(field, []))

    for field in ["subcategory", "summary", "automation_level", "throughput_level"]:
        if not merged.get(field):
            merged[field] = knowledge.get(field, "")

    for field in ["brand_vendor", "origin"]:
        if not merged.get(field):
            merged[field] = knowledge.get(field, "")

    for field in ["overview", "advantages", "applications", "category", "product_code", "page"]:
        if not merged.get(field):
            merged[field] = knowledge.get(field)

    merged["source"] = "manual_and_knowledge"
    return merged


def infer_tags(item: Dict[str, Any]) -> Dict[str, List[str]]:
    text = " ".join([
        item.get("title", ""),
        item.get("overview", ""),
        item.get("advantages", ""),
        item.get("applications", ""),
    ])
    capabilities = []
    tasks = []

    tag_rules = [
        ("单细胞", "单细胞分析", "单细胞研究"),
        ("空间组学", "空间组学成像", "空间组学研究"),
        ("高通量", "高通量处理", "批量样本处理"),
        ("自动", "自动化处理", "自动化实验流程"),
        ("测序", "测序文库制备", "NGS测序建库"),
        ("建库", "文库制备", "NGS测序建库"),
        ("蛋白", "蛋白分析", "蛋白组学分析"),
        ("质谱", "质谱分析", "质谱检测"),
        ("成像", "成像检测", "成像分析"),
        ("显微", "显微成像", "显微观察"),
        ("细胞培养", "细胞培养", "细胞培养管理"),
        ("外泌体", "外泌体处理", "外泌体研究"),
        ("核酸", "核酸分析", "核酸检测"),
    ]

    for keyword, capability, task in tag_rules:
        if keyword in text:
            if capability not in capabilities:
                capabilities.append(capability)
            if task not in tasks:
                tasks.append(task)

    return {
        "capabilities": capabilities[:5],
        "tasks": tasks[:5],
    }


def infer_product_profile(item: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join([
        item.get("title", ""),
        item.get("overview", ""),
        item.get("advantages", ""),
        item.get("applications", ""),
    ])
    demand_like = parse_demand(text)

    automation_level = "无明确自动化"
    if "全自动" in text or "无人值守" in text:
        automation_level = "全自动"
    elif "半自动" in text:
        automation_level = "半自动"
    elif "自动" in text:
        automation_level = "自动化"

    throughput_level = "未明确"
    if any(keyword in text for keyword in ["高通量", "超高通量", "96", "384", "3000", "批量"]):
        throughput_level = "高通量/批量"
    elif any(keyword in text for keyword in ["24", "中通量"]):
        throughput_level = "中等通量"
    elif any(keyword in text for keyword in ["少量", "单样本"]):
        throughput_level = "低通量/单样本"

    workflow_roles = []
    role_rules = [
        ("样本前处理", ["前处理", "提取", "纯化", "打断", "萃取", "移液", "点样"]),
        ("文库制备", ["建库", "文库制备", "文库构建"]),
        ("检测分析", ["检测", "分析", "质谱", "成像", "显微"]),
        ("细胞培养/生产", ["细胞培养", "换液", "细胞生产", "生物反应器"]),
        ("数据/样本管理", ["样本库", "数据", "管理系统"]),
    ]
    for label, keywords in role_rules:
        if any(keyword in text for keyword in keywords):
            workflow_roles.append(label)

    return {
        "sample_types": demand_like["sample_types"],
        "application_tasks": demand_like["tasks"],
        "automation_level": automation_level,
        "throughput_level": throughput_level,
        "workflow_roles": workflow_roles[:4],
    }


@lru_cache(maxsize=1)
def load_products() -> List[Dict[str, Any]]:
    from backend.knowledge_catalog import reviewed_catalog_is_authoritative
    if reviewed_catalog_is_authoritative():
        # Never refill intentional blanks or merge distinct reviewed rows by fuzzy model.
        return [knowledge_product_to_catalog_item(p) for p in load_knowledge_products()]
    products = []
    for path in RAW_DOCS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, list):
            continue

        for item in data:
            if not isinstance(item, dict):
                continue
            if not item.get("is_product_page") or not item.get("title"):
                continue

            product = {
                "name": item.get("title", ""),
                "product_code": item.get("product_code") or None,
                "page": item.get("page"),
                "category": item.get("category"),
                "overview": clean_text(item.get("overview", "")),
                "advantages": clean_text(item.get("advantages", "")),
                "applications": clean_text(item.get("applications", "")),
            }
            product.update(infer_tags(item))
            product.update(infer_product_profile(item))
            product["aliases"] = []
            product["summary"] = ""
            product["scenarios"] = []
            product["input_materials"] = []
            product["output_materials"] = []
            product["key_specs"] = []
            product["source_files"] = []
            product["source"] = "manual"
            products.append(product)

    key_to_index = {}
    for index, product in enumerate(products):
        for key in product_keys(product):
            key_to_index.setdefault(key, index)

    for record in load_knowledge_products():
        product = knowledge_product_to_catalog_item(record)
        keys = product_keys(product)
        match_index = next((key_to_index[key] for key in keys if key in key_to_index), None)
        if match_index is not None:
            products[match_index] = merge_catalog_items(products[match_index], product)
            for key in product_keys(products[match_index]):
                key_to_index.setdefault(key, match_index)
            continue

        index = len(products)
        products.append(product)
        for key in keys:
            key_to_index.setdefault(key, index)

    return products


def product_text(product: Dict[str, Any]) -> str:
    return " ".join([
        product.get("name", ""),
        product.get("product_code") or "",
        product.get("category") or "",
        product.get("subcategory") or "",
        product.get("summary") or "",
        product.get("overview", ""),
        product.get("advantages", ""),
        product.get("applications", ""),
        " ".join(product.get("aliases", [])),
        " ".join(product.get("capabilities", [])),
        " ".join(product.get("tasks", [])),
        " ".join(product.get("sample_types", [])),
        " ".join(product.get("workflow_roles", [])),
        " ".join(product.get("scenarios", [])),
        " ".join(product.get("input_materials", [])),
        " ".join(product.get("output_materials", [])),
        " ".join(product.get("key_specs", [])),
        product.get("automation_level") or "",
        product.get("throughput_level") or "",
    ])


def score_product(query: str, product: Dict[str, Any]) -> int:
    score, _ = score_product_with_reasons(query, product)
    return score


def score_product_with_reasons(query: str, product: Dict[str, Any]) -> tuple[int, List[str]]:
    demand = parse_demand(query)
    query_compact = compact_text(query)
    name_compact = compact_text(product.get("name", ""))
    text = product_text(product)
    text_compact = compact_text(text)
    score = 0
    reasons = []

    if query_compact and (query_compact in name_compact or name_compact in query_compact):
        score += 80
        reasons.append("产品名称与提问高度匹配")

    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", query):
        if token.casefold() in text_compact:
            score += 35
            reasons.append(f"命中型号/英文关键词：{token}")

    for keyword in KEYWORDS:
        if keyword in query and keyword in text:
            score += 15
            reasons.append(f"命中关键词：{keyword}")

    for keyword in HIGH_VALUE_TERMS:
        if keyword in query and keyword in text:
            score += 22
            reasons.append(f"命中关键应用条件：{keyword}")

    for requirement, supported_terms in REQUIRED_CAPABILITY_TERMS.items():
        if requirement not in query:
            continue
        if any(term in text for term in supported_terms):
            score += 34
            reasons.append(f"满足关键能力：{requirement}")
        else:
            score -= 34

    if any(term in query for term in ["NGS", "建库", "文库制备"]):
        library_terms = ["文库制备", "测序文库制备", "NGS测序建库"]
        if any(term in product.get("workflow_roles", []) for term in library_terms) or any(
            term in product.get("capabilities", []) for term in library_terms
        ):
            score += 36
            reasons.append("匹配文库制备流程角色")

    for capacity in re.findall(r"(?<![A-Za-z])(?:96|384)(?![A-Za-z])", query):
        model_text = f"{product.get('name', '')} {product.get('product_code') or ''}"
        if capacity in model_text:
            score += 28
            reasons.append(f"型号匹配{capacity}样本通量")

    for chunk in re.split(r"[，,。！？!?；;：:\s]+", query):
        chunk = chunk.strip()
        if len(chunk) >= 3 and chunk in text:
            score += 8
            reasons.append(f"命中需求片段：{chunk}")

    product_tasks = product.get("tasks", []) + product.get("application_tasks", [])
    for task in demand["tasks"]:
        if task in product_tasks or task in text:
            score += 35
            reasons.append(f"匹配实验任务：{task}")

    for sample_type in demand["sample_types"]:
        if sample_type in product.get("sample_types", []) or sample_type in text:
            score += 28
            reasons.append(f"适配样本类型：{sample_type}")

    if demand["automation"] and (
        product.get("automation_level") in {"全自动", "自动化", "半自动"}
        or "自动化处理" in product.get("capabilities", [])
    ):
        score += 24
        reasons.append(f"自动化匹配：{product.get('automation_level')}")

    if demand["high_throughput"] and (
        product.get("throughput_level") == "高通量/批量"
        or "高通量处理" in product.get("capabilities", [])
        or "批量样本处理" in product.get("tasks", [])
    ):
        score += 24
        reasons.append("匹配高通量/批量样本处理")

    if demand["resolution"] and any(keyword in text for keyword in ["单细胞", "亚细胞", "高分辨率", "显微", "成像"]):
        score += 20
        reasons.append(f"匹配分辨率需求：{demand['resolution']}")

    query_for_domain = query or ""
    if "单细胞" in query_for_domain and "空间" in query_for_domain:
        primary_terms = ["单细胞", "空间组学", "空间转录组", "空间蛋白", "原位", "组织原位", "DEMO-INSTRUMENT-197"]
        blocked_terms = ["激光捕获", "激光显微切割", "LCM", "共聚焦", "激光共聚焦"]
        if any(term in text for term in primary_terms):
            score += 80
            reasons.insert(0, "匹配单细胞空间组学核心方向")
        if any(term in text for term in blocked_terms) and not any(term in query_for_domain for term in blocked_terms):
            score -= 180
            reasons.insert(0, "排除：当前问题未要求微区切割或共聚焦成像")

    return score, reasons[:6]


def search_local_devices(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    scored = []
    for product in load_products():
        score, reasons = score_product_with_reasons(query, product)
        if score > 0:
            scored.append((score, product, reasons))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "name": item.get("name"),
            "record_id": item.get("record_id"),
            "product_code": item.get("product_code"),
            "industrial_code": item.get("product_id"),
            "brand_vendor": item.get("brand_vendor", ""),
            "supplier_name": item.get("supplier_name", ""),
            "brand_name": item.get("brand_name", ""),
            "key_specs": item.get("key_specs", []),
            "product_configuration": item.get("product_configuration", ""),
            "brochure_url": f"/api/products/brochure?name={item.get('name', '')}",
            "category": item.get("category"),
            "capabilities": item.get("capabilities", []),
            "tasks": item.get("tasks", []),
            "sample_types": item.get("sample_types", []),
            "workflow_roles": item.get("workflow_roles", []),
            "automation_level": item.get("automation_level"),
            "throughput_level": item.get("throughput_level"),
            "overview": item.get("overview", ""),
            "applications": item.get("applications", ""),
            "match_reasons": reasons,
            "local_score": score,
        }
        for score, item, reasons in scored[:limit]
    ]


def find_local_product(device_name: str) -> Dict[str, Any] | None:
    query = compact_text(device_name)
    if not query:
        return None

    products = load_products()
    for product in products:
        if query in {compact_text(product.get(k, "")) for k in ("product_code", "product_id", "record_id")}:
            return product
    for product in products:
        if compact_text(product.get("name", "")) == query:
            return product

    for product in products:
        name = compact_text(product.get("name", ""))
        if query in name or name in query:
            return product

    matches = search_local_devices(device_name, limit=1)
    if not matches:
        return None

    match_name = matches[0]["name"]
    return next((item for item in products if item.get("name") == match_name), None)


def product_evidence(product: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = []
    for section_type, text in [
        ("overview", product.get("overview")),
        ("advantages", product.get("advantages")),
        ("applications", product.get("applications")),
        ("key_specs", "；".join(product.get("key_specs", []))),
        ("product_configuration", product.get("product_configuration")),
        ("brand_vendor", product.get("brand_vendor")),
    ]:
        if not text:
            continue
        evidence.append({
            "chunk_id": f"{product.get('name')}_{product.get('page')}_{section_type}",
            "product_name": product.get("name"),
            "page": product.get("page"),
            "section_type": section_type,
            "text": text,
            "score": None,
        })
    return evidence


def get_local_device_detail(device_name: str) -> Dict[str, Any] | None:
    product = find_local_product(device_name)
    if not product:
        return None

    source_pages = product.get("source_pages", [])
    page = product.get("page")
    return {
        "name": product.get("name"),
        "product_code": product.get("product_code"),
        "industrial_code": product.get("product_id"),
        "record_id": product.get("record_id", ""),
        "supplier_name": product.get("supplier_name", ""),
        "brand_name": product.get("brand_name", ""),
        "product_configuration": product.get("product_configuration", ""),
        "brand_vendor": product.get("brand_vendor", ""),
        "origin": product.get("origin", ""),
        "capabilities": product.get("capabilities", []),
        "tasks": product.get("tasks", []),
        "constraints": [],
        "sample_types": product.get("sample_types", []),
        "workflow_roles": product.get("workflow_roles", []),
        "automation_level": product.get("automation_level"),
        "throughput_level": product.get("throughput_level"),
        "overview": product.get("overview", ""),
        "advantages": product.get("advantages", ""),
        "applications": product.get("applications", ""),
        "key_specs": product.get("key_specs", []),
        "source_files": product.get("source_files", []),
        "source_pages": source_pages if source_pages else ([str(page)] if page else []),
        "brochure_url": f"/api/products/brochure?name={product.get('name', '')}",
        "evidence_chunks": product_evidence(product),
        "source": "local_catalog",
    }


def local_recommend(user_query: str, limit: int = 5, error: str | None = None) -> Dict[str, Any]:
    candidates = search_local_devices(user_query, limit=limit)
    evidence_chunks = []

    for candidate in candidates:
        product = find_local_product(candidate["name"])
        if product:
            evidence_chunks.extend(product_evidence(product)[:2])

    return {
        "user_query": user_query,
        "demand_profile": parse_demand(user_query),
        "candidate_devices": candidates,
        "evidence_chunks": evidence_chunks[:limit],
        "source": "local_catalog",
        "fallback_reason": error,
    }
