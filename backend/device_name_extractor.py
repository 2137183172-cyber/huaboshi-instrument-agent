import json
import os
import re
from functools import lru_cache
from pathlib import Path

from backend.graph_tools import search_devices_fallback
from backend.local_catalog import search_local_devices
from backend.knowledge_catalog import load_knowledge_products, reviewed_catalog_is_authoritative


TRAILING_PUNCTUATION = " \t\r\n。！？!?；;，,、：:）)]】》\"'“”‘’"
ALIAS_FILE = Path(__file__).resolve().parent.parent / "data" / "device_aliases.json"
GENERIC_PARAMETER_WORDS = [
    "关注",
    "具体",
    "多少",
    "分辨率",
    "空间分辨率",
    "通量",
    "预算",
    "样本",
    "数量",
    "自动化",
    "价格",
    "报价",
]


def normalize_name(text: str) -> str:
    text = (text or "").strip()
    prefixes = ["智莓华科", "智荟华科", "SynergiTech", "ynergiTech"]
    for p in prefixes:
        if text.startswith(p):
            text = text[len(p):].strip()
    return text


def clean_query_text(text: str) -> str:
    cleaned = normalize_name(text)

    prefixes = ["介绍一下", "介绍", "说说", "查看", "看看", "详情", "这个设备", "这台设备", "帮我看看", "我想了解"]
    for p in prefixes:
        cleaned = cleaned.replace(p, "").strip()

    suffixes = ["的详情", "详情", "是什么", "做什么", "的介绍", "介绍"]
    for s in suffixes:
        if cleaned.endswith(s):
            cleaned = cleaned[: -len(s)].strip()

    return normalize_name(cleaned).strip(TRAILING_PUNCTUATION)


def normalize_lookup_key(text: str) -> str:
    cleaned = clean_query_text(text)
    return re.sub(r"\s+", "", cleaned).casefold()


def infer_aliases(canonical_name: str) -> list[str]:
    aliases = []

    def add(value: str) -> None:
        value = clean_query_text(value)
        if value and value not in aliases:
            aliases.append(value)

    add(canonical_name)

    for sep in ["-", "－", "—"]:
        if sep in canonical_name:
            left, right = canonical_name.split(sep, 1)
            add(left)
            add(right)
            for part in re.split(r"[/／、,，]", right):
                add(part)

    # 连在中文后的英文型号，例如 全自动...DEMO-INSTRUMENT-077。
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", canonical_name):
        add(token)

    return aliases


@lru_cache(maxsize=1)
def load_alias_map() -> dict[str, str]:
    if reviewed_catalog_is_authoritative():
        alias_map = {}
        for p in load_knowledge_products():
            for alias in [p['name'], p.get('product_code'), p.get('product_id'), *p.get('aliases',[])]:
                if alias:
                    alias_map.setdefault(normalize_lookup_key(alias), p['name'])
        return alias_map
    if not ALIAS_FILE.exists():
        return {}

    try:
        records = json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    alias_map = {}
    if not isinstance(records, list):
        return alias_map

    for record in records:
        if not isinstance(record, dict):
            continue

        canonical = clean_query_text(record.get("canonical", ""))
        if not canonical:
            continue

        aliases = []
        raw_aliases = record.get("aliases", [])
        if isinstance(raw_aliases, list):
            aliases.extend(str(x) for x in raw_aliases if x)

        aliases.extend(infer_aliases(canonical))

        for alias in aliases:
            key = normalize_lookup_key(alias)
            if key:
                alias_map[key] = canonical

    return alias_map


def find_alias_match(candidate: str) -> str | None:
    key = normalize_lookup_key(candidate)
    if not key:
        return None

    alias_map = load_alias_map()
    if key in alias_map:
        return alias_map[key]

    for alias_key, canonical in alias_map.items():
        if key in alias_key or alias_key in key:
            return canonical

    return None


def build_name_candidates(text: str) -> list[str]:
    cleaned = clean_query_text(text)
    candidates = []

    def add(value: str) -> None:
        value = clean_query_text(value)
        if value and value not in candidates:
            candidates.append(value)

    add(cleaned)

    for sep in ["-", "－", "—", "_", "（", "(", "《", "》", "，", ",", "。", "；", ";", "：", ":"]:
        for part in cleaned.split(sep):
            add(part)

    # 英文型号通常是最稳定的别名，例如 DEMO-INSTRUMENT-197。
    token = ""
    for ch in cleaned:
        if ch.isascii() and (ch.isalnum() or ch in ["-", "_"]):
            token += ch
        else:
            add(token)
            token = ""
    add(token)

    return candidates


def looks_like_model_token(text: str) -> bool:
    token = (text or "").strip()
    if len(token) < 3:
        return False
    if not re.search(r"[A-Za-z]", token):
        return False
    return bool(re.search(r"\d", token) or re.search(r"[A-Z][a-z]+[A-Z]", token))


def is_unsafe_fuzzy_candidate(candidate: str) -> bool:
    text = (candidate or "").strip()
    if not text:
        return True
    if len(text) <= 2:
        return True
    if any(word in text for word in GENERIC_PARAMETER_WORDS):
        return True
    if re.fullmatch(r"[<>=≤≥~约大于小于以内以上\s\d.]+(?:nm|um|μm|mm|cm|ml|ul|μl|孔|个|台|万)?", text, re.I):
        return True
    return False


def extract_device_name(user_query: str) -> str | None:
    for candidate in build_name_candidates(user_query):
        alias_match = find_alias_match(candidate)
        if alias_match:
            return alias_match

        if is_unsafe_fuzzy_candidate(candidate):
            continue

        matches = search_local_devices(candidate, limit=5)
        if not matches and os.getenv("ENABLE_NEO4J_NAME_LOOKUP", "false").strip().lower() in {"1", "true", "yes"}:
            try:
                matches = search_devices_fallback(candidate)
            except Exception:
                matches = []

        if not matches:
            continue

        # 优先精确匹配（归一化后）
        for item in matches:
            name = normalize_name(item.get("name", "")).strip(TRAILING_PUNCTUATION)
            if name == candidate:
                return item.get("name")

        # 再做包含匹配
        for item in matches:
            name = normalize_name(item.get("name", "")).strip(TRAILING_PUNCTUATION)
            if candidate in name or name in candidate:
                return item.get("name")

        if not looks_like_model_token(candidate):
            continue

        return matches[0].get("name")

    return None
