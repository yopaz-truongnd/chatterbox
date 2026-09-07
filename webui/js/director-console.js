/** Director Console: a thin REST adapter over authoritative workflow services. */
let directorWorkflows = [];
let directorActive = null;
let directorReview = null;
let directorSource = null;
let directorRevisions = null;
let directorOperations = [];
let directorBeat = null;
let directorView = 'workspace';
let directorPollTimer = null;

const directorInputClass = 'bg-[#0E0C12] border border-[#3F3A46] rounded-lg px-3 py-2 text-xs text-white focus:border-purple-500 focus:outline-hidden';

async function directorFetch(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.message || `HTTP ${response.status}`);
  return body;
}

function toggleDirectorCreate() {
  document.getElementById('directorCreate')?.classList.toggle('hidden');
}

async function startDirectorWorkflow() {
  const script = document.getElementById('directorScript').value.trim();
  if (!script) return showToast('warning', 'Source script is required.');
  const policy = {
    provider: document.getElementById('directorProvider').value,
    model: document.getElementById('directorModel').value.trim() || null,
    output_formats: document.getElementById('directorMp3').checked ? ['wav', 'mp3'] : ['wav'],
    require_final_approval: document.getElementById('directorFinalGate').checked,
  };
  try {
    const workflow = await directorFetch('/api/v1/voice-workflows', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: document.getElementById('directorTitle').value.trim() || null,
        project_id: document.getElementById('directorProjectId').value.trim() || null,
        script_text: script, language: 'en', policy,
      }),
    });
    document.getElementById('directorCreate').classList.add('hidden');
    showToast('success', 'Production workflow started.');
    await loadDirectorWorkflows();
    openDirectorWorkflow(workflow.workflow_id);
  } catch (error) { showToast('error', escapeHtml(error.message)); }
}

async function loadDirectorWorkflows() {
  const list = document.getElementById('directorWorkflowList');
  if (!list) return;
  try {
    directorWorkflows = await directorFetch('/api/v1/voice-workflows?limit=100');
    document.getElementById('directorCount').textContent = `${directorWorkflows.length} workflows`;
    list.innerHTML = directorWorkflows.length ? directorWorkflows.map(workflow => {
      const progress = workflow.steps.length ? Math.round(workflow.steps.filter(s => ['completed', 'skipped'].includes(s.status)).length * 100 / workflow.steps.length) : 0;
      return `<button onclick="openDirectorWorkflow('${escapeHtml(workflow.workflow_id)}')" class="w-full text-left p-3 rounded-lg border ${directorActive?.workflow_id === workflow.workflow_id ? 'border-purple-500' : 'border-[#3F3A46]'} bg-[#0E0C12] hover:bg-[#231F2A]">
        <div class="flex justify-between gap-2"><strong class="text-xs text-white truncate">${escapeHtml(workflow.project_id)}</strong>${directorStatusChip(workflow.status)}</div>
        <div class="mt-2 h-1 bg-[#3F3A46] rounded"><div class="h-1 bg-purple-500 rounded" style="width:${progress}%"></div></div>
        <div class="mt-1 flex justify-between text-[10px] text-slate-500"><span>${escapeHtml(workflow.policy.provider)} / ${escapeHtml(workflow.policy.model || 'default')}</span><span>${progress}%</span></div>
      </button>`;
    }).join('') : '<p class="text-xs text-slate-500 py-6 text-center">No productions yet.</p>';
    if (directorActive) {
      const fresh = directorWorkflows.find(w => w.workflow_id === directorActive.workflow_id);
      if (fresh) { directorActive = fresh; renderDirectorShell(); }
    }
  } catch (error) { list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`; }
}

function directorStatusChip(status) {
  const color = status === 'completed' ? 'emerald' : status === 'waiting_for_human' ? 'amber' : ['failed', 'cancelled'].includes(status) ? 'red' : 'purple';
  return `<span class="px-2 py-0.5 rounded bg-${color}-950/60 text-${color}-300 text-[10px]">${escapeHtml(status)}</span>`;
}

async function openDirectorWorkflow(workflowId) {
  try {
    directorActive = await directorFetch(`/api/v1/voice-workflows/${workflowId}`);
    [directorReview, directorSource, directorRevisions, directorOperations] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/director-review`).catch(() => null),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/script`).catch(() => null),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/revisions`).catch(() => null),
      directorFetch(`/api/v1/voice-project-jobs?project_id=${encodeURIComponent(directorActive.project_id)}&limit=20`).catch(() => []),
    ]);
    document.getElementById('directorEmpty').classList.add('hidden');
    document.getElementById('directorWorkspace').classList.remove('hidden');
    renderDirectorShell();
    scheduleDirectorPolling();
  } catch (error) { showToast('error', escapeHtml(error.message)); }
}

