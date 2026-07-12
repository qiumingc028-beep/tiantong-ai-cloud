(function(){
  'use strict';
  const API='/api/v2/alpha-workflows';
  const STAGE_LABELS={orchestrator:'Orchestrator',research:'Research',knowledge:'Knowledge',skills:'Skill',skill:'Skill',execution:'Agent Runtime',agent_runtime:'Agent Runtime',verification:'Verification',audit:'Audit',feedback:'Knowledge 回流',dashboard:'结果展示',workflow:'全链路',task_center:'任务创建',recovery:'恢复'};
  const $=id=>document.getElementById(id);
  const text=value=>value===null||value===undefined||value===''?'暂无数据':String(value);
  const escapeHtml=value=>text(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const formatTime=value=>value?new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short',hour12:false}).format(new Date(value)):'时间未记录';
  const stageLabel=code=>STAGE_LABELS[code]||text(code);

  async function request(path,options={}){
    const response=await fetch(`${API}${path}`,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    let payload={};
    try{payload=await response.json();}catch(_error){payload={};}
    if(response.status===401){location.href='/login.html';throw new Error('登录已失效，请重新登录');}
    if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'服务暂时不可用，请稍后重试');
    return payload;
  }

  function showMessage(message,type='loading'){
    const node=$('page-message'); if(!node)return;
    node.className=`message message-${type}`;node.textContent=message;node.hidden=false;
  }

  function runTitle(run){return run.workflow_context?.task_title||run.scenario_title||run.dashboard_summary?.['任务标题']||'Alpha 验证任务';}
  function nextStep(run){return run.dashboard_summary?.['下一步']||`当前阶段：${stageLabel(run.current_stage||run.workflow_context?.current_stage)}`;}

  async function initList(){
    document.querySelector('[data-action="refresh"]').addEventListener('click',loadList);
    $('start-form').addEventListener('submit',startRun);
    await loadList();
  }

  async function loadList(){
    showMessage('正在加载 Alpha 任务…');
    try{
      const [dashboard,scenarios]=await Promise.all([request('/dashboard'),request('/scenarios')]);
      const runs=dashboard.runs||[];
      $('overview').hidden=false;
      $('metric-total').textContent=dashboard.run_count??runs.length;
      $('metric-active').textContent=text(dashboard.active_count);
      $('metric-completed').textContent=text(dashboard.completed_count);
      $('metric-attention').textContent=text(dashboard.attention_count);
      renderScenarios(scenarios.items||[]);renderRuns(runs);
      showMessage(runs.length?'任务进度已更新。':'还没有 Alpha 任务，可以从下方开始第一次验证。',runs.length?'success':'empty');
    }catch(error){showMessage(error.message,'error');renderRuns([],'任务列表加载失败，请稍后重试。');}
  }

  function renderScenarios(items){
    const select=$('scenario-select');
    const enabled=items.filter(item=>item.enabled);
    select.innerHTML=enabled.length?enabled.map(item=>`<option value="${escapeHtml(item.scenario_code)}" data-input="${escapeHtml(item.default_input_text||'')}">${escapeHtml(item.title)}</option>`).join(''):'<option value="">暂无可用场景</option>';
    select.disabled=!enabled.length;
    const applyDefault=()=>{const option=select.selectedOptions[0];if(option&&option.dataset.input&&!$('workflow-input').value)$('workflow-input').value=option.dataset.input;};
    select.onchange=applyDefault;applyDefault();
  }

  function renderRuns(runs,errorText){
    const list=$('run-list');
    if(!runs.length){list.innerHTML=`<div class="empty">${escapeHtml(errorText||'暂无运行记录。完成上方输入后即可开始。')}</div>`;return;}
    list.innerHTML=runs.map(run=>`<article class="run-card">
      <div><div class="run-title"><span class="badge">${escapeHtml(run.status)}</span><h3>${escapeHtml(runTitle(run))}</h3></div>
      <div class="run-meta"><span>当前阶段：${escapeHtml(stageLabel(run.current_stage))}</span><span>风险：${escapeHtml(run.risk_score??'待评分')}</span><span>质量：${escapeHtml(run.quality_score??'待评分')}</span><span>${escapeHtml(formatTime(run.updated_at||run.created_at))}</span></div></div>
      <a class="button button-light" href="/alpha-workflow-detail.html?run_id=${encodeURIComponent(run.run_id)}">查看进度</a>
    </article>`).join('');
  }

  async function startRun(event){
    event.preventDefault();const button=event.submitter;const input=$('workflow-input').value.trim();
    if(!input){showMessage('请先填写研究目标。','empty');return;}
    button.disabled=true;showMessage('正在从 Orchestrator 启动 Alpha 验证…');
    try{
      const payload={input_text:input};const scenario=$('scenario-select').value;if(scenario)payload.scenario_code=scenario;
      const result=await request('/demo',{method:'POST',body:JSON.stringify(payload)});
      const runId=result.run?.run_id;if(!runId)throw new Error('任务已提交，但接口未返回运行编号');
      location.href=`/alpha-workflow-detail.html?run_id=${encodeURIComponent(runId)}`;
    }catch(error){showMessage(error.message,'error');button.disabled=false;}
  }

  let detail={run:null,trace:null,audit:null,stages:null,report:null};
  async function initDetail(){
    const runId=new URLSearchParams(location.search).get('run_id');
    document.querySelector('[data-action="refresh"]').addEventListener('click',()=>loadDetail(runId));
    document.querySelector('[data-action="close-report"]').addEventListener('click',()=>{$('report-panel').hidden=true;});
    $('report-button').addEventListener('click',toggleReport);
    if(!runId){showMessage('链接中缺少运行编号，请返回任务列表重新选择。','error');return;}
    await loadDetail(runId);
  }

  async function loadDetail(runId){
    showMessage('正在读取全链路进度…');$('detail-content').hidden=true;
    try{
      const [runData,trace,audit,stages,report]=await Promise.all([
        request(`/runs/${encodeURIComponent(runId)}`),request(`/runs/${encodeURIComponent(runId)}/trace`),request(`/runs/${encodeURIComponent(runId)}/audit`),
        request(`/runs/${encodeURIComponent(runId)}/stages`),request(`/runs/${encodeURIComponent(runId)}/report`)
      ]);
      detail={run:runData.run,trace,audit,stages,report};renderDetail();$('detail-content').hidden=false;showMessage('全链路进度已更新。','success');
    }catch(error){showMessage(error.message,'error');}
  }

  function renderDetail(){
    const run=detail.run,context=run.workflow_context||{};
    $('task-title').textContent=runTitle(run);$('task-next').textContent=nextStep(run);
    $('run-status').textContent=text(run.status);$('current-stage').textContent=`当前阶段：${stageLabel(run.current_stage||context.current_stage)}`;
    $('risk-score').textContent=run.risk_score??'—';$('risk-level').textContent=run.risk_level?`${run.risk_level}风险`:'尚未评分';
    $('quality-score').textContent=run.quality_score??'—';$('quality-grade').textContent=text(run.quality_grade||'尚未评分');
    const approvals=approvalIds(run,context);
    $('approval-status').textContent=approvals.length?'已有审批记录':'暂无数据';$('approval-count').textContent=approvals.length?`${approvals.length} 条审批引用`:'暂无数据';
    renderActions(run);renderStages();renderExecution(run);renderKnowledge(run);renderAssurance(run);renderRecovery(run);renderSummary();renderAudit();renderTrace(run);
  }

  function stageEvidence(code){
    const aliases={execution:['execution','agent_runtime'],feedback:['feedback'],audit:['audit'],skills:['skills','skill']};
    const candidates=new Set(aliases[code]||[code]);
    const spans=detail.stages?.spans||detail.trace?.spans||[];const events=detail.stages?.events||detail.trace?.events||[];
    return [...spans,...events].filter(item=>candidates.has(item.stage)).at(-1)||null;
  }
  function renderStages(){
    const spans=detail.stages?.spans||[];const events=detail.stages?.events||[];const rows=spans.length?spans:events;
    $('stage-flow').innerHTML=rows.length?rows.map(item=>`<li class="stage-step" title="${escapeHtml(item.message)}"><i class="stage-dot"></i><strong>${escapeHtml(stageLabel(item.stage))}</strong><span>${escapeHtml(item.status)}</span></li>`).join(''):'<li class="empty">暂无数据</li>';
    $('progress-text').textContent=rows.length?`服务端返回 ${rows.length} 个阶段记录`:'暂无数据';
  }

  function renderExecution(run){
    const exec=stageEvidence('execution');const skill=stageEvidence('skills');
    $('execution-facts').innerHTML=facts([
      ['AI 员工','暂无数据'],['员工执行状态',exec?.status],['Research 来源数量','暂无数据'],
      ['Agent Execution',run.agent_execution_id],['Skill',run.skill_id],['Skill 版本',run.skill_version_id],['Skill 调用状态',skill?.status]
    ]);
  }
  function renderKnowledge(run){
    const knowledge=stageEvidence('knowledge');const feedback=stageEvidence('feedback');
    $('knowledge-facts').innerHTML=[
      box('候选与正式知识状态',knowledge?.message||knowledge?.status),box('知识资产',run.knowledge_asset_id),
      box('知识版本',run.knowledge_version_id),box('知识引用','暂无数据'),
      box('Knowledge 回流',feedback?.message||feedback?.status)
    ].join('');
  }
  function renderAssurance(run){
    const approvals=approvalIds(run,run.workflow_context||[]);const verification=stageEvidence('verification');const audit=stageEvidence('audit');
    $('assurance-facts').innerHTML=[box('审批引用',approvals.length?approvals.join('；'):null),box('Verification ID',run.verification_id),box('Verification',verification?.status||verification?.message),box('Audit',audit?.status||audit?.message||auditTimelineStatus())].join('');
  }
  function renderRecovery(run){
    const events=(detail.audit?.timeline||[]).filter(item=>/recover|恢复/i.test(`${item.event_code||''}${item.message||''}`));
    $('recovery-facts').innerHTML=[box('失败原因',run.failure_reason),box('当前恢复状态',run.recovery_status),box('恢复来源',run.recovered_from_run_id),box('恢复记录',events.length?events.map(item=>item.message||item.event_code).join('；'):null)].join('');
  }
  function renderSummary(){
    const report=detail.report||{};const summary=report.dashboard_summary||detail.run.dashboard_summary||{};
    $('report-summary').innerHTML=Object.keys(summary).length?Object.entries(summary).map(([key,value])=>`<div><strong>${escapeHtml(key)}：</strong>${escapeHtml(value)}</div>`).join(''):'最终交付摘要尚未生成。';
    const finalReport=report.report_content;const available=finalReport!==null&&finalReport!==undefined&&finalReport!=='';
    $('report-button').disabled=!available;$('report-button').textContent=available?'查看最终报告':'最终报告暂无数据';
    $('report-title').textContent='最终研究报告';$('report-content').textContent=available?(typeof finalReport==='string'?finalReport:JSON.stringify(finalReport,null,2)):'暂无数据';
  }
  function toggleReport(){$('report-panel').hidden=!$('report-panel').hidden;if(!$('report-panel').hidden)$('report-panel').scrollIntoView({behavior:'smooth'});}
  function renderAudit(){
    const items=detail.audit?.timeline||[];$('audit-count').textContent=`${items.length} 条审计记录`;
    $('audit-timeline').innerHTML=items.length?items.map(item=>`<article class="timeline-item"><h3>${escapeHtml(item.message||stageLabel(item.stage))} <span class="badge">${escapeHtml(item.status)}</span></h3><p>${escapeHtml(stageLabel(item.stage))} · ${escapeHtml(item.event_code)}</p><time>${escapeHtml(formatTime(item.created_at))}</time></article>`).join(''):'<div class="empty">暂无审计记录。</div>';
  }
  function renderTrace(run){
    $('trace-facts').innerHTML=facts([['Trace ID',run.trace_id],['Root Span ID',run.root_span_id],['Workflow ID',run.workflow_id],['Task ID',run.task_id],['Orchestrator Run',run.orchestrator_run_id]]);
    const spans=detail.trace?.spans||[];const events=detail.trace?.events||[];
    const rows=spans.length?spans:events;
    $('span-list').innerHTML=rows.length?rows.map(span=>`<div class="span"><strong>${escapeHtml(span.span_name||span.message||stageLabel(span.stage))}</strong> · ${escapeHtml(span.status)}<div class="mono">span_id：${escapeHtml(span.span_id)}</div><div class="mono">parent_span_id：${span.parent_span_id===null?'根节点（无父级）':escapeHtml(span.parent_span_id)}</div></div>`).join(''):'<div class="empty">暂无数据</div>';
  }
  function renderActions(run){
    const actions=['<button class="button button-light" data-run-action="refresh">刷新进度</button>'];
    if(detail.report?.report_content)actions.push('<button class="button" data-run-action="report">查看最终报告</button>');
    normalizeActions(run.available_actions).forEach(action=>{if(action==='recover')actions.push('<button class="button" data-run-action="recover">从检查点恢复</button>');if(action==='cancel')actions.push('<button class="button button-danger" data-run-action="cancel">取消任务</button>');});
    $('primary-actions').innerHTML=actions.join('');
    $('primary-actions').querySelectorAll('[data-run-action]').forEach(button=>button.addEventListener('click',()=>handleAction(button.dataset.runAction)));
  }
  function handleAction(action){
    if(action==='report'){toggleReport();return;}if(action==='refresh'){loadDetail(detail.run.run_id);return;}
    const recover=action==='recover';$('reason-title').textContent=recover?'从检查点恢复':'取消 Alpha 任务';$('reason-help').textContent=recover?'系统会按契约创建新的恢复运行，并保留原任务审计记录。':'取消后任务不会继续执行。';
    $('reason-confirm').className=`button ${recover?'':'button-danger'}`;$('reason-dialog').showModal();
    $('reason-form').onsubmit=async event=>{if(event.submitter?.value==='cancel')return;event.preventDefault();$('reason-confirm').disabled=true;try{const current=detail.run.run_id;const result=await request(`/runs/${encodeURIComponent(current)}/${recover?'recover':'cancel'}`,{method:'POST',body:JSON.stringify({reason:$('reason-input').value.trim()||null})});$('reason-dialog').close();const next=result.run?.run_id||current;if(next!==current)history.replaceState(null,'',`?run_id=${encodeURIComponent(next)}`);await loadDetail(next);}catch(error){showMessage(error.message,'error');$('reason-dialog').close();}finally{$('reason-confirm').disabled=false;}};
  }
  function facts(rows){return rows.map(([key,value])=>`<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join('');}
  function box(label,value){return `<div class="fact-box"><strong>${escapeHtml(label)}</strong><br>${escapeHtml(value)}</div>`;}
  function approvalIds(run,context){return Array.isArray(run.approval_ids)?run.approval_ids:Array.isArray(context.approval_ids)?context.approval_ids:[];}
  function auditTimelineStatus(){const rows=detail.audit?.timeline||[];return rows.length?rows.at(-1).status:null;}
  function normalizeActions(value){return Array.isArray(value)?value.map(item=>typeof item==='string'?item:item?.code||item?.action).filter(Boolean):[];}

  const page=document.body.dataset.page;if(page==='list')initList();if(page==='detail')initDetail();
})();
