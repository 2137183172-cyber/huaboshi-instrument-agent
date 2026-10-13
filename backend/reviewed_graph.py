"""Versioned product graph. Never mix a stale graph with a reviewed catalog."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from time import monotonic
from pathlib import Path

from backend.knowledge_catalog import PRODUCTS_FILE, SCENARIOS_FILE, RELATION_WEIGHTS

SCHEMA_VERSION = 'reviewed-graph-v1'
ROLES = set(RELATION_WEIGHTS)
LABELS = {'product':'PIMProduct','scenario':'PIMScenario','step':'PIMStep',
          'capability':'PIMCapability','task':'PIMTask','brand':'PIMBrandVendor',
          'supplier':'PIMSupplier','sample':'PIMSampleType','evidence':'PIMEvidence'}
RELATIONS = {'HAS_STEP','NEXT_STEP','USES_PRODUCT','EXCLUDES_PRODUCT','HAS_CAPABILITY',
             'APPLIED_IN','HAS_BRAND_VENDOR','SUPPLIED_BY','ACCEPTS_SAMPLE','HAS_EVIDENCE'}


def norm(value):
    return re.sub(r'\s+','',str(value or '')).casefold()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def release_id(product_path=PRODUCTS_FILE, scenario_path=SCENARIOS_FILE):
    return digest(SCHEMA_VERSION.encode()+product_path.read_bytes()+scenario_path.read_bytes())


@lru_cache(maxsize=1)
def current_release():
    return release_id()


def values(value):
    if isinstance(value,list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r'[；;\n]+',str(value or '')) if v.strip()]


def match_product(item, products):
    """Exact stable key/name/model only; ambiguity is a review item, not an edge."""
    explicit=item.get('record_id') or item.get('product_id')
    if explicit:
        hits=[p for p in products if explicit in (p.get('record_id'),p.get('product_id'))]
    else:
        target=norm(item.get('name'))
        hits=[p for p in products if target and target in
              {norm(p.get(k)) for k in ('display_name','product_name','product_code')}]
        if not hits:
            # A model must be a whole token and uniquely identify one record.
            text=str(item.get('name') or '')
            hits=[p for p in products if len(str(p.get('product_code') or ''))>=3 and
                  re.search(r'(?<![A-Za-z0-9])'+re.escape(p['product_code'])+r'(?![A-Za-z0-9])',text,re.I)]
    return hits[0] if len(hits)==1 else None, [p['record_id'] for p in hits]


def match_products(item, products):
    """Allow multiple models only via reviewed stable keys, never fuzzy hits."""
    if 'record_ids' in item:
        keys = item['record_ids']
        if not isinstance(keys, list) or not keys or not all(isinstance(k,str) for k in keys):
            return [], [], 'invalid_record_ids'
        lookup = {p['record_id']:p for p in products}
        if any(key not in lookup for key in keys):
            return [], keys, 'unknown_record_id'
        return [lookup[k] for k in dict.fromkeys(keys)], keys, ''
    p,hits = match_product(item,products)
    return ([p],hits,'') if p else ([],hits,'ambiguous' if hits else 'unmatched')


def build_plan(product_path=PRODUCTS_FILE, scenario_path=SCENARIOS_FILE):
    payload=json.loads(product_path.read_text(encoding='utf-8'))
    products=payload['products']
    scenarios=json.loads(scenario_path.read_text(encoding='utf-8'))['scenarios']
    if not payload.get('metadata',{}).get('authoritative_reviewed') or not products:
        raise ValueError('A published, authoritative reviewed catalog is required')
    if any(p.get('review_status')!='approved' or not p.get('record_id') for p in products):
        raise ValueError('Unapproved products or missing stable record keys')
    if len({p['record_id'] for p in products})!=len(products):
        raise ValueError('Duplicate stable product keys')
    release=release_id(product_path,scenario_path)
    nodes={};edges={};pending=[]

    def node(kind,identity,**props):
        key=digest((release+'|'+kind+'|'+str(identity)).encode())
        nodes[key]={'key':key,'kind':kind,'props':dict(props,node_key=key,release_id=release)}
        return key

    def edge(a,b,kind,**props):
        key=(a,b,kind,str(props.get('role','')))
        edges[key]={'a':a,'b':b,'kind':kind,'role':props.get('role',''),'props':props}

    product_keys={}
    from scripts.publish_reviewed_products import PUBLIC_FACTS
    for p in products:
        facts={k:p.get(k,'') for k in PUBLIC_FACTS}
        # Node properties only contain scalars and scalar lists; the fact map is JSON.
        key=node('product',p['record_id'],record_id=p['record_id'],product_id=p.get('product_id',''),
                 name=p.get('display_name') or p['product_name'],facts_json=json.dumps(facts,ensure_ascii=False))
        product_keys[p['record_id']]=key
        for field,kind,rel in [('capabilities','capability','HAS_CAPABILITY'),('tasks','task','APPLIED_IN'),
                               ('sample_types','sample','ACCEPTS_SAMPLE'),('brand_vendor','brand','HAS_BRAND_VENDOR'),
                               ('supplier_name','supplier','SUPPLIED_BY')]:
            for value in values(p.get(field)):
                edge(key,node(kind,value,name=value),rel)
        for field in ('overview','advantages','applications','key_specs','product_configuration'):
            text='\n'.join(values(p.get(field)))
            if text:
                edge(key,node('evidence',p['record_id']+'|'+field,section=field,text=text,
                              source_sha256=payload['metadata'].get('source_sha256','')), 'HAS_EVIDENCE')
    for scenario in scenarios:
        skey=node('scenario',scenario['scenario_id'],scenario_id=scenario['scenario_id'],title=scenario.get('title',''))
        previous=None
        for order,step in enumerate(scenario.get('steps',[]),1):
            stepkey=node('step',scenario['scenario_id']+'|'+str(order),step_no=str(step.get('step_no',order)),
                         name=step.get('name',''),goal=step.get('goal',''),handoff=step.get('handoff',''),order=order)
            edge(skey,stepkey,'HAS_STEP')
            if previous:
                # Source document order, not an invented physical compatibility assertion.
                edge(previous,stepkey,'NEXT_STEP',basis='source_document_order')
            previous=stepkey
            resolved=[]
            for role,items in step.get('relations',{}).items():
                for item in items:
                    if item.get('external'):continue
                    matched,hits,reason=match_products(item,products)
                    if role not in ROLES or not matched:
                        pending.append({'scenario_id':scenario['scenario_id'],'step_no':step.get('step_no'),
                                        'role':role,'name':item.get('name'),'candidate_ids':hits,
                                        'reason':'unknown_role' if role not in ROLES else reason})
                        continue
                    resolved.extend((p,role,item) for p in matched)
            excluded={p['record_id'] for p,r,i in resolved if r=='不兼容设备'}
            for p,role,item in resolved:
                if p['record_id'] in excluded and role!='不兼容设备':
                    pending.append({'scenario_id':scenario['scenario_id'],'step_no':step.get('step_no'),
                                    'name':item.get('name'),'role':role,'reason':'incompatible_role_conflict'})
                    continue
                edge(stepkey,product_keys[p['record_id']], 'EXCLUDES_PRODUCT' if role=='不兼容设备' else 'USES_PRODUCT',
                     role=role,description=item.get('description',''),basis='explicit_scenario_relation')
    return {'schema':SCHEMA_VERSION,'release_id':release,'products':len(products),'scenarios':len(scenarios),
            'nodes':list(nodes.values()),'edges':list(edges.values()),'pending_review':pending,
            'product_sha256':digest(product_path.read_bytes()),'scenario_sha256':digest(scenario_path.read_bytes())}


def connect():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env', override=False)
    from neo4j import GraphDatabase
    return GraphDatabase.driver(os.getenv('NEO4J_URI','bolt://127.0.0.1:7687'),
        auth=(os.getenv('NEO4J_USERNAME','neo4j'),os.getenv('NEO4J_PASSWORD','')),
        connection_timeout=2,connection_acquisition_timeout=3,max_transaction_retry_time=0)


def sync_plan(driver,plan):
    database=os.getenv('NEO4J_DATABASE','neo4j')
    # Namespaced labels do not touch legacy Device or operational/customer nodes.
    for label in [*LABELS.values(),'PIMRelease','PIMGraphState']:
        prop='node_key' if label in LABELS.values() else 'release_id' if label=='PIMRelease' else 'name'
        driver.execute_query(f'CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE',database_=database)

    def write(tx):
        for kind,label in LABELS.items():
            tx.run(f'UNWIND $rows AS row MERGE (n:{label} {{node_key:row.key}}) SET n = row.props',
                   rows=[n for n in plan['nodes'] if n['kind']==kind]).consume()
        for kind in sorted(RELATIONS):
            tx.run(f'UNWIND $rows AS row MATCH (a {{node_key:row.a}}), (b {{node_key:row.b}}) '
                   f'MERGE (a)-[r:{kind} {{role:row.role}}]->(b) SET r += row.props',
                   rows=[e for e in plan['edges'] if e['kind']==kind]).consume()
        actual=tx.run('MATCH (p:PIMProduct {release_id:$release}) RETURN count(p) AS n',release=plan['release_id']).single()['n']
        if actual!=plan['products']:
            raise RuntimeError('Graph product verification failed; transaction rolled back')
        edge_count=tx.run('MATCH (a {release_id:$release})-[r]->(b {release_id:$release}) RETURN count(r) AS n',release=plan['release_id']).single()['n']
        if edge_count!=len(plan['edges']):
            raise RuntimeError('Graph relationship verification failed; transaction rolled back')
        tx.run('MERGE (v:PIMRelease {release_id:$release}) SET v.status="ready", v.products=$products, '
               'v.product_sha256=$ph, v.scenario_sha256=$sh, v.schema=$schema '
               'MERGE (s:PIMGraphState {name:"reviewed_products"}) '
               'SET s.previous_release = CASE WHEN s.active_release = $release THEN s.previous_release ELSE s.active_release END, '
               's.active_release=$release',release=plan['release_id'],products=plan['products'],
               ph=plan['product_sha256'],sh=plan['scenario_sha256'],schema=plan['schema']).consume()
        return {'products':actual,'relationships':edge_count,'release_id':plan['release_id']}
    with driver.session(database=database) as session:
        return session.execute_write(write)


_retry_after=0.0


def graph_context(record_ids,scenario_ids):
    global _retry_after
    if monotonic()<_retry_after:
        return None
    try:
        with connect() as driver:
            rows,_,_=driver.execute_query('MATCH (s:PIMGraphState {name:"reviewed_products",active_release:$release}) '
                'MATCH (v:PIMRelease {release_id:s.active_release,status:"ready"}) RETURN v.products AS products',
                release=current_release(),database_=os.getenv('NEO4J_DATABASE','neo4j'))
            if not rows:return None
            rows,_,_=driver.execute_query('MATCH (s:PIMScenario {release_id:$release})-[:HAS_STEP]->(t:PIMStep) '
                'MATCH (t)-[r]->(p:PIMProduct {release_id:$release}) '
                'WHERE type(r) IN ["USES_PRODUCT","EXCLUDES_PRODUCT"] AND s.scenario_id IN $scenarios AND p.record_id IN $ids '
                'RETURN p.record_id AS record_id,s.title AS scenario,t.name AS step,r.role AS role,type(r) AS kind',
                release=current_release(),scenarios=scenario_ids,ids=record_ids,
                database_=os.getenv('NEO4J_DATABASE','neo4j'))
            return [r.data() for r in rows]
    except Exception:
        # Fail closed to the reviewed local catalog, never to old vector documents.
        _retry_after=monotonic()+30
        return None


def enrich_recommendation(query,result):
    from backend.knowledge_catalog import load_scenarios, score_scenario
    scenarios=sorted([(score_scenario(query,s)[0],s['scenario_id']) for s in load_scenarios()],reverse=True)
    scenario_ids=[sid for score,sid in scenarios[:2] if score>=22]
    candidates=result.get('candidate_devices',[])
    context=graph_context([p.get('record_id') for p in candidates if p.get('record_id')],scenario_ids)
    if context is None:return False
    by_id=defaultdict(list)
    for r in context:by_id[r['record_id']].append(r)
    kept=[]
    for item in candidates:
        relations=by_id[item.get('record_id')]
        # Incompatibility cannot be rewarded as another recommendation relation.
        if any(r['kind']=='EXCLUDES_PRODUCT' for r in relations):continue
        bonus=max([min(30,RELATION_WEIGHTS.get(r['role'],0)//3) for r in relations]+[0])
        item['graph_score']=bonus
        item['graph_relations']=relations
        if relations:
            best=max(relations,key=lambda r:RELATION_WEIGHTS.get(r['role'],0))
            item.setdefault('match_reasons',[]).insert(0,f"在{best['scenario']}的{best['step']}步骤中为{best['role']}")
        kept.append(item)
    result['candidate_devices']=sorted(kept,key=lambda p:p.get('local_score',0)+p.get('graph_score',0),reverse=True)
    allowed={p['name'] for p in kept}
    result['evidence_chunks']=[e for e in result.get('evidence_chunks',[]) if e.get('product_name') in allowed]
    result['source']='reviewed_neo4j_graph'
    return True