function renderDirectorShell() {
  const workflow = directorActive;
  document.getElementById('directorActiveTitle').textContent = directorReview?.title || workflow.project_id;
  document.getElementById('directorActiveMeta').textContent = `${workflow.workflow_id} · ${workflow.status} · updated ${workflow.updated_at}`;
  document.getElementById('directorProgress').innerHTML = workflow.steps.map(step => `<div class="rounded p-2 border border-[#3F3A46] text-center"><div class="text-[10px] ${step.status === 'completed' ? 'text-emerald-400' : step.status === 'running' ? 'text-purple-300' : 'text-slate-500'}">${escapeHtml(step.name)}</div><div class="text-[9px] text-slate-500">${escapeHtml(step.status)}</div></div>`).join('');
  const actions = document.getElementById('directorGateActions');
  const gate = workflow.human_action?.action_type;
  if (workflow.status === 'waiting_for_human' && gate) {
    const label = gate === 'narration_acceptance' ? 'Approve Narration' : gate === 'final_audio_approval' ? 'Approve Final Master' : 'Resume';
    actions.innerHTML = `<button onclick="approveDirectorGate(true)" class="px-3 py-2 rounded-lg bg-emerald-600 text-white text-xs font-bold">${label}</button><button onclick="approveDirectorGate(false)" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Reject</button>`;
  } else if (['queued', 'running', 'cancelling'].includes(workflow.status)) {
    actions.innerHTML = '<button onclick="cancelDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Cancel</button>';
  } else if (workflow.status === 'interrupted') {
    actions.innerHTML = '<button onclick="resumeDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-purple-600 text-white text-xs">Resume</button>';
  } else actions.innerHTML = '';
  renderDirectorOperations();
  renderDirectorPendingRevisions();
  if (workflow.status === 'waiting_for_human' && gate === 'narration_acceptance') directorView = 'review';
  if (workflow.status === 'waiting_for_human' && gate === 'final_audio_approval') directorView = 'delivery';
  showDirectorView(directorView);
}

function renderDirectorOperations() {
  const panel = document.getElementById('directorOperations');
  if (!panel) return;
  const visible = directorOperations.filter(op => ['queued','running','cancelling','interrupted','failed'].includes(op.status)).slice(0, 5);
  panel.classList.toggle('hidden', !visible.length);
  panel.innerHTML = visible.length ? `<h4 class="text-xs font-bold text-white mb-3">Operations</h4>${visible.map(op => `<div class="mb-3 last:mb-0"><div class="flex justify-between text-[11px]"><b>${escapeHtml(op.operation)}${op.beat_id ? ` · ${escapeHtml(op.beat_id)}` : ''}</b><span>${escapeHtml(op.status)}</span></div><div class="h-1.5 bg-[#3F3A46] rounded mt-1"><div class="h-1.5 bg-purple-500 rounded" style="width:${Math.max(0, Math.min(100, op.progress_percent || 0))}%"></div></div><div class="flex justify-between items-center mt-1 text-[9px] text-slate-500 font-mono"><span>${escapeHtml(op.id)} · ${escapeHtml(op.stage || 'queued')} · ${Math.round(op.progress_percent || 0)}%</span>${['queued','running'].includes(op.status) ? `<button onclick="cancelDirectorOperation('${escapeHtml(op.id)}')" class="text-red-400">Cancel</button>` : ''}</div></div>`).join('')}` : '';
}

