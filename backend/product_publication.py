"""Customer/LLM boundary: internal identifiers and commercial data stay private."""
import re
from functools import lru_cache
from urllib.parse import quote

PRIVATE_KEYS = {
    'product_id', 'industrial_code', 'record_id', 'record_ids', 'record_key', 'price_range',
    'price_visibility', 'source_files', 'source_pages', 'source_sheets',
    'source_datasets', 'evidence_chunks_raw', 'review_notes', 'approved_by',
    'approval_basis', 'supplement_source', 'supplement_review_status',
    'source_report_model', 'diagnostics', 'model_error', 'fallback_reason',
    'confidence_score', 'local_score', 'score', 'chunk_id', 'graph_score', 'graph_relations',
}


def private_key(key):
    return key in PRIVATE_KEYS or key.startswith('reference_quote_') or 'review' in key


@lru_cache(maxsize=1)
def internal_tokens():
    from backend.knowledge_catalog import load_knowledge_products
    products = load_knowledge_products()
    models = {p.get('product_code') for p in products if p.get('product_code')}
    # Some legacy identifier values are genuine models; do not censor models.
    return tuple(sorted({str(p.get(k)) for p in products for k in ('product_id', 'record_id')
                         if p.get(k) and p.get(k) not in models}, key=len, reverse=True))


@lru_cache(maxsize=1)
def internal_token_patterns():
    # Match complete identifiers; a legacy ID may be a prefix of a valid model.
    return tuple(re.compile(r'(?<![A-Za-z0-9])'+re.escape(value)+r'(?![A-Za-z0-9])')
                 for token in internal_tokens() for value in {token, quote(token, safe='')})


def customer_text(value):
    text = re.sub(r'(?:\*\*)?(?:产业编号|产品编号|内部编号|产品ID|product_id|industrial_code|record_key)(?:\*\*)?\s*[:：]\s*[^\s，,；;。|<]+', '', value, flags=re.I)
    for pattern in internal_token_patterns():
        text = pattern.sub('', text)
    # PubMed Central accessions are public citations, not industrial identifiers.
    text = re.sub(r'\b(?!PMC\d+\b)[A-Z]{3,8}\d{7,}\b', '', text)
    return text


def public_payload(value):
    """Preserve typed blanks; the presentation layer renders a hyphen."""
    if isinstance(value, dict):
        return {k: public_payload(v) for k,v in value.items() if not private_key(k)}
    if isinstance(value, list):
        return [public_payload(v) for v in value]
    if isinstance(value, str):
        return customer_text(value)
    return value


def public_chat_payload(result):
    from backend.scenario_names import present_result
    result = present_result(result)
    from backend.local_catalog import load_products
    by_name = {p['name']:p for p in reversed(load_products())}
    for card in result.get('recommended_devices', []):
        product = by_name.get(card.get('name'))
        if product:
            for key in ('product_code','brand_vendor','supplier_name','brand_name','overview',
                        'advantages','applications','key_specs','product_configuration','sample_types'):
                card[key] = product.get(key)
    return public_payload(result)


def reviewed_fact_answer(query):
    """Known product fields, especially blanks, must not be invented by the LLM."""
    from backend.knowledge_catalog import reviewed_catalog_is_authoritative
    from backend.local_catalog import load_products, get_local_device_detail
    if not reviewed_catalog_is_authoritative():
        return None
    fields = []
    for terms, key, label in [
        (('厂家','制造商','品牌'), 'brand_vendor', '品牌/厂家'),
        (('供货单位','供应商'), 'supplier_name', '供货单位'),
        (('参数','规格'), 'key_specs', '技术参数'),
        (('配置',), 'product_configuration', '配置需求（非标配承诺）'),
        (('优势',), 'advantages', '产品优势'),
        (('样本',), 'sample_types', '适用样本'),
        (('型号',), 'product_code', '型号'),
        (('产地',), 'origin', '产地'),
    ]:
        if any(t in query for t in terms):
            fields.append((key,label))
    if not fields:
        return None
    hits = []
    for p in load_products():
        aliases=[p['name'],p.get('product_code'),p.get('product_id'),*p.get('aliases',[])]
        if any(a and len(a)>=2 and re.search(r'(?<![A-Za-z0-9])'+re.escape(a)+r'(?![A-Za-z0-9])',query,re.I) for a in aliases):
            hits.append(p)
    if len({p['name'] for p in hits}) != 1:
        return None
    product=hits[0]
    lines=[product['name']]
    for key,label in fields:
        value=product.get(key)
        if isinstance(value,list):
            value='；'.join(value)
        lines.append(f'{label}：{value if value not in (None, "") else "-"}')
    return {'intent':'detail','answer':'\n'.join(lines),
            'recommended_devices':[get_local_device_detail(product['name'])],
            'related_questions':[],'need_more_info':[],'clarifying_questions':[],
            'disclaimer':'仅依据已审核产品资料；“-”表示该字段暂未提供。',
            'generation_source':'reviewed_product_knowledge'}
