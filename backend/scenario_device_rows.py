"""Render reviewed multi-model equipment without fuzzy lookup or renaming."""
from functools import lru_cache
import json
from backend.knowledge_catalog import PRODUCTS_FILE


@lru_cache(maxsize=1)
def products_by_key():
    return {p['record_id']:p for p in json.loads(PRODUCTS_FILE.read_text(encoding='utf-8'))['products']}


def reviewed_equipment_row(item, step):
    lookup = products_by_key()
    products = [lookup[k] for k in item.get('record_ids',[]) if k in lookup]
    def joined(field):
        return '；'.join(dict.fromkeys(str(p.get(field) or '').strip() for p in products if p.get(field)))
    return {
        'name':item['name'], 'brand':joined('brand_vendor'),
        'model':'；'.join(dict.fromkeys((p.get('product_code') or '').split('；')[0] for p in products if p.get('product_code'))),
        'origin':joined('origin'), 'industrial_code':'',
        'technical_specs':'', 'applications':item.get('description',''),
        'description':item.get('description',''), 'step_no':str(step.get('step_no') or ''),
    }