function renderDirectorPendingRevisions() {
  const panel = document.getElementById('directorPendingRevisions');
  if (!panel) return;
  const pendingIds = directorRevisions?.state?.pending_revision_ids || [];
  const events = (directorRevisions?.events || []).filter(event => pendingIds.includes(event.revision_id));
  panel.classList.toggle('hidden', !events.length);
  panel.innerHTML = events.length ? `<div class="flex flex-wrap justify-between gap-3"><div><h4 class="text-xs font-bold text-amber-300">Pending revisions</h4>${events.map(event => `<p class="text-[11px] text-slate-300 mt-1"><b>${escapeHtml(event.beat_id || event.affected_beats?.join(', ') || 'Project')}</b> · ${escapeHtml(event.revision_type.replaceAll('_',' '))}</p>`).join('')}</div><button onclick="reproduceDirectorProject()" class="self-end px-3 py-2 rounded bg-amber-600 text-white text-xs font-bold">Reproduce pending revisions</button></div>` : '';
}

function showDirectorView(view) {
  directorView = view;
  document.querySelectorAll('#directorViews button').forEach(button => button.className = `px-3 py-2 rounded-lg text-xs whitespace-nowrap ${button.dataset.view === view ? 'bg-purple-600 text-white' : 'bg-[#231F2A] text-slate-300'}`);
  const content = document.getElementById('directorViewContent');
  if (!directorActive || !content) return;
  if (view === 'review') content.innerHTML = renderDirectorReview();
  else if (view === 'mix') content.innerHTML = renderDirectorMix();
  else if (view === 'delivery') renderDirectorDelivery(content);
  else content.innerHTML = renderDirectorWorkspace();
  content.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`);
}

function renderDirectorWorkspace() {
  if (!directorReview) return '<p class="text-xs text-slate-500">The project review becomes available after project creation.</p>';
  const gaps = [...directorReview.required_resource_gaps, ...directorReview.recommended_resource_gaps];
  return `<h4 class="text-xs font-bold text-white mb-1">Source script (immutable)</h4><p class="text-[9px] text-slate-500 font-mono mb-3">SHA-256 ${escapeHtml(directorSource?.sha256 || directorReview.source_script_sha256)}</p><div class="p-3 rounded bg-[#0E0C12] text-xs text-slate-300 whitespace-pre-wrap">${escapeHtml(directorSource?.script_text || directorReview.script_excerpt)}</div>
    <div class="grid md:grid-cols-2 gap-3 mt-4"><div><h4 class="text-xs font-bold text-white mb-2">VoicePlan beats</h4>${directorReview.beats.map(b => `<button onclick="openDirectorBeat('${escapeHtml(b.beat_id)}')" class="block w-full text-left p-2 mb-1 rounded bg-[#0E0C12] text-xs"><b class="text-white">${escapeHtml(b.beat_id)}</b> <span class="text-slate-400">${escapeHtml(b.emotion)} · energy ${b.energy} · ${escapeHtml(b.render_status)}</span></button>`).join('')}</div><div><h4 class="text-xs font-bold text-white mb-2">Resource readiness ${directorReview.resource_readiness ?? '—'}%</h4>${gaps.length ? gaps.map(renderDirectorGap).join('') : '<p class="text-xs text-emerald-400">No resource gaps.</p>'}</div></div>`;
}

function renderDirectorGap(gap) {
  const required = gap.priority === 'required';
  const action = gap.resource_type === 'knowledge'
    ? gap.term ? `<div class="flex gap-1 mt-2"><input class="director-input flex-1" placeholder="Approved pronunciation"><button onclick="resolveDirectorPronunciation('${escapeHtml(gap.term)}',this)" class="px-2 rounded bg-purple-700 text-[10px]">Resolve</button></div>` : '<p class="text-[10px] text-slate-500 mt-2">No structured pronunciation term provided.</p>'
    : `<div class="flex gap-1 mt-2"><input class="director-input flex-1" placeholder="Existing asset ID"><button onclick="bindDirectorResource('${escapeHtml(gap.resource_id)}',this)" class="px-2 rounded bg-purple-700 text-[10px]">Bind</button></div>`;
  return `<div class="p-2 mb-2 rounded ${required ? 'bg-red-950/30 border-red-800' : 'bg-amber-950/30 border-amber-800'} border text-xs text-amber-200"><div class="flex justify-between"><span>${escapeHtml(gap.resource_type)}: ${escapeHtml(gap.description)}</span><b class="text-[9px] uppercase">${escapeHtml(gap.priority)}</b></div>${action}</div>`;
}

function renderDirectorReview() {
  if (!directorReview?.beats?.length) return '<p class="text-xs text-slate-500">No planned beats yet.</p>';
  const gated = directorActive.status === 'waiting_for_human' && directorActive.human_action?.action_type === 'narration_acceptance';
  return `${gated ? '<div class="mb-3 p-3 rounded-lg border border-amber-500/50 bg-amber-950/30 text-xs text-amber-200">Narration approval required. Listen to and verify selected attempts before approval.</div>' : ''}<div class="space-y-3">${directorReview.beats.map(beat => `<article class="p-3 rounded-lg bg-[#0E0C12] border ${beat.selected_attempt ? 'border-emerald-700/50' : 'border-[#3F3A46]'}"><div class="flex flex-wrap justify-between gap-2"><div><b class="text-white text-xs">${escapeHtml(beat.beat_id)} · ${escapeHtml(beat.emotion)}</b><p class="text-[11px] text-slate-400 mt-1">${escapeHtml(beat.source_text)}</p></div><span class="text-[10px] text-slate-400">selected ${beat.selected_attempt ?? 'none'} · QC ${beat.qc_summary?.score ?? beat.qc_summary?.overall_score ?? '—'}</span></div>
    <div class="flex flex-wrap gap-2 mt-3">${beat.available_attempts.map(a => `<div class="flex items-center gap-1"><audio controls preload="none" class="h-8 w-44" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(a.artifact_id)}"></audio><button onclick="selectDirectorAttempt('${escapeHtml(beat.beat_id)}',${a.attempt_id})" class="px-2 py-1 rounded ${a.selected ? 'bg-emerald-700' : 'bg-[#231F2A]'} text-[10px] text-white">Attempt ${a.attempt_id}</button></div>`).join('')}</div>
    <div class="flex gap-2 mt-3"><button onclick="openDirectorBeat('${escapeHtml(beat.beat_id)}')" class="px-3 py-1 rounded bg-purple-600 text-white text-[10px]">Open Beat Review</button></div></article>`).join('')}</div>`;
}

function renderDirectorMix() {
  const done = name => directorActive.steps.find(s => s.name === name);
  return `<div class="grid md:grid-cols-3 gap-3">${['prepare_mix','mix','master'].map(name => { const step = done(name); return `<div class="p-4 rounded bg-[#0E0C12]"><b class="text-white text-xs">${name.replace('_',' ')}</b><p class="text-[11px] text-slate-400 mt-2">${escapeHtml(step?.status || 'pending')}</p><p class="text-[10px] text-slate-500">${escapeHtml(JSON.stringify(step?.result_summary || {}))}</p></div>`; }).join('')}</div>`;
}

async function renderDirectorDelivery(content) {
  content.innerHTML = '<p class="text-xs text-slate-500">Loading artifacts…</p>';
  try {
    const [data, mixPlan] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/artifacts`),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/mix-plan`).catch(() => null),
    ]);
    const gate = directorActive.human_action?.action_type === 'final_audio_approval' ? directorActive.human_action.items?.[0] : null;
    const metrics = directorOperations.find(op => op.operation === 'master' && op.status === 'completed')?.result?.metrics || {};
    const masterCard = gate ? `<div class="mb-4 p-4 rounded-lg border border-amber-500/50 bg-amber-950/20"><div class="flex flex-wrap justify-between gap-3"><div><h4 class="font-bold text-white">master.wav</h4><p class="text-[10px] text-slate-400 font-mono break-all">SHA-256 ${escapeHtml(gate.sha256)}</p><p class="text-[10px] text-slate-400">Duration ${mixPlan?.duration_ms ? `${Math.round(mixPlan.duration_ms)} ms` : 'not reported'} · Loudness ${metrics.output_lufs ?? 'not reported'} LUFS · Lineage VERIFIED</p></div><button onclick="approveDirectorGate(true)" class="px-3 py-2 rounded bg-emerald-600 text-white text-xs font-bold">Approve Final Master</button></div><audio controls preload="metadata" class="w-full h-9 mt-3" src="${escapeHtml(gate.download_url)}"></audio></div>` : '';
    const artifactsHtml = data.artifacts.map(a => {
      const lineage = directorReview?.artifact_status?.find(item => item.artifact_id === a.id);
      const valid = lineage?.exists && lineage?.fresh && lineage?.sha256 === a.sha256;
      const label = valid ? 'VERIFIED' : lineage?.exists && !lineage?.fresh ? 'STALE' : 'UNVERIFIED';
      const download = valid ? `<a class="px-3 py-1 rounded bg-purple-600 text-white text-xs" href="${escapeHtml(lineage.download_url)}">Download</a>` : '<span class="px-3 py-1 rounded bg-[#231F2A] text-slate-500 text-xs">Download disabled</span>';
      return `<div class="flex flex-wrap items-center justify-between gap-2 p-3 mb-2 rounded bg-[#0E0C12]"><div><b class="text-xs text-white">${escapeHtml(a.id)}</b><p class="text-[10px] text-slate-500 font-mono">SHA-256 ${escapeHtml(a.sha256 || 'not reported')}</p><p class="text-[10px] ${valid ? 'text-emerald-400' : 'text-amber-400'}">${label}</p></div>${download}</div>`;
    }).join('') || '<p class="text-xs text-slate-500">No deliverables yet.</p>';
    content.innerHTML = `${masterCard}<div class="mb-3">${directorStatusChip(directorActive.status)} <span class="text-xs text-slate-400 ml-2">Downloads require authoritative fresh lineage.</span></div>${artifactsHtml}`;
  } catch (error) { content.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`; }
}

async function directorMutation(url, options = {}) {
  try { const result = await directorFetch(url, options); await refreshDirectorActive(); return result; }
  catch (error) { showToast('error', escapeHtml(error.message)); return null; }
}

async function approveDirectorGate(approved) {
  const gate = directorActive.human_action;
  if (!gate) return;
  const action = {narration_acceptance:'approve_narration', final_audio_approval:'approve_final_audio'}[gate.action_type];
  if (!action) return showToast('error', `Unsupported human gate: ${escapeHtml(gate.action_type)}`);
  const artifact = gate.action_type === 'final_audio_approval' ? gate.items?.[0] || {} : {};
  await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/approve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, approved, artifact_id:artifact.artifact_id || null, artifact_sha256:artifact.sha256 || null})});
}
async function cancelDirectorWorkflow() { await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/cancel`, {method:'POST'}); }
async function resumeDirectorWorkflow() { await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/resume`, {method:'POST'}); }
async function selectDirectorAttempt(beat, attempt) { await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/attempts/${attempt}/select`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor_id:'director-console',explicit_approval:true})}); }

