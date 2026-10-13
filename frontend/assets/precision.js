'use strict';
(() => {
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = value => [...new Set(value.split(/[，,；;\n]+/).map(s=>s.trim()).filter(Boolean))];
  const opts = values => values.map(v=>`<option>${e(v)}</option>`).join('');
  const input = (name, label, value='', type='text') => `<label>${label}<input name="${name}" type="${type}" value="${e(value)}" required></label>`;
  const profile = document.getElementById('profileForm');
  profile.querySelector('.actions').insertAdjacentHTML('beforebegin', `<details><summary>业务背景</summary><label>经营产品线（分号分隔）</label><input name="product_lines" placeholder="SPR；BLI；MST"><label>联系人职务与职责</label><input name="decision_role" maxlength="200"><label>销售团队</label><input name="sales_team" maxlength="400"><label>现有设备与业务需求</label><textarea name="existing_equipment" maxlength="2000"></textarea><label>联系状态</label><select name="contact_policy">${opts(['待核实','可业务联系','拒绝联系'])}</select></details>`);
  document.querySelector('nav').insertAdjacentHTML('beforeend','<button data-tab="precision">重点产品精准拓展</button>');
  document.querySelector('main').insertAdjacentHTML('beforeend','<section id="precision" class="panel"><div class="notice">加载精准拓展工作台…</div></section>');
  const panel = document.getElementById('precision');
  let data, products;
  async function request(path, body) {
    const r = await fetch('/api/precision/' + path, {method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
    const result=await r.json(); if(!r.ok) throw Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail)); return result;
  }
  function render() {
    const x=data.example;
    panel.innerHTML=`<div class="notice"><b>重点产品拓展</b><br>选产品 · 找渠道 · 联系客户 · 跟进商机</div>
    <button type="button" id="refreshPrecision">刷新</button><div class="stats">${Object.entries({briefs:'拓展任务',reviewed:'审核通过',contacted:'已联系',opportunities:'关联商机'}).map(([k,v])=>`<div class="card stat">${v}<strong>${data.metrics[k]}</strong></div>`).join('')}</div>
    <article class="card"><h2>分子互作样本制备设备 · 拓展示例</h2><p>围绕客户的配样需求，寻找合适的经销商和研究团队。</p><div class="flow">${['了解客户的设备和配样需求','梳理样品配制流程','确认设备与方法是否适用','安排检测与演示','跟进合作机会'].map((s,i)=>`<div>${i+1}. ${e(s)}</div>`).join('')}</div><p><b>从经销商入手：</b>联系经营 SPR、BLI、MST 相关设备的经销商，了解客户的配样需求。<br><b>从客户入手：</b>寻找开展分子互作研究的团队，再对接熟悉这些客户的经销商。</p><details><summary>沟通参考</summary><p>${e(x.outreach)}</p></details><details><summary>产品资料与审核事项</summary><p>${e(x.source)}</p><p>${e(x.boundary)}</p><p>${e(x.data_warning)}</p><ul>${x.checks.map(s=>`<li>${e(s)}</li>`).join('')}</ul></details><button type="button" id="fillPrecisionCase">使用此案例</button></article>
    <div class="grid"><form class="card" data-precision="brief"><h2>建立重点产品任务</h2>${input('title','任务名称')}
    <label>产品<select name="product_id" required><option value="">请选择</option>${products.map(p=>`<option value="${e(p.id)}">${e(p.name)} · ${e(p.brand_vendor)}</option>`).join('')}</select></label>
    ${input('owner','负责人')}${input('due_date','截止日期','','date')}<label>合作类型<select name="priority">${opts(['战略候选','重点合作','付费合作'])}</select></label>
    ${input('product_lines','经销商产品线（如 SPR；BLI；MST）')}${input('target_scenarios','客户研究方向（如 分子互作；蛋白互作）')}
    <label>目标区域<input name="regions" placeholder="不限区域可留空"></label><label>能为客户解决什么问题<textarea name="benefit" required maxlength="2000"></textarea></label><label>需要确认的事项<textarea name="boundary" required maxlength="2000"></textarea></label><button class="primary">保存任务</button></form>
    <div>${data.briefs.map(b=>`<article class="card"><h2>${e(b.title)}</h2><p>${e(b.owner)} · ${e(b.due_date)} · ${b.ready?'审核通过':'待审核'}</p><p>${e(b.benefit)}</p><details><summary>待确认事项</summary><p>${e(b.boundary)}</p></details>
    ${['产品','应用','商务'].map(r=>`<p><b>${r}审核：</b>${e(b.reviews[r]?.decision||'待核实')} · ${e(b.reviews[r]?.reviewer||'-')}<br>${e(b.reviews[r]?.scope||'未填适用范围')}<br>${e(b.reviews[r]?.evidence||'未填证据')}</p>`).join('')}
    <details><summary>审核记录</summary><form data-precision="review" data-key="${e(b.id)}"><label>职责<select name="role">${opts(['产品','应用','商务'])}</select></label><label>结果<select name="decision">${opts(['待核实','通过','不通过'])}</select></label>${input('reviewer','审核人')}${input('scope','适用机型与条件')}${input('evidence','参考资料')}<button class="primary">保存审核</button></form><p>${b.events.map(v=>`${e(v.at)} ${e(v.role)} ${e(v.reviewer)}：${e(v.decision)} / ${e(v.scope)} / ${e(v.evidence)}`).join('<br>')||'暂无记录'}</p></details>
    <h3>潜在合作对象</h3>${b.candidates.length?b.candidates.map(c=>`<div class="notice"><b>${e(c.name)}</b> · ${c.role==='dealer'?'经销商':'终端客户'}<br>${e(c.reasons.join('；'))}<br>关联经销商：${e(c.linked_dealers.join('；')||'未登记')}</div>`).join(''):'<p>暂无匹配对象，可先补充经销商产品线和客户研究方向。</p>'}
    <details><summary>安排跟进</summary><form data-precision="action" data-key="${e(b.id)}"><label>合作对象<select name="target_id" required><option value="">请选择</option>${b.candidates.map(c=>`<option value="${e(c.id)}">${e(c.name)}</option>`).join('')}</select></label><label>任务类别<select name="kind">${opts(['资料核实','业务触达'])}</select></label>${input('owner','负责人',b.owner)}${input('due_date','截止日期',b.due_date,'date')}${input('next_action','下一步')}<button class="primary">安排任务</button></form></details></article>`).join('')||'<div class="card">从左侧新建第一个拓展任务。</div>'}</div></div>
    <h2>执行与反馈</h2>${data.actions.map(a=>`<article class="card"><h3>${e(a.target_name)} · ${e(a.result)} ${a.overdue?'（逾期）':''}</h3><p>${e(a.owner)} · ${e(a.due_date)} · ${e(a.next_action)}</p><details><summary>跟进历史</summary>${a.events.map(v=>`<p>${e(v.at)} ${e(v.result)}：${e(v.note)}<br>下一步：${e(v.next_action)}</p>`).join('')||'尚未执行'}</details>${a.result==='拒绝联系'?'已停止推进':`<form data-precision="feedback" data-key="${e(a.id)}"><label>本次结果<select name="result">${opts(['待执行','已联系','有效意向','暂无需求','拒绝联系','商机关联'])}</select></label>${input('note','实际反馈 / 证据')}${input('next_action','下一步（结束请注明结束原因）')}${input('due_date','下次日期',a.due_date,'date')}<label>真实协作商机<select name="opportunity_id"><option value="">未关联</option>${(state.opportunities||[]).map(o=>`<option value="${e(o.id)}">${e(state.demands.find(d=>d.id===o.demand_id)?.title||o.id)}</option>`).join('')}</select></label><button class="primary">记录反馈</button></form>`}</article>`).join('')||'<div class="card">暂无执行记录。</div>'}
    <div class="card"><h2>拓展更多合作伙伴</h2><p>寻找能补齐方案的厂家，通过经销商和行业熟人转介绍，接触有相关研究需求的客户。</p><a href="/growth">管理拓展线索与跟进任务</a></div>`;
  }
  async function load() { data=await request('workspace'); if(!products) products=(await (await fetch('/api/channels/workspace')).json()).products; render(); }
  panel.addEventListener('submit',async event=>{
    event.preventDefault(); event.stopPropagation(); const f=event.target,button=f.querySelector('button');button.disabled=true;
    try { const body=Object.fromEntries(new FormData(f)); const kind=f.dataset.precision;
      if(kind==='brief') for(const k of ['product_lines','target_scenarios','regions']) body[k]=list(body[k]);
      const path=kind==='brief'?'briefs':kind==='review'?`briefs/${f.dataset.key}/reviews`:kind==='action'?`briefs/${f.dataset.key}/actions`:`actions/${f.dataset.key}/feedback`;
      await request(path,body);await load();message('已保存。');
    } catch(err){message(err.message,true);} finally {button.disabled=false;}
  });
  panel.addEventListener('click',event=>{
    if(event.target.id==='refreshPrecision') {load().catch(err=>message(err.message,true));return;}
    if(event.target.id!=='fillPrecisionCase') return;
    const f=panel.querySelector('[data-precision="brief"]');
    f.elements.title.value=data.example.title;
    f.elements.product_lines.value='SPR；BLI；MST';f.elements.target_scenarios.value='分子互作；蛋白互作；分子互作检测';
    f.elements.benefit.value='了解客户重复梯度配样的工作量，通过演示评估自动配样的效率和重复性。';
    f.elements.boundary.value='确认产品主记录、下游检测机型、样品与耗材要求，补充适配报告和演示结果。';
    const ids=new Set(data.example.products.map(p=>p.id));
    for(const option of f.elements.product_id.options) option.hidden=Boolean(option.value)&&!ids.has(option.value);
    f.elements.product_id.value='';f.scrollIntoView({behavior:'smooth'});message('案例已填入，请补充产品、负责人和日期后保存。');
  });
  load().then(()=>{if(location.hash==='#precision') showTab('precision');}).catch(err=>{panel.textContent='加载失败：'+err.message;});
})();
