from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.demand_profile import parse_demand


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"
PRODUCTS_FILE = DATA_DIR / "products_v2.json"
SCENARIOS_FILE = DATA_DIR / "scenario_solutions_v2.json"


@lru_cache(maxsize=1)
def reviewed_catalog_is_authoritative() -> bool:
    if not PRODUCTS_FILE.exists():
        return False
    payload = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    return payload.get("metadata", {}).get("authoritative_reviewed") is True

RELATION_WEIGHTS = {
    "核心设备": 90,
    "必选设备": 65,
    "可选设备": 35,
    "通用辅助设备": 12,
    "替代设备": 24,
    "前置设备": 12,
    "下游设备": 12,
    "不兼容设备": -120,
}

DOMAIN_TERMS = [
    "单细胞",
    "空间组学",
    "空间转录组",
    "空间蛋白",
    "原位",
    "组织切片",
    "病理玻片",
    "类器官",
    "3D细胞",
    "细胞培养",
    "活细胞",
    "细胞治疗",
    "细胞生产",
    "成像",
    "显微",
    "激光显微切割",
    "微区组学",
    "NGS",
    "建库",
    "测序",
    "DNA",
    "RNA",
    "核酸提取",
    "核酸纯化",
    "基因编辑",
    "基因合成",
    "突变体库",
    "克隆筛选",
    "菌株",
    "微生物",
    "蛋白",
    "蛋白组学",
    "酶活",
    "分子互作",
    "质谱",
    "外泌体",
    "样本库",
    "低温保存",
    "植物",
    "育种",
    "食品",
    "高光谱",
    "自动化",
    "高通量",
    "批量",
    "96孔",
    "384孔",
    "血液",
    "血浆",
    "血清",
    "FFPE",
]


def normalize_text(value: Any) -> str:
    return re.sub(r"[\s\-_/，,；;：:（）()【】\[\]·]+", "", str(value or "")).casefold()


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = re.split(r"[；;、,\n|]+", str(values or ""))
    result = []
    for value in values:
        item = clean_text(value)
        if item and item not in result:
            result.append(item)
    return result


def product_aliases(product: dict[str, Any]) -> list[str]:
    aliases = [
        product.get("name", ""),
        product.get("product_name", ""),
        product.get("display_name", ""),
        product.get("product_code", ""),
        *product.get("aliases", []),
    ]
    return [item for item in unique_strings(aliases) if len(normalize_text(item)) >= 2]


@lru_cache(maxsize=1)
def load_knowledge_products() -> list[dict[str, Any]]:
    if not PRODUCTS_FILE.exists():
        return []
    try:
        payload = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    products = []
    for raw in payload.get("products", []):
        if not isinstance(raw, dict) or not raw.get("product_name"):
            continue
        products.append({
            "record_id": raw.get("record_id"),
            "product_id": raw.get("product_id", ""),
            "supplier_name": clean_text(raw.get("supplier_name")),
            "brand_name": clean_text(raw.get("brand_name")),
            "product_configuration": clean_text(raw.get("product_configuration")),
            "name": clean_text(raw.get("display_name") or raw.get("product_name")),
            "display_name": clean_text(raw.get("display_name") or raw.get("product_name")),
            "product_name": clean_text(raw.get("product_name")),
            "product_code": clean_text(raw.get("product_code")) or None,
            "aliases": unique_strings(raw.get("product_aliases", [])),
            "brand_vendor": clean_text(raw.get("brand_vendor")),
            "origin": clean_text(raw.get("origin")),
            "category": clean_text(raw.get("category")) or "未分类",
            "subcategory": clean_text(raw.get("subcategory")),
            "summary": clean_text(raw.get("one_sentence_summary")),
            "overview": clean_text(raw.get("overview")),
            "advantages": clean_text(raw.get("advantages")),
            "applications": clean_text(raw.get("applications")),
            "limitations": clean_text(raw.get("limitations")),
            "capabilities": unique_strings(raw.get("capabilities", [])),
            "tasks": unique_strings(raw.get("tasks", [])),
            "workflow_roles": unique_strings(raw.get("workflow_roles", [])),
            "automation_level": clean_text(raw.get("automation_level")),
            "throughput_level": clean_text(raw.get("throughput_level")),
            "sample_types": unique_strings(raw.get("sample_types", [])),
            "input_materials": unique_strings(raw.get("input_materials", [])),
            "output_materials": unique_strings(raw.get("output_materials", [])),
            "scenarios": unique_strings(raw.get("scenarios", [])),
            "workflow_steps": unique_strings(raw.get("workflow_steps", [])),
            "upstream_steps": unique_strings(raw.get("upstream_steps", [])),
            "downstream_steps": unique_strings(raw.get("downstream_steps", [])),
            "compatible_devices": unique_strings(raw.get("compatible_devices", [])),
            "alternative_devices": unique_strings(raw.get("alternative_devices", [])),
            "key_specs": unique_strings(raw.get("key_specs", [])),
            "consumables": unique_strings(raw.get("consumables", [])),
            "software_features": unique_strings(raw.get("software_features", [])),
            "lead_questions": unique_strings(raw.get("lead_questions", [])),
            "target_customers": unique_strings(raw.get("target_customers", [])),
            "source_files": unique_strings(raw.get("source_files", [])),
            "source_pages": unique_strings(raw.get("source_pages", [])),
            "evidence_chunks_raw": unique_strings(raw.get("evidence_chunks", [])),
            "confidence_score": raw.get("confidence_score"),
            "review_status": clean_text(raw.get("review_status")),
            "review_notes": clean_text(raw.get("review_notes")),
            "source": "pim_v2",
        })
    return products