async function resolveDirectorPronunciation(term, button) {
  const phonetic = button.parentElement.querySelector('input').value.trim();
  if (!phonetic) return showToast('warning', 'Enter an approved pronunciation.');
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/pronunciations`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({term,phonetic,actor_id:'director-console'})});
}

async function bindDirectorResource(resourceId, button) {
  const assetId = button.parentElement.querySelector('input').value.trim();
  if (!assetId) return showToast('warning', 'Enter an existing library asset ID.');
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/bind`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resource_id:resourceId,asset_id:assetId,actor_id:'director-console',allow_substitution:true})});
}

function openDirectorBeat(beatId) {
  directorBeat = directorReview?.beats.find(beat => beat.beat_id === beatId);
  if (!directorBeat) return;
  document.getElementById('directorBeatTitle').textContent = `${directorBeat.beat_id} · ${directorBeat.render_status}`;
  document.getElementById('directorBeatBody').innerHTML = `<section><label class="text-[10px] uppercase text-slate-500">Immutable source</label><p class="mt-1 p-3 rounded bg-[#0E0C12] text-xs text-slate-300">${escapeHtml(directorBeat.source_text)}</p></section>
    <section class="grid grid-cols-2 md:grid-cols-4 gap-3"><label class="text-[10px] text-slate-400">Emotion<input id="directorBeatEmotion" value="${escapeHtml(directorBeat.emotion)}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Energy<input id="directorBeatEnergy" type="number" min="0" max="5" step="0.1" value="${directorBeat.energy}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Pace<input id="directorBeatPace" type="number" min="0.1" step="0.1" value="${directorBeat.pace ?? ''}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Pause after (ms)<input id="directorBeatPause" type="number" min="0" step="10" value="${directorBeat.pause_after_ms}" class="director-input w-full mt-1"></label></section>
    <section><div class="flex justify-between"><h4 class="text-xs font-bold">Attempts</h4><span class="text-[10px] text-slate-400">Selected: ${directorBeat.selected_attempt ?? 'none'} · QC ${directorBeat.qc_summary?.score ?? directorBeat.qc_summary?.overall_score ?? '—'}</span></div>${directorBeat.available_attempts.map(attempt => `<div class="mt-2 p-2 rounded bg-[#0E0C12] flex flex-wrap items-center gap-2"><audio controls preload="none" class="h-8 flex-1" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(attempt.artifact_id)}"></audio><span class="text-[10px]">#${attempt.attempt_id} · ${escapeHtml(attempt.qc_verdict || attempt.status)} · ${attempt.qc_score ?? '—'}</span><button onclick="selectDirectorAttempt('${escapeHtml(directorBeat.beat_id)}',${attempt.attempt_id}).then(()=>openDirectorBeat('${escapeHtml(directorBeat.beat_id)}'))" class="px-2 py-1 rounded ${attempt.selected ? 'bg-emerald-700' : 'bg-purple-700'} text-[10px]">${attempt.selected ? 'Selected' : 'Select'}</button></div>`).join('') || '<p class="text-xs text-slate-500 mt-2">No attempts.</p>'}</section>
    <section><h4 class="text-xs font-bold mb-1">QC summary</h4><pre class="p-3 rounded bg-[#0E0C12] text-[10px] text-slate-400 overflow-x-auto">${escapeHtml(JSON.stringify(directorBeat.qc_summary || {}, null, 2))}</pre></section>
    <div id="directorImpactPreview"></div><div class="flex flex-wrap justify-end gap-2"><button onclick="saveDirectorTiming()" class="px-3 py-2 rounded bg-[#231F2A] text-xs">Save Timing</button><button onclick="saveDirectorDirection()" class="px-3 py-2 rounded bg-purple-600 text-xs font-bold">Save Direction</button><button onclick="rerenderDirectorBeat('${escapeHtml(directorBeat.beat_id)}')" class="px-3 py-2 rounded bg-emerald-700 text-xs font-bold">Rerender Beat</button></div>`;
  document.querySelectorAll('#directorBeatDialog .director-input').forEach(el => el.className += ` ${directorInputClass}`);
  document.getElementById('directorBeatDialog').showModal();
}

function closeDirectorBeat() { document.getElementById('directorBeatDialog').close(); directorBeat = null; }

function showDirectorImpact(result) {
  const steps = result?.required_reproduction_steps || [];
  document.getElementById('directorImpactPreview').innerHTML = `<div class="p-3 rounded border border-amber-500/40 bg-amber-950/20"><h4 class="text-xs font-bold text-amber-300">Server impact preview</h4><p class="text-[11px] text-slate-300 mt-1">${steps.length ? steps.map(escapeHtml).join(' → ') : 'No reproduction required'}</p><p class="text-[10px] mt-1 ${steps.includes('render_beat') ? 'text-amber-300' : 'text-emerald-400'}">Narration rerender: ${steps.includes('render_beat') ? 'YES' : 'NO'}</p></div>`;
}

async function saveDirectorDirection() {
  const pace = document.getElementById('directorBeatPace').value;
  const result = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${directorBeat.beat_id}/direction`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({emotion:document.getElementById('directorBeatEmotion').value,energy:Number(document.getElementById('directorBeatEnergy').value),pace:pace ? Number(pace) : null,actor_id:'director-console'})});
  if (result) showDirectorImpact(result);
}

