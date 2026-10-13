'use strict';
const $ = id => document.getElementById(id);
const roles = {manufacturer:'厂家', dealer:'经销商', customer:'终端客户'};
const nextStages = {'发现':['已核实','关闭'],'已核实':['已触达','培育','关闭'],'已触达':['有效意向','培育','关闭'],'有效意向':['培育','关闭'],'培育':['已核实','已触达','关闭']};
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const split = v => [...new Set(v.split(/[，,；;\n]+/).map(x=>x.trim()).filter(Boolean))];
const rate = v => v == null ? '—' : `${(v*100).toFixed(1)}%`;
let state = {prospects:[],campaigns:[],tasks:[],metrics:{},by_role:{},by_source:[]}, channel={profiles:[],products:[]};
let importPreview = null;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';$('message').style.display='block';}
async function api(path,method='GET',body){const r=await fetch(`/api/growth/${path}`,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;}
function tab(id){document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('nav [data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));}
function campaignOptions(selected='',role=''){return '<option value="">不关联项目</option>'+state.campaigns.filter(c=>c.active&&(!role||c.role===role)||c.id===selected).map(c=>`<option value="${esc(c.id)}" ${c.id===selected?'selected':''}>${esc(c.name)} · ${roles[c.role]}</option>`).join('');}
function productChecks(ids=[]){$('productChecks').innerHTML=channel.products.map(p=>`<label data-search="${esc(p.name.toLowerCase())}"><input type="checkbox" value="${esc(p.id)}" ${ids.includes(p.id)?'checked':''}><span>${esc(p.name)}</span></label>`).join('');$('productSearch').value='';}
function selectedProducts(){return [...$('productChecks').querySelectorAll('input:checked')].map(x=>x.value);}
function fillSelectOptions(){
  const f=$('prospectForm');
  f.elements.campaign_id.innerHTML=campaignOptions(f.elements.campaign_id.value,f.elements.role.value);
  const ref=f.elements.referrer_id.value;
  f.elements.referrer_id.innerHTML='<option value="">无 / 尚未登记</option>'+channel.profiles.filter(p=>p.active||p.id===ref).map(p=>`<option value="${esc(p.id)}" ${p.id===ref?'selected':''}>${esc(p.name)} · ${roles[p.role]}</option>`).join('');
  const task=$('taskForm').elements.prospect_id, current=task.value;
  task.innerHTML='<option value="">请选择线索</option>'+state.prospects.filter(p=>!['已入池','关闭'].includes(p.stage)&&p.contact_policy!=='拒绝联系').map(p=>`<option value="${esc(p.id)}" ${current===p.id?'selected':''}>${esc(p.name)} · ${roles[p.role]}</option>`).join('');
  $('importCampaign').innerHTML=campaignOptions($('importCampaign').value);
}
function metricsTable(items, label){return `<table><thead><tr><th>${label}</th><th>发现</th><th>核实</th><th>触达</th><th>意向</th><th>入池</th><th>净新增档案</th><th>入池后激活</th><th>核实→入池</th></tr></thead><tbody>${items.map(([name,m])=>`<tr><td>${esc(name)}</td>${['discovered','qualified','contacted','engaged','converted','created_profiles','activated'].map(k=>`<td>${m[k]}</td>`).join('')}<td>${rate(m.conversion_rate)}</td></tr>`).join('')}</tbody></table>`;}
function renderDashboard(){
  const labels={discovered:'发现机构',qualified:'已核实',contacted:'已触达',engaged:'有效意向',converted:'转入正式池',created_profiles:'净新增档案'};
  $('stats').innerHTML=Object.entries(labels).map(([k,v])=>`<div class="card stat">${v}<strong>${state.metrics[k]}</strong><small>累计达成</small></div>`).join('');
  $('roleMetrics').innerHTML=metricsTable(Object.entries(state.by_role).map(([r,m])=>[roles[r],m]),'主体');
  $('sourceMetrics').innerHTML=state.by_source.length?metricsTable(state.by_source.map(m=>[m.source,m]),'来源'):'<p class="empty">暂无来源数据。建立项目并登记第一条线索。</p>';
  const open=state.prospects.filter(p=>!['已入池','关闭'].includes(p.stage));
  const noTask=open.filter(p=>!state.tasks.some(t=>t.prospect_id===p.id&&t.status==='待办')).length;
  $('actionSummary').innerHTML=`<p>逾期待办：<b>${state.tasks.filter(t=>t.overdue).length}</b></p><p>今天到期待办：<b>${state.tasks.filter(t=>t.status==='待办'&&t.due_date===state.today).length}</b></p><p>尚未安排待办的在跟线索：<b>${noTask}</b></p><p>已确认意向、尚待正式入池：<b>${state.prospects.filter(p=>p.stage==='有效意向').length}</b></p>`;
}
function renderCampaigns(){
  $('campaignList').innerHTML=state.campaigns.map(c=>`<article class="card"><div class="rowhead"><h3>${esc(c.name)}</h3><button data-edit-campaign="${esc(c.id)}">编辑</button></div><span class="tag">${roles[c.role]}</span><span class="tag">${c.active?'启用':'停用'}</span><p>${esc(c.channel)} · 负责人 ${esc(c.owner)} · ${esc(c.start_date)} 至 ${esc(c.end_date)}</p><p class="detail">${esc(c.proposition)}</p><p>核实目标：${c.metrics.qualified} / ${c.target_qualified}</p><progress value="${c.metrics.qualified}" max="${c.target_qualified}"></progress><p>有效意向 ${c.metrics.engaged} · 已入池 ${c.metrics.converted} · 净新增档案 ${c.metrics.created_profiles}</p><p class="muted">预算 ¥${c.budget.toFixed(2)} / 实际投入 ¥${c.actual_cost.toFixed(2)} · 单条核实成本 ${c.metrics.cost_per_qualified==null?'—':`¥${c.metrics.cost_per_qualified.toFixed(2)}`}</p><button data-add-prospect="${esc(c.id)}">登记本项目线索</button></article>`).join('')||'<div class="card empty">先从“拓展策略”选择主体，或建立自己的拓展项目。</div>';
}
function renderProspects(){
  const query=$('prospectSearch').value.toLowerCase(),role=$('roleFilter').value,stage=$('stageFilter').value;
  const items=state.prospects.filter(p=>(!role||p.role===role)&&(!stage||p.stage===stage)&&[p.name,p.owner,p.source,...p.regions,...p.scenarios].join(' ').toLowerCase().includes(query));
  $('prospectList').innerHTML=items.map(p=>`<article class="card"><div class="rowhead"><h3>${esc(p.name)}</h3>${p.converted_at?'':`<button data-edit-prospect="${esc(p.id)}">补充画像</button>`}</div><span class="tag">${roles[p.role]}</span><span class="tag">${esc(p.stage)}</span><span class="tag ${p.contact_policy==='拒绝联系'?'danger':''}">${esc(p.contact_policy)}</span><div class="detail"><p>地区：${esc(p.regions.join('；')||'待补充')} · 场景：${esc(p.scenarios.join('；')||'待补充')}</p><p>来源：${esc(p.source)} · 负责人：${esc(p.owner)}</p><p>业务匹配：${esc(p.fit_note||'尚未核实')}</p>${p.existing_profile_id&&!p.converted_at?'<p class="notice">正式档案已有同名同角色机构，入池时将要求关联已有档案。</p>':''}</div><details><summary>来源、联系方式与历史记录</summary><p class="detail">${esc(p.source_reference)}</p><p>业务联系：${esc(p.contact||'待核实')}</p><p class="detail">依据：${esc(p.evidence||'待补充')}</p><p class="detail">备注：${esc(p.notes)}</p>${p.events.map(e=>`<div class="event"><b>${esc(e.stage)}</b> · <small>${esc(e.at)}</small><p>${esc(e.note)}</p></div>`).join('')}</details>${nextStages[p.stage]?`<form data-progress="${esc(p.id)}"><label>阶段推进 / 记录实际沟通</label><select name="stage">${[p.stage,...nextStages[p.stage]].map(s=>`<option>${s}</option>`).join('')}</select><textarea name="note" required maxlength="2000" placeholder="填写核实结果、实际触达或对方确认的下一步，不以计划代替结果"></textarea><div class="actions"><button class="primary">记录进展</button><button type="button" data-task="${esc(p.id)}">安排任务</button>${p.stage==='有效意向'?`<button type="button" data-convert="${esc(p.id)}">${p.existing_profile_id?'关联已有正式档案':'确认转入正式档案'}</button>`:''}</div></form>`:''}${p.converted_at?'<p><a href="/channels">已衔接渠道协作工作台，继续记录客户需求与三方协作</a></p>':''}</article>`).join('')||'<div class="card empty">暂无符合条件的线索。可手动登记或批量导入已有名单。</div>';
}
function renderTasks(){
  const filter=$('taskFilter').value;
  const items=state.tasks.filter(t=>!filter||(filter==='overdue'?t.overdue:t.status===filter)).sort((a,b)=>a.due_date.localeCompare(b.due_date));
  $('taskList').innerHTML=items.map(t=>`<article class="card"><h3>${esc(t.action)}</h3><span class="tag ${t.overdue?'danger':''}">${t.overdue?'逾期待办':esc(t.status)}</span><p>${esc(state.prospects.find(p=>p.id===t.prospect_id)?.name||'记录不存在')} · ${esc(t.kind)}</p><p>负责人 ${esc(t.owner)} · 截止 ${esc(t.due_date)}</p>${t.status==='待办'?`<form data-complete="${esc(t.id)}"><label>实际完成结果 *</label><textarea name="outcome" required maxlength="2000"></textarea><div class="actions"><button class="primary">完成任务</button></div></form>`:`<p>${esc(t.outcome)}</p>`}</article>`).join('')||'<div class="card empty">暂无符合条件的任务。</div>';
}
async function refresh(){const results=await Promise.all([api('workspace'),fetch('/api/channels/workspace').then(async r=>{if(!r.ok)throw new Error('产品与正式档案读取失败');return r.json();})]);state=results[0];channel=results[1];renderDashboard();renderCampaigns();renderProspects();renderTasks();fillSelectOptions();}
function resetCampaign(){const f=$('campaignForm');f.reset();f.elements.record_id.value='';f.elements.role.disabled=false;$('campaignTitle').textContent='新建拓展项目';}
function resetProspect(){const f=$('prospectForm');f.reset();f.elements.record_id.value='';for(const k of ['role','campaign_id','referrer_id'])f.elements[k].disabled=false;for(const k of ['source','source_reference'])f.elements[k].readOnly=false;$('prospectTitle').textContent='登记潜在线索';fillSelectOptions();productChecks();}
function editCampaign(id){const c=state.campaigns.find(x=>x.id===id),f=$('campaignForm');resetCampaign();for(const k of ['name','role','channel','owner','start_date','end_date','target_qualified','budget','actual_cost','proposition'])f.elements[k].value=c[k];f.elements.record_id.value=id;f.elements.active.checked=c.active;f.elements.role.disabled=true;$('campaignTitle').textContent='编辑拓展项目';tab('campaigns');f.scrollIntoView({behavior:'smooth'});}
function editProspect(id){const p=state.prospects.find(x=>x.id===id),f=$('prospectForm');resetProspect();for(const k of ['name','role','source','source_reference','owner','contact','contact_policy','evidence','fit_note','notes'])f.elements[k].value=p[k];fillSelectOptions();f.elements.campaign_id.innerHTML=campaignOptions(p.campaign_id,p.role);f.elements.referrer_id.innerHTML='<option value="">无 / 尚未登记</option>'+channel.profiles.filter(x=>x.active||x.id===p.referrer_id).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');f.elements.referrer_id.value=p.referrer_id;for(const k of ['regions','customer_types','scenarios','capabilities'])f.elements[k].value=p[k].join('；');f.elements.record_id.value=id;for(const k of ['role','campaign_id','referrer_id'])f.elements[k].disabled=true;for(const k of ['source','source_reference'])f.elements[k].readOnly=true;productChecks(p.product_ids);$('prospectTitle').textContent='补充画像（首次来源保留）';tab('prospects');f.scrollIntoView({behavior:'smooth'});}
const playbooks={manufacturer:{name:'场景设备缺口 · 厂家拓展试点',channel:'产品品牌核实 / 展商名录 / 伙伴引荐',proposition:'围绕已选场景梳理产品能力缺口，邀请厂家提供产品资料与技术对接人，推进一次联合技术交流。'},dealer:{name:'重点区域 · 经销商拓展试点',channel:'厂家引荐 / 区域活动 / 渠道转介绍',proposition:'提供场景选型资料与产品培训，核实经销商服务区域、客户类型和推广能力，推进一次联合客户沟通。'},customer:{name:'重点应用场景 · 终端客户拓展试点',channel:'场景内容 / 技术活动 / 需求线索 / 伙伴引荐',proposition:'以具体研究任务切入，提供方案梳理与设备选型沟通，确认研究方向、需求负责人和下一步验证行动。'}};
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{
  if(b.dataset.tab)tab(b.dataset.tab);
  if(b.id==='resetCampaign')resetCampaign();if(b.id==='resetProspect')resetProspect();
  if(b.dataset.playbook){resetCampaign();const f=$('campaignForm'),p=playbooks[b.dataset.playbook];f.elements.role.value=b.dataset.playbook;for(const k of ['name','channel','proposition'])f.elements[k].value=p[k];tab('campaigns');}
  if(b.dataset.editCampaign)editCampaign(b.dataset.editCampaign);
  if(b.dataset.editProspect)editProspect(b.dataset.editProspect);
  if(b.dataset.addProspect){const c=state.campaigns.find(x=>x.id===b.dataset.addProspect);resetProspect();const f=$('prospectForm');f.elements.role.value=c.role;fillSelectOptions();f.elements.campaign_id.value=c.id;f.elements.owner.value=c.owner;f.elements.source.value=c.channel;tab('prospects');}
  if(b.dataset.task){tab('tasks');const p=state.prospects.find(x=>x.id===b.dataset.task);$('taskForm').elements.prospect_id.value=p.id;$('taskForm').elements.owner.value=p.owner;}
  if(b.dataset.convert){b.disabled=true;const p=state.prospects.find(x=>x.id===b.dataset.convert);await api(`prospects/${p.id}/convert`,'POST',{existing_profile_id:p.existing_profile_id||''});await refresh();message('已衔接正式档案，可在渠道协作工作台继续管理。');}
  if(b.id==='previewImport'||b.id==='commitImport'){
    b.disabled=true;const commit=b.id==='commitImport';
    let payload;
    if(commit){if(!importPreview)throw new Error('请先重新预检');payload={...importPreview,commit:true};}
    else{const file=$('importFile').files[0];if(!file)throw new Error('请选择 UTF-8 CSV 文件');if(file.size>500000)throw new Error('文件过大，请拆分到 200 行以内');const csv_text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());payload={csv_text,campaign_id:$('importCampaign').value,commit:false};}
    const result=await api('import','POST',payload);
    $('importResult').innerHTML=`<p>本批 ${result.rows.length} 条，错误 ${result.errors} 条，已导入 ${result.imported} 条。</p><table><thead><tr><th>行号</th><th>机构</th><th>结果</th></tr></thead><tbody>${result.rows.map(r=>`<tr><td>${r.row}</td><td>${esc(r.name)}</td><td class="detail">${r.ok?'通过':esc(r.error)}</td></tr>`).join('')}</tbody></table>`;
    importPreview=!commit&&!result.errors?{csv_text:payload.csv_text,campaign_id:payload.campaign_id}:null;
    $('commitImport').disabled=!importPreview;
    if(result.committed){await refresh();message('名单已导入发现池，后续请安排核实任务。');}else if(result.errors)message('预检存在错误，本批未写入；请修改文件后重试。',true);
  }
}catch(error){message(error.message,true);}finally{if(b.id!=='commitImport')b.disabled=false;else b.disabled=!importPreview;}});
document.addEventListener('submit',async e=>{e.preventDefault();const f=e.target,id=f.getAttribute('id'),b=f.querySelector('button.primary');if(b)b.disabled=true;const values=Object.fromEntries(new FormData(f));try{
  if(id==='campaignForm'){const key=values.record_id;delete values.record_id;values.role=f.elements.role.value;values.active=f.elements.active.checked;for(const k of ['target_qualified','budget','actual_cost'])values[k]=Number(values[k]);await api(key?`campaigns/${key}`:'campaigns',key?'PUT':'POST',values);await refresh();resetCampaign();}
  else if(id==='prospectForm'){const key=values.record_id;delete values.record_id;for(const k of ['role','campaign_id','referrer_id'])values[k]=f.elements[k].value;for(const k of ['regions','customer_types','scenarios','capabilities'])values[k]=split(values[k]);values.product_ids=selectedProducts();await api(key?`prospects/${key}`:'prospects',key?'PUT':'POST',values);await refresh();resetProspect();}
  else if(id==='taskForm'){await api('tasks','POST',values);f.reset();await refresh();}
  else if(f.dataset.progress){await api(`prospects/${f.dataset.progress}/progress`,'POST',values);await refresh();}
  else if(f.dataset.complete){await api(`tasks/${f.dataset.complete}/complete`,'POST',values);await refresh();}
  message('已保存到本机。');
}catch(error){message(error.message,true);}finally{if(b)b.disabled=false;}});
for(const id of ['prospectSearch','roleFilter','stageFilter'])$(id).addEventListener(id==='prospectSearch'?'input':'change',renderProspects);
$('taskFilter').addEventListener('change',renderTasks);
$('prospectForm').elements.role.addEventListener('change',fillSelectOptions);
$('productSearch').addEventListener('input',e=>{$('productChecks').querySelectorAll('label').forEach(l=>l.hidden=!l.dataset.search.includes(e.target.value.toLowerCase()));});
for(const id of ['importFile','importCampaign'])$(id).addEventListener('change',()=>{importPreview=null;$('commitImport').disabled=true;$('importResult').textContent='文件或项目已变更，请重新预检。';});
refresh().then(()=>{resetCampaign();resetProspect();}).catch(e=>message(`加载失败：${e.message}`,true));
