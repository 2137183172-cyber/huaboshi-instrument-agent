"""Public scenario names and searchable aliases; base knowledge stays intact."""
from copy import deepcopy
from difflib import SequenceMatcher
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def registry():
    path = Path(__file__).resolve().parents[1]/'data/knowledge/scenario_names.json'
    return json.loads(path.read_text(encoding='utf-8'))


def entry(key):
    key = registry()['merged_ids'].get(key, key)
    return next((e for e in registry()['entries'] if e['id'] == key), None)


def display_title(key, fallback=''):
    value = entry(key)
    return value['display_title'] if value else fallback


def normalize(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', text.casefold())


def names(e):
    return list(dict.fromkeys([e['display_title'], e['base_title'], *e['aliases']]))


def candidates(query):
    text = normalize(query)
    for e in registry()['entries']:
        if any(text == normalize(n) for n in names(e)) or query == e['id']:
            return [e]
    # Do not turn equipment follow-ups into a fresh full-plan answer.
    if any(w in query for w in ('参数', '报价', '预算', '哪个设备', '哪些设备', '品牌', '厂家', '多少钱', '适用样本', '步骤')):
        return []
    text = re.sub(r'^(请|帮我|给我|我想|想|我要|要|查看|看看|生成|输出|搜索|找一下|找|了解)+', '', text)
    text = re.sub(r'(完整|项目|平台|研究|综合|方案|流程|的|一下|吗|呢|怎么做)', '', text)
    if len(text) < 3:
        # Short topics must match a registered alias exactly, never fuzzily.
        return [e for e in registry()['entries'] if text and any(
            text == normalize(n) for n in names(e))]
    ranked = []
    for e in registry()['entries']:
        score = 0
        for name in names(e):
            value = re.sub(r'(完整|项目|平台|研究|综合|方案|流程|的)', '', normalize(name))
            if text == value:
                current = 1.0
            elif text in value or (len(value) >= 5 and value in text):
                current = .94
            elif len(text) >= 5:
                current = SequenceMatcher(None, text, value).ratio()
            else:
                current = 0
            score = max(score, current)
        if score >= .78:
            ranked.append((score, e))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked:
        return []
    best = ranked[0][0]
    return [e for score, e in ranked if best - score < .08]


def present_result(result):
    result = deepcopy(result)
    plan = result.get('scenario_plan')
    if not plan:
        return result
    value = entry(plan.get('scenario_id'))
    if not value:
        return result
    if result.get('intent', 'scenario_plan') == 'scenario_plan':
        from backend.published_scenarios import reviewed_plan
        reviewed = reviewed_plan(plan.get('scenario_id'))
        if reviewed:
            result['scenario_plan'] = plan = reviewed
    old_title = plan.get('title', '')
    plan['title'] = value['display_title']
    plan['base_title'] = value['base_title']
    if old_title:
        for key in ('answer', 'related_questions'):
            if isinstance(result.get(key), str):
                result[key] = result[key].replace(old_title, value['display_title'])
            elif isinstance(result.get(key), list):
                result[key] = [v.replace(old_title, value['display_title']) if isinstance(v, str) else v for v in result[key]]
    if result.get('intent') == 'scenario_plan':
        result['answer'] = '《'+plan['title']+'》'
        result['related_questions'] = []
    return result