async function saveDirectorTiming() {
  const result = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${directorBeat.beat_id}/timing`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({pause_after_ms:Number(document.getElementById('directorBeatPause').value),actor_id:'director-console'})});
  if (result) showDirectorImpact(result);
}
async function rerenderDirectorBeat(beat) { const job = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/render`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:directorActive.policy.provider})}); if (job?.job_id) pollDirectorOperation(job.job_id); }
async function reproduceDirectorProject() { const job = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/reproduce`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); if (job?.job_id) pollDirectorOperation(job.job_id); }

async function pollDirectorOperation(jobId) {
  const operation = await directorFetch(`/api/v1/voice-project-jobs/${jobId}`).catch(() => null);
  if (!operation) return;
  directorOperations = [operation, ...directorOperations.filter(item => item.id !== operation.id)];
  renderDirectorOperations();
  if (!['completed','failed','cancelled','interrupted'].includes(operation.status)) setTimeout(() => pollDirectorOperation(jobId), 1500);
  else refreshDirectorActive();
}

async function cancelDirectorOperation(jobId) {
  await directorMutation(`/api/v1/voice-project-jobs/${jobId}/cancel`, {method:'POST'});
  pollDirectorOperation(jobId);
}

async function refreshDirectorActive() {
  if (!directorActive) return;
  directorActive = await directorFetch(`/api/v1/voice-workflows/${directorActive.workflow_id}`);
  [directorReview, directorSource, directorRevisions, directorOperations] = await Promise.all([
    directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/director-review`).catch(() => directorReview),
    directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/script`).catch(() => directorSource),
    directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/revisions`).catch(() => directorRevisions),
    directorFetch(`/api/v1/voice-project-jobs?project_id=${encodeURIComponent(directorActive.project_id)}&limit=20`).catch(() => directorOperations),
  ]);
  renderDirectorShell();
  await loadDirectorWorkflows();
}

function scheduleDirectorPolling() {
  clearInterval(directorPollTimer);
  directorPollTimer = setInterval(() => {
    const activeJob = directorOperations.some(op => ['queued','running','cancelling'].includes(op.status));
    if (currentTab === 'director' && directorActive && (activeJob || ['queued','running','waiting_for_human','cancelling'].includes(directorActive.status))) refreshDirectorActive().catch(() => {});
  }, 2500);
}

window.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`));
