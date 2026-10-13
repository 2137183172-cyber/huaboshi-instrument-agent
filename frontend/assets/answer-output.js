window.HuaboshiOutput = (() => {
  const escape = (value) => String(value || '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  function publicDeviceName(item) {
    let name = String(item?.name || '').trim();
    const model = String(item?.model || '').trim();
    if (!name || !model || ['-', '——'].includes(model) || !name.includes(model)) return name;
    const start = name.indexOf(model);
    const end = start + model.length;
    if (start > 0 && end < name.length && '（('.includes(name[start - 1]) && '）)'.includes(name[end])) {
      name = name.slice(0, start - 1) + name.slice(end + 1);
    } else {
      name = name.replace(model, '');
    }
    return name.replace(/\s+/gu, ' ').replace(/[ ；;,，]+$/gu, '').trim();
  }
  function publicText(plan, value) {
    let text = String(value || '');
    const replacements = (plan?.equipment_table || []).map((item) => {
      const raw = String(item?.name || '');
      return [raw, publicDeviceName(item)];
    }).filter(([raw, visible]) => raw && raw !== visible).sort((a, b) => b[0].length - a[0].length);
    replacements.forEach(([raw, visible]) => { text = text.split(raw).join(visible); });
    return text;
  }
  function mindmap(data) {
    if (!data.scenario_plan?.steps?.length) return '';
    const plan = data.scenario_plan || {};
    const path = data.research_path || {};
    const branches = [];
    for (const step of (plan.steps || path.stages || [])) {
      const details = [step.goal, step.samples && `样本：${step.samples}`, step.role && `角色：${step.role}`, step.capabilities, step.handoff && `衔接：${step.handoff}`].filter(Boolean).map((value) => publicText(plan, value));
      for (const [label, items] of Object.entries(step.relations || {})) {
        if (Array.isArray(items) && items.length) details.push(publicText(plan, `${label}：${items.join('；')}`));
      }
      if (step.quality_gate) details.push(publicText(plan, `质量检查：${step.quality_gate}`));
      if (step.boundary) details.push(publicText(plan, `适用边界：${step.boundary}`));
      if (step.output) details.push(publicText(plan, `输出结果：${step.output}`));
      branches.push({ title: step.name || '研究环节', details });
    }
    const devices = data.recommended_devices || [];
    if (devices.length) branches.push({ title: '推荐设备', details: devices.map((device) => [device.name, device.scenario_step || device.workflow_role || device.applications].filter(Boolean).join('：')) });
    if (!branches.length) {
      const lines = String(data.answer || '').split(/\n+/).map((line) => line.replace(/^\s*(?:#{1,6}|[-*+]|\d+[.、])\s*/, '').replace(/\*\*/g, '').trim()).filter(Boolean);
      for (const line of lines.slice(0, 16)) branches.push({ title: line, details: [] });
    }
    if (!branches.length) return '';
    return `<details class="hb-mindmap" open><summary>方案思维导图</summary><div class="hb-map-tree"><strong class="hb-map-root">${escape(plan.title || path.title || '华博士方案')}</strong><ul>${branches.map((branch) => `<li><details open><summary>${escape(branch.title)}</summary>${branch.details.length ? `<ul>${branch.details.map((detail) => `<li>${escape(detail)}</li>`).join('')}</ul>` : ''}</details></li>`).join('')}</ul></div></details>`;
  }
  async function download(button) {
    const answer = button.closest('.hb-answer');
    const status = button.closest('.hb-output-actions').querySelector('.hb-export-status');
    button.disabled = true;
    status.textContent = '正在生成文档…';
    try {
      const plan = JSON.parse(decodeURIComponent(button.dataset.plan));
      const title = plan.title || '华博士方案';
      const maps = mapImages(answer.querySelector('.hb-map-tree'));
      const headers = ['设备名称', '用途及功能'];
      const rows = (plan.equipment_table || []).map(item => [publicDeviceName(item), publicText(plan, item.applications || '-')]);
      const response = await fetch('/api/export/prepare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.slice(0, 200), maps, headers, rows }) });
      if (!response.ok) throw new Error('文档生成失败，请稍后重试');
      const result = await response.json();
      const link = document.createElement('a');
      link.href = result.download_url;
      link.textContent = '点击下载 Word';
      const preview = document.createElement('a');
      preview.href = result.preview_url;
      preview.textContent = '查看方案 / 手机下载';
      status.replaceChildren(link, document.createTextNode(' · '), preview);
      if (/Android|iPhone|iPad|iPod|MicroMessenger/i.test(navigator.userAgent)) {
        window.location.assign(result.preview_url);
      } else {
        link.click();
      }
    } catch (error) {
      status.textContent = error.message || '下载失败，请重试';
    } finally {
      button.disabled = false;
    }
  }
  function actions(data) {
    if (!data.scenario_plan?.steps?.length) return '';
    if (data.scenario_plan.catalog_download) {
      const url = data.scenario_plan.catalog_download;
      const mobile = /Android|iPhone|iPad|iPod|MicroMessenger/i.test(navigator.userAgent);
      return `<div class="hb-output-actions"><a class="stage-open" href="${escape(mobile ? url.replace(/\/download$/, '/view') : url)}">下载完整方案word文档</a></div>`;
    }
    return `<div class="hb-output-actions"><button type="button" class="stage-open" data-plan="${escape(encodeURIComponent(JSON.stringify(data.scenario_plan)))}" onclick="HuaboshiOutput.download(this)">下载完整方案word文档</button><span class="hb-export-status" role="status"></span></div>`;
  }
  // Render the same visible tree as high-resolution, page-sized images for Word.
  function mapImages(tree) {
    const canvas = document.createElement('canvas');
    canvas.width = 1600; canvas.height = 2000;
    const ctx = canvas.getContext('2d');
    ctx.scale(2, 2);
    const images = [];
    let y;
    function start() {
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 800, 1000);
      ctx.fillStyle = '#eaf6f8'; ctx.fillRect(20, 16, 760, 72);
      ctx.fillStyle = '#087b8d'; ctx.font = 'bold 21px "Microsoft YaHei", sans-serif';
      ctx.fillText((tree.querySelector('.hb-map-root')?.textContent || '方案思维导图').slice(0, 34), 36, 58);
      y = 116;
    }
    function save() {
      const cropped = document.createElement('canvas');
      cropped.width = canvas.width;
      cropped.height = Math.min(canvas.height, Math.ceil((y + 16) * 2));
      cropped.getContext('2d').drawImage(canvas, 0, 0);
      images.push(cropped.toDataURL('image/png').split(',')[1]);
    }
    function line(text, level, bold) {
      const x = level ? 78 : 46;
      ctx.font = `${bold ? 'bold ' : ''}18px "Microsoft YaHei", sans-serif`;
      let current = '';
      const lines = [];
      for (const character of text) {
        if (character === '\n' || ctx.measureText(current + character).width > 740 - x) { lines.push(current); current = ''; }
        if (character !== '\n') current += character;
      }
      if (current) lines.push(current);
      for (const value of lines) {
        if (y > 950) { save(); start(); ctx.font = `${bold ? 'bold ' : ''}18px "Microsoft YaHei", sans-serif`; }
        ctx.strokeStyle = '#92bdc5'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x - 18, y - 24); ctx.lineTo(x - 18, y + 8); ctx.moveTo(x - 18, y - 6); ctx.lineTo(x - 5, y - 6); ctx.stroke();
        ctx.fillStyle = bold ? '#126576' : '#33434a'; ctx.fillText(value, x, y); y += 29;
      }
      y += bold ? 4 : 2;
    }
    start();
    for (const branch of tree.querySelectorAll(':scope > ul > li')) {
      line(branch.querySelector('summary').textContent, 0, true);
      for (const detail of branch.querySelectorAll('ul > li')) line(detail.textContent, 1, false);
      y += 10;
    }
    save();
    return images;
  }
  return { mindmap, download, actions };
})();