@lru_cache(maxsize=1)
def load_scenarios() -> list[dict[str, Any]]:
    if not SCENARIOS_FILE.exists():
        return []
    try:
        payload = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("scenarios", []) if isinstance(item, dict)]


def product_search_text(product: dict[str, Any]) -> str:
    values = [
        *product_aliases(product),
        product.get("brand_vendor", ""),
        product.get("category", ""),
        product.get("subcategory", ""),
        product.get("summary", ""),
        product.get("overview", ""),
        product.get("advantages", ""),
        product.get("applications", ""),
        product.get("limitations", ""),
        product.get("automation_level", ""),
        product.get("throughput_level", ""),
        *product.get("capabilities", []),
        *product.get("tasks", []),
        *product.get("workflow_roles", []),
        *product.get("sample_types", []),
        *product.get("scenarios", []),
        *product.get("workflow_steps", []),
        *product.get("key_specs", []),
    ]
    return " ".join(clean_text(value) for value in values if value)


def query_terms(query: str) -> list[str]:
    terms = [term for term in DOMAIN_TERMS if term.casefold() in (query or "").casefold()]
    terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}", query or ""))
    return unique_strings(terms)


def scenario_text(scenario: dict[str, Any]) -> str:
    values = [
        scenario.get("title", ""),
        scenario.get("applications", ""),
        scenario.get("positioning", ""),
        scenario.get("target_customers", ""),
        scenario.get("sample_scope", ""),
    ]
    for step in scenario.get("steps", []):
        values.extend([
            step.get("name", ""),
            step.get("samples", ""),
            step.get("goal", ""),
            step.get("handoff", ""),
        ])
    return " ".join(values)


def score_scenario(query: str, scenario: dict[str, Any]) -> tuple[int, list[str]]:
    text = scenario_text(scenario)
    score = 0
    reasons = []
    for term in query_terms(query):
        if term.casefold() not in text.casefold():
            continue
        weight = 22 if term in scenario.get("title", "") or term in scenario.get("applications", "") else 10
        score += weight
        reasons.append(term)

    demand = parse_demand(query)
    for task in demand.get("tasks", []):
        task_terms = [term for term in DOMAIN_TERMS if term in task]
        if any(term in text for term in task_terms):
            score += 20
    for sample in demand.get("sample_types", []):
        if sample in text or any(part in text for part in re.split(r"[/／]", sample)):
            score += 14

    return score, unique_strings(reasons)[:5]


def relation_matches_product(item: dict[str, Any], product: dict[str, Any]) -> bool:
    if item.get("external"):
        return False
    if 'record_ids' in item:
        return product.get('record_id') in item['record_ids']
    description = normalize_text(item.get("description", ""))
    if not description:
        return False
    for alias in product_aliases(product):
        key = normalize_text(alias)
        if len(key) >= 3 and key in description:
            return True
    return False


