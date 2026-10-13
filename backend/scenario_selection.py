"""Deterministic navigation from supported scenario choices to complete plans."""
import re


LEGACY_CHOICES = {
    '蛋白分析与分子互作产品': 'S11',
    '蛋白和分子互作': 'S11',
    '蛋白分析与分子互作': 'S11',
    'NGS建库与测序产品': 'six-01',
    '细胞培养与细胞治疗产品': 'S20',
    '动物活体成像产品': 'S36',
    '显微成像与空间组学产品': 'S16',
}


def choices():
    from backend.scenario_catalog import directory_items

    return [
        {
            'title': item['title'],
            'key': item['id'],
            'source': 'runtime' if item.get('source') == 'runtime' else 'catalog',
        }
        for item in directory_items()
    ]


def option_titles():
    return [c['title'] for c in choices()]


def navigation_result():
    return {'intent':'scenario_navigation','answer':'请选择需要查看的完整方案。',
            'recommended_devices':[], 'need_more_info':[], 'related_questions':[],
            'clarifying_title':'选择完整方案',
            'clarifying_questions':[{'id':'scenario_direction','question':'请选择需要查看的完整方案',
                                     'options':option_titles()}]}


def selection_result(message, action='', action_value=''):
    from backend.scenario_catalog import catalog_chat_result
    from backend.scenario_service import build_scenario_result
    from backend.scenario_names import candidates, present_result, registry, normalize
    selected = (action_value or message).strip() if action=='scenario_choice' else message.strip()
    # Compatibility with the old clarification submission and saved messages.
    selected = re.sub(r'^补充信息[：:]\s*', '', selected)
    selected = re.sub(r'^(?:您更想了解哪类产品[？?]|请选择需要查看的(?:场景|完整)方案)\s*', '', selected)
    selected = re.sub(r'^查看(?=动物活体成像产品|NGS建库与测序产品)', '', selected)
    if selected=='自动化样本前处理产品' or selected=='查看自动化样本前处理产品':
        return navigation_result()
    key=LEGACY_CHOICES.get(selected)
    if any(normalize(selected) == normalize(title) for title in registry()['planned_titles']):
        return {'intent': 'scenario_planned', 'answer': '该名称属于待扩展方案，目前尚未生成完整方案。',
                'recommended_devices': [], 'related_questions': [], 'need_more_info': []}
    matches = [] if key else candidates(selected)
    if len(matches) > 1:
        result = navigation_result()
        result['answer'] = '找到多个相关完整方案，请选择需要查看的一项。'
        result['clarifying_questions'][0]['options'] = [e['display_title'] for e in matches]
        return result
    if matches:
        key = matches[0]['id']
    choice=next((c for c in choices() if selected in (c['title'],c['key']) or c['key']==key),None)
    if not choice:
        return navigation_result() if action=='scenario_choice' else None
    if choice['source']=='catalog':
        return catalog_chat_result(choice['title'],choice['key'])
    return present_result(build_scenario_result(choice['key']))
