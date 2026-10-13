'use strict';
let state = {profiles: [], products: [], demands: [], opportunities: [], authorizations: []};
const $ = id => document.getElementById(id);
const roles = {dealer: '经销商', manufacturer: '厂家', customer: '终端客户'};
const stages = ['待对接', '需求确认', '方案选型', '演示验证', '商务报价', '交付实施', '售后服务', '已关闭'];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const split = value => [...new Set(value.split(/[，,；;\n]+/).map(x => x.trim()).filter(Boolean))];
const pname = id => state.products.find(x => x.id === id)?.name || `已不在产品库：${id}`;
const org = id => state.profiles.find(x => x.id === id)?.name || '记录不存在';
const productNames = ids => ids.map(pname).join('；') || '未登记';
const tags = xs => xs.map(x => `<span class="tag">${esc(x)}</span>`).join('') || '<span class="muted">未登记</span>';
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; $('message').style.display = 'block'; }
async function api(path, method = 'GET', body) {
  const response = await fetch(`/api/channels/${path}`, {method, headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function options(role, selected = '') {
  return '<option value="">请选择</option>' + state.profiles.filter(x => x.role === role && x.active).map(x => `<option value="${esc(x.id)}" ${x.id === selected ? 'selected' : ''}>${esc(x.name)}</option>`).join('');
}
function checks(id, items, selected = []) {
  $(id).innerHTML = items.map(x => `<label data-search="${esc([x.name, x.brand_vendor, x.category].join(' ').toLowerCase())}"><input type="checkbox" value="${esc(x.id)}" ${selected.includes(x.id) ? 'checked' : ''}><span>${esc(x.name)}</span></label>`).join('') || '<p class="muted">暂无可选记录，请先建立对应档案。</p>';
}
function checked(id) { return [...$(id).querySelectorAll('input:checked')].map(x => x.value); }
function filterChecks(id, query) { $(id).querySelectorAll('label').forEach(x => x.hidden = !x.dataset.search.includes(query.toLowerCase())); }
function showTab(id) {
  document.querySelectorAll('.panel').forEach(x => x.classList.toggle('active', x.id === id));
  document.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('active', x.dataset.tab === id));
}
function profileList() {
  const query = $('profileSearch').value.toLowerCase(), role = $('roleFilter').value;
  const items = state.profiles.filter(x => (!role || x.role === role) && [x.name, ...x.regions, ...x.customer_types, ...x.scenarios, productNames(x.product_ids), ...x.customer_ids.map(org)].join(' ').toLowerCase().includes(query));
  $('profileList').innerHTML = items.map(p => `<article class="card"><div class="rowhead"><h3>${esc(p.name)}</h3><button data-edit="${esc(p.id)}">编辑</button></div><div>${tags([roles[p.role], p.active ? '启用' : '停用'])}</div><div class="detail"><p>区域：${tags(p.regions)}</p><p>客户类型：${tags(p.customer_types)}</p><p>场景经验：${tags(p.scenarios)}</p><p>服务能力：${tags(p.capabilities)}</p><p>关联产品：${esc(productNames(p.product_ids))}</p>${p.role === 'dealer' ? `<p>已接触客户：${esc(p.customer_ids.map(org).join('；') || '未登记，目标客户类型不等于实际客户')}</p>` : ''}<p>联系信息：${esc(p.contact || '未登记')} · 内部负责人：${esc(p.owner || '未登记')}</p><p>依据：${esc(p.evidence || '待补充核实依据')}</p><p>${esc(p.notes)}</p></div></article>`).join('') || '<div class="card empty">暂无符合条件的档案。从左侧建立第一个主体。</div>';
}
function editProfile(id) {
  const p = state.profiles.find(x => x.id === id), form = $('profileForm');
  form.reset();
  for (const key of ['id','role','name','contact','owner','evidence','notes','decision_role','sales_team','existing_equipment']) form.elements[key].value = p[key] || '';
  form.elements.contact_policy.value = p.contact_policy || '待核实';
  for (const key of ['regions','customer_types','scenarios','capabilities','product_lines']) form.elements[key].value = (p[key] || []).join('；');
  form.elements.active.checked = p.active; form.elements.role.disabled = true;
  checks('profileProducts', state.products, p.product_ids);
  checks('profileCustomers', state.profiles.filter(x => x.role === 'customer'), p.customer_ids);
  $('profileProductSearch').value = ''; $('customerLinks').hidden = p.role !== 'dealer';
  $('profileTitle').textContent = '编辑主体档案'; form.scrollIntoView({behavior:'smooth', block:'start'});
}
function resetProfile() {
  $('profileForm').reset(); $('profileForm').elements.id.value = ''; $('profileForm').elements.role.disabled = false;
  $('profileTitle').textContent = '新建主体档案'; $('customerLinks').hidden = false;
  checks('profileProducts', state.products); checks('profileCustomers', state.profiles.filter(x => x.role === 'customer' && x.active));
}
function authProducts() {
  const form = $('authorizationForm'), maker = state.profiles.find(x => x.id === form.elements.manufacturer_id.value), dealer = state.profiles.find(x => x.id === form.elements.dealer_id.value);
  checks('authorizationProducts', state.products.filter(x => maker?.product_ids.includes(x.id) && dealer?.product_ids.includes(x.id)));
}
function render() {
  $('stats').innerHTML = [['manufacturer','厂家档案'],['dealer','经销商档案'],['customer','终端客户档案'],['opportunity','协作项目']].map(([key,label]) => `<div class="card stat">${label}<strong>${key === 'opportunity' ? state.opportunities.length : state.profiles.filter(x => x.role === key).length}</strong><small>本机业务记录</small></div>`).join('');
  profileList();
  for (const [form, field, role] of [['demandForm','customer_id','customer'],['authorizationForm','manufacturer_id','manufacturer'],['authorizationForm','dealer_id','dealer']]) {
    const select = $(form).elements[field]; select.innerHTML = options(role, select.value);
  }
  checks('demandProducts', state.products, checked('demandProducts'));
  filterChecks('demandProducts', $('demandProductSearch').value);
  authProducts();
  $('demandList').innerHTML = state.demands.map(d => `<article class="card"><h3>${esc(d.title)}</h3><p>${esc(org(d.customer_id))} · ${esc(d.region)} · ${esc(d.customer_type)}</p><p>应用：${esc(d.scenario || '待补充')}</p><p>产品：${esc(productNames(d.product_ids))}</p><p>${esc(d.requirement)}</p><p class="muted">负责人：${esc(d.owner || '未登记')}</p><button data-match="${esc(d.id)}">匹配经销商</button><div id="match-${esc(d.id)}"></div></article>`).join('') || '<div class="card empty">登记需求后可查看渠道匹配依据。</div>';
  $('authorizationList').innerHTML = state.authorizations.map(a => `<p class="detail">${esc(org(a.manufacturer_id))} → ${esc(org(a.dealer_id))}<br>${esc({pending:'待核实',confirmed:'已核实授权',revoked:'已撤销'}[a.status])} · ${esc(productNames(a.product_ids))}<br><small>${esc(a.evidence || '无凭证')} · 历史变更 ${a.history.length} 次</small></p>`).join('');
  $('opportunityList').innerHTML = state.opportunities.map(o => {
    const demand = state.demands.find(x => x.id === o.demand_id);
    const i = stages.indexOf(o.stage), choices = [...new Set([o.stage, stages[Math.min(i + 1, stages.length - 1)], '已关闭'])];
    return `<article class="card"><h3>${esc(demand?.title || '协作项目')}</h3><div class="notice">${esc(org(o.manufacturer_id))} → ${esc(org(o.dealer_id))} → ${esc(org(o.customer_id))}</div><p>协作产品：${esc(productNames(o.product_ids))}</p><p>${tags([o.stage])} 下一步：${esc(o.next_action || '待登记')}</p><details><summary>查看跟进记录</summary>${o.events.map(e => `<div class="event"><b>${esc(e.actor_name)} · ${esc(e.stage)}</b><p>${esc(e.note)}</p><small>${esc(e.at)} · 下一步：${esc(e.next_action)}</small></div>`).join('') || '<p>暂无跟进记录</p>'}</details>${o.stage === '已关闭' ? '' : `<form data-followup="${esc(o.id)}"><label>代表哪一方记录</label><select name="actor_id">${[o.manufacturer_id,o.dealer_id,o.customer_id].map(id => `<option value="${esc(id)}">${esc(org(id))}</option>`).join('')}</select><label>本次阶段</label><select name="stage">${choices.map(s => `<option>${esc(s)}</option>`).join('')}</select><label>沟通内容 / 本阶段交付物 *</label><textarea name="note" required maxlength="2000"></textarea><label>下一步行动</label><input name="next_action" maxlength="1000"><div class="actions"><button class="primary">保存跟进</button></div></form>`}</article>`;
  }).join('') || '<div class="card empty">在需求匹配结果中选择厂家和经销商，建立三方协作。</div>';
}
async function refresh() { state = await api('workspace'); render(); }
async function showMatches(id) {
  const data = await api(`demands/${id}/matches`), target = $(`match-${id}`);
  target.innerHTML = `<p class="muted">${esc(data.rule)}</p>` + (data.items.map(m => {
    const makers = state.profiles.filter(p => p.active && p.role === 'manufacturer' && p.product_ids.some(x => m.product_ids.includes(x)));
    return `<div class="card"><h3>${esc(m.name)} · 匹配分 ${m.score}</h3><p>${esc(m.reasons.join('；'))}</p><p>覆盖产品：${esc(productNames(m.product_ids))}</p><p>缺口：${esc(m.missing_product_ids.length ? productNames(m.missing_product_ids) : '需求产品均有推广登记')}</p><small>${esc(m.notice)}</small><form data-assign="${esc(id)}" data-dealer="${esc(m.dealer_id)}"><label>选择提供技术支持的厂家</label><select name="manufacturer_id" required><option value="">请选择</option>${makers.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select><small>协作仅关联三方共同产品；其它需求产品需另行对接。</small><div class="actions"><button class="primary" ${makers.length ? '' : 'disabled'}>建立三方协作</button></div>${makers.length ? '' : '<p>请先建立对应产品的厂家档案。</p>'}</form></div>`;
  }).join('') || '<p>暂无匹配经销商。请核查区域、客户类型和推广产品登记是否完整。</p>');
}
document.addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return;
  try {
    if (button.dataset.tab) showTab(button.dataset.tab);
    if (button.dataset.edit) editProfile(button.dataset.edit);
    if (button.dataset.match) { button.disabled = true; await showMatches(button.dataset.match); }
    if (button.id === 'resetProfile') resetProfile();
  } catch (error) { message(error.message, true); } finally { button.disabled = false; }
});
document.addEventListener('submit', async event => {
  event.preventDefault(); const form = event.target, button = form.querySelector('button[type=submit],button.primary'); if (button) button.disabled = true;
  const values = Object.fromEntries(new FormData(form));
  try {
    if (form.getAttribute('id') === 'profileForm') {
      const id = form.elements.id.value; delete values.id;
      values.role = form.elements.role.value;
      for (const key of ['regions','customer_types','scenarios','capabilities','product_lines']) values[key] = split(values[key]);
      values.product_ids = checked('profileProducts'); values.customer_ids = values.role === 'dealer' ? checked('profileCustomers') : []; values.active = form.elements.active.checked;
      await api(id ? `profiles/${id}` : 'profiles', id ? 'PUT' : 'POST', values); await refresh(); resetProfile();
    } else if (form.getAttribute('id') === 'demandForm') {
      values.product_ids = checked('demandProducts'); await api('demands', 'POST', values); form.reset(); checks('demandProducts', state.products); await refresh();
    } else if (form.getAttribute('id') === 'authorizationForm') {
      values.product_ids = checked('authorizationProducts'); await api('authorizations','POST',values); await refresh();
    } else if (form.dataset.assign) {
      await api('opportunities','POST',{demand_id:form.dataset.assign,dealer_id:form.dataset.dealer,manufacturer_id:values.manufacturer_id}); await refresh(); showTab('cooperation');
    } else if (form.dataset.followup) { await api(`opportunities/${form.dataset.followup}/followups`,'POST',values); await refresh(); }
    message('已保存到本机。');
  } catch (error) { message(error.message, true); } finally { if (button) button.disabled = false; }
});
$('profileSearch').addEventListener('input',profileList); $('roleFilter').addEventListener('change',profileList);
$('profileProductSearch').addEventListener('input',e => filterChecks('profileProducts',e.target.value));
$('demandProductSearch').addEventListener('input',e => filterChecks('demandProducts',e.target.value));
$('profileForm').elements.role.addEventListener('change',e => $('customerLinks').hidden = e.target.value !== 'dealer');
$('demandForm').elements.customer_id.addEventListener('change',e => {const p=state.profiles.find(x=>x.id===e.target.value); if(p){$('demandForm').elements.region.value=p.regions[0]||''; $('demandForm').elements.customer_type.value=p.customer_types[0]||'';}});
for (const name of ['manufacturer_id','dealer_id']) $('authorizationForm').elements[name].addEventListener('change',authProducts);
refresh().then(resetProfile).catch(e => message(`加载失败：${e.message}`,true));
