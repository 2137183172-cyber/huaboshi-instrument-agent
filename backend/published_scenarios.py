"""Reviewed public plans, independent of the underlying product graph."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from html import escape
from backend.scenario_prose import join_scope_notes
from backend.scenario_public_view import public_device_name, public_text

FILE = Path(__file__).resolve().parents[1]/'data/knowledge/scenario_publication.json'


@lru_cache(maxsize=1)
def publication():
    if not FILE.exists():
        return {'version': '', 'plans': []}
    return json.loads(FILE.read_text(encoding='utf-8'))


def reviewed_plan(key):
    from backend.scenario_names import registry
    key = registry()['merged_ids'].get(key, key)
    plan = next((p for p in publication()['plans'] if p['scenario_id'] == key), None)
    return deepcopy(plan) if plan else None


def topic_items():
    return [{'id': p['scenario_id'], 'title': p['title'], 'group': '专题方案',
             'summary': '点击查看完整方案', 'scenario_plan': deepcopy(p),
             'file': 'published/'+p['scenario_id']+'.docx'}
            for p in publication()['plans'] if p['scenario_id'].startswith('topic-')]


def document_item(key):
    plan = reviewed_plan(key)
    if plan is None:
        return None
    return {'id': plan['scenario_id'], 'title': plan['title'],
            'file': 'published/'+plan['scenario_id']+'.docx'}


def plan_html(plan):
    def details(step):
        pairs=[('目标',step.get('goal')),('适用样本',step.get('samples')),('执行内容',step.get('capabilities'))]
        pairs += [(role,'；'.join(values)) for role,values in step.get('relations',{}).items()]
        pairs += [(label,step.get(key)) for label,key in [('衔接','handoff'),('质量检查','quality_gate'),('适用边界','boundary'),('输出结果','output')]]
        return [(k,public_text(plan,v)) for k,v in pairs if v]
    h=['<section class="scenario-plan"><h2>'+escape(plan['title'])+'</h2>']
    if plan.get('introduction'):h.append('<p>'+escape(public_text(plan,plan['introduction']))+'</p>')
    if plan.get('scope_notes'):h.append('<p>实施条件：'+escape(public_text(plan,join_scope_notes(plan['scope_notes'])))+'</p>')
    for step in plan['steps']:
        h.append('<h3>'+escape(str(step['step_no'])+'. '+step['name'])+'</h3>')
        h.extend('<p><strong>'+escape(k)+'：</strong>'+escape(v)+'</p>' for k,v in details(step))
    if plan.get('configuration'):h.append('<p>配置安排：'+escape(public_text(plan,plan['configuration']))+'</p>')
    h.extend('<p>验收要点：'+escape(public_text(plan,v))+'</p>' for v in plan.get('acceptance',[]))
    h.append('<h3>方案设备明细表</h3><table><thead><tr>')
    h.extend('<th>'+v+'</th>' for v in ['设备名称','用途及功能'])
    h.append('</tr></thead><tbody>')
    for row in plan['equipment_table']:
        values=[public_device_name(row.get('name'),row.get('model')),public_text(plan,row.get('applications') or '——')]
        h.append('<tr>'+''.join('<td>'+escape(str(value or '——'))+'</td>' for value in values)+'</tr>')
    h.append('</tbody></table><details class="hb-mindmap" open><summary>方案思维导图</summary><ul>')
    for step in plan['steps']:
        h.append('<li>'+escape(step['name'])+'<ul>'+''.join('<li>'+escape(k+'：'+v)+'</li>' for k,v in details(step))+'</ul></li>')
    h.append('</ul></details></section>')
    return ''.join(h)


def stage_result(key, name):
    plan = reviewed_plan(key)
    if not plan:
        return None
    step = next((s for s in plan['steps'] if s['name'] == name), None)
    if not step:
        return None
    names = set(step.get('device_names', [])) or {
        n for values in step.get('relations', {}).values() for n in values}
    cards = [{**row, 'name': public_device_name(row.get('name'), row.get('model')),
              'model': '', 'origin': '', 'scenario_step': name,
              'brand_vendor': '', 'product_code': ''}
             for row in plan['equipment_table'] if row['name'] in names]
    return {'intent': 'scenario_equipment', 'answer_focus': 'scenario_equipment',
            'answer': f"《{plan['title']}》：{name}。" + ('' if cards else '本环节以方法设计、记录或审核为主，没有指定设备。'),
            'scenario_context': {'scenario_id': plan['scenario_id'], 'title': plan['title'],
                                 'selected_stages': [name]},
            'recommended_devices': cards, 'need_more_info': [], 'clarifying_questions': [],
            'related_questions': [], 'generation_source': 'scenario_catalog'}