@lru_cache(maxsize=1)
def product_relation_index() -> dict[str, list[dict[str, Any]]]:
    products = load_knowledge_products()
    index: dict[str, list[dict[str, Any]]] = {}
    alias_entries = []
    for product in products:
        record_id = product.get("record_id")
        if not record_id:
            continue
        aliases = {
            normalize_text(alias)
            for alias in product_aliases(product)
            if len(normalize_text(alias)) >= 3
        }
        for alias in aliases:
            alias_entries.append((alias, record_id))

    for scenario in load_scenarios():
        for step in scenario.get("steps", []):
            for relation, items in step.get("relations", {}).items():
                for item in items:
                    if item.get("external"):
                        continue
                    description = normalize_text(item.get("description", ""))
                    matched_ids = set(item['record_ids']) if 'record_ids' in item else {
                        record_id
                        for alias, record_id in alias_entries
                        if alias in description
                    }
                    for record_id in matched_ids:
                        if not record_id:
                            continue
                        index.setdefault(record_id, []).append({
                            "scenario_id": scenario.get("scenario_id"),
                            "scenario_title": scenario.get("title"),
                            "step_no": step.get("step_no"),
                            "step_name": step.get("name"),
                            "relation": relation,
                            "description": item.get("description"),
                        })
    return index


@lru_cache(maxsize=128)
def query_scenario_scores(query: str) -> dict[str, tuple[int, list[str]]]:
    scores = {}
    for scenario in load_scenarios():
        score, terms = score_scenario(query, scenario)
        if score > 0:
            scores[scenario.get("scenario_id", "")] = (score, terms)
    return scores


def scene_matches_for_product(query: str, product: dict[str, Any]) -> list[dict[str, Any]]:
    matches = []
    scenario_scores = query_scenario_scores(query)
    for relation_item in product_relation_index().get(product.get("record_id", ""), []):
        scenario_id = relation_item.get("scenario_id", "")
        if scenario_id not in scenario_scores:
            continue
        scenario_score, scenario_terms = scenario_scores[scenario_id]
        relation = relation_item.get("relation", "")
        matches.append({
            **relation_item,
            "scenario_terms": scenario_terms,
            "score": scenario_score + RELATION_WEIGHTS.get(relation, 0),
        })
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches


def score_knowledge_product(query: str, product: dict[str, Any]) -> tuple[int, list[str], list[dict[str, Any]]]:
    query_key = normalize_text(query)
    text = product_search_text(product)
    text_key = normalize_text(text)
    score = 0
    reasons = []

    for alias in product_aliases(product):
        alias_key = normalize_text(alias)
        if not alias_key:
            continue
        if alias_key == query_key:
            score += 220
            reasons.append("产品名称或型号精确匹配")
            break
        if len(alias_key) >= 3 and alias_key in query_key:
            score += 150
            reasons.append(f"命中产品名称或型号：{alias}")
            break

    for term in query_terms(query):
        if normalize_text(term) in text_key:
            score += 18
            reasons.append(f"匹配需求关键词：{term}")

    demand = parse_demand(query)
    for task in demand.get("tasks", []):
        if any(term in text for term in DOMAIN_TERMS if term in task):
            score += 28
            reasons.append(f"匹配实验任务：{task}")
    for sample in demand.get("sample_types", []):
        if sample in text or any(part in text for part in re.split(r"[/／]", sample)):
            score += 22
            reasons.append(f"适配样本类型：{sample}")

    if demand.get("automation") and any(term in text for term in ["自动化", "全自动", "无人值守"]):
        score += 16
        reasons.append("符合自动化偏好")
    if demand.get("high_throughput") and any(term in text for term in ["高通量", "批量", "96", "384"]):
        score += 16
        reasons.append("符合高通量或批量处理需求")

    scene_matches = scene_matches_for_product(query, product)
    if scene_matches:
        best = scene_matches[0]
        score += best["score"]
        relation = best["relation"]
        reasons.insert(0, f"场景方案中作为{relation}：{best['scenario_title']} / {best['step_name']}")
        if relation == "不兼容设备":
            reasons.insert(0, "场景边界明确标记为不兼容，不建议用于当前步骤")

    return score, unique_strings(reasons)[:6], scene_matches[:4]
