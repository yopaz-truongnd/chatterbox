/** Director Console: a thin REST adapter over authoritative workflow services. */
let directorWorkflows = [];
let directorActive = null;
let directorReview = null;
let directorSource = null;
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
    [directorReview, directorSource] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/director-review`).catch(() => null),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/script`).catch(() => null),
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
  showDirectorView(directorView);
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
}

function renderDirectorWorkspace() {
  if (!directorReview) return '<p class="text-xs text-slate-500">The project review becomes available after project creation.</p>';
  const gaps = [...directorReview.required_resource_gaps, ...directorReview.recommended_resource_gaps];
  return `<h4 class="text-xs font-bold text-white mb-1">Source script (immutable)</h4><p class="text-[9px] text-slate-500 font-mono mb-3">SHA-256 ${escapeHtml(directorSource?.sha256 || directorReview.source_script_sha256)}</p><div class="p-3 rounded bg-[#0E0C12] text-xs text-slate-300 whitespace-pre-wrap">${escapeHtml(directorSource?.script_text || directorReview.script_excerpt)}</div>
    <div class="grid md:grid-cols-2 gap-3 mt-4"><div><h4 class="text-xs font-bold text-white mb-2">VoicePlan beats</h4>${directorReview.beats.map(b => `<button onclick="showDirectorView('review')" class="block w-full text-left p-2 mb-1 rounded bg-[#0E0C12] text-xs"><b class="text-white">${escapeHtml(b.beat_id)}</b> <span class="text-slate-400">${escapeHtml(b.emotion)} · energy ${b.energy} · ${escapeHtml(b.render_status)}</span></button>`).join('')}</div><div><h4 class="text-xs font-bold text-white mb-2">Resource readiness ${directorReview.resource_readiness ?? '—'}%</h4>${gaps.length ? gaps.map(g => `<div class="p-2 mb-1 rounded bg-amber-950/30 text-xs text-amber-200">${escapeHtml(g.resource_type)}: ${escapeHtml(g.description)}</div>`).join('') : '<p class="text-xs text-emerald-400">No resource gaps.</p>'}</div></div>`;
}

function renderDirectorReview() {
  if (!directorReview?.beats?.length) return '<p class="text-xs text-slate-500">No planned beats yet.</p>';
  return `<div class="space-y-3">${directorReview.beats.map(beat => `<article class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46]"><div class="flex flex-wrap justify-between gap-2"><div><b class="text-white text-xs">${escapeHtml(beat.beat_id)} · ${escapeHtml(beat.emotion)}</b><p class="text-[11px] text-slate-400 mt-1">${escapeHtml(beat.source_text)}</p></div><span class="text-[10px] text-slate-400">energy ${beat.energy} · pace ${beat.pace ?? '—'} · QC ${beat.qc_summary?.score ?? beat.qc_summary?.overall_score ?? '—'}</span></div>
    <div class="flex flex-wrap gap-2 mt-3">${beat.available_attempts.map(a => `<div class="flex items-center gap-1"><audio controls preload="none" class="h-8 w-44" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(a.artifact_id)}"></audio><button onclick="selectDirectorAttempt('${escapeHtml(beat.beat_id)}',${a.attempt_id})" class="px-2 py-1 rounded ${a.selected ? 'bg-emerald-700' : 'bg-[#231F2A]'} text-[10px] text-white">Attempt ${a.attempt_id}</button></div>`).join('')}</div>
    <div class="flex gap-2 mt-3"><button onclick="editDirectorDirection('${escapeHtml(beat.beat_id)}','${escapeHtml(beat.emotion)}',${beat.energy})" class="px-2 py-1 rounded bg-purple-900 text-purple-200 text-[10px]">Direction</button><button onclick="editDirectorTiming('${escapeHtml(beat.beat_id)}',${beat.pause_after_ms})" class="px-2 py-1 rounded bg-purple-900 text-purple-200 text-[10px]">Timing</button><button onclick="rerenderDirectorBeat('${escapeHtml(beat.beat_id)}')" class="px-2 py-1 rounded bg-purple-600 text-white text-[10px]">Rerender</button></div></article>`).join('')}</div>`;
}

function renderDirectorMix() {
  const done = name => directorActive.steps.find(s => s.name === name);
  return `<div class="grid md:grid-cols-3 gap-3">${['prepare_mix','mix','master'].map(name => { const step = done(name); return `<div class="p-4 rounded bg-[#0E0C12]"><b class="text-white text-xs">${name.replace('_',' ')}</b><p class="text-[11px] text-slate-400 mt-2">${escapeHtml(step?.status || 'pending')}</p><p class="text-[10px] text-slate-500">${escapeHtml(JSON.stringify(step?.result_summary || {}))}</p></div>`; }).join('')}</div><button onclick="reproduceDirectorProject()" class="mt-4 px-3 py-2 rounded bg-purple-600 text-white text-xs">Reproduce pending revision</button>`;
}

async function renderDirectorDelivery(content) {
  content.innerHTML = '<p class="text-xs text-slate-500">Loading artifacts…</p>';
  try {
    const data = await directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/artifacts`);
    content.innerHTML = `<div class="mb-3">${directorStatusChip(directorActive.status)} <span class="text-xs text-slate-400 ml-2">Final approval is server-authoritative.</span></div>${data.artifacts.map(a => { const lineage = directorReview?.artifact_status?.find(item => item.artifact_id === a.id); return `<div class="flex flex-wrap items-center justify-between gap-2 p-3 mb-2 rounded bg-[#0E0C12]"><div><b class="text-xs text-white">${escapeHtml(a.id)}</b><p class="text-[10px] text-slate-500 font-mono">SHA-256 ${escapeHtml(a.sha256 || 'not reported')}</p><p class="text-[10px] ${lineage?.fresh ? 'text-emerald-400' : 'text-amber-400'}">Lineage ${lineage?.fresh ? 'verified / fresh' : 'not verified'}</p></div><a class="px-3 py-1 rounded bg-purple-600 text-white text-xs" href="${escapeHtml(a.download_url)}">Download</a></div>`; }).join('') || '<p class="text-xs text-slate-500">No deliverables yet.</p>';
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

async function editDirectorDirection(beat, emotion, energy) {
  const nextEmotion = prompt('Emotion', emotion); if (nextEmotion === null) return;
  const nextEnergy = prompt('Energy (0–5)', energy); if (nextEnergy === null) return;
  const result = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/direction`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({emotion:nextEmotion,energy:Number(nextEnergy),actor_id:'director-console'})});
  if (result) showToast('info', `Impact: ${(result.required_reproduction_steps || []).join(' → ') || 'none'}`);
}
async function editDirectorTiming(beat, pause) {
  const next = prompt('Pause after (ms)', pause); if (next === null) return;
  const result = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/timing`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({pause_after_ms:Number(next),actor_id:'director-console'})});
  if (result) showToast('info', `Impact: ${(result.required_reproduction_steps || []).join(' → ') || 'none'}`);
}
async function rerenderDirectorBeat(beat) { const job = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/render`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:directorActive.policy.provider})}); if (job?.job_id) pollDirectorOperation(job.job_id); }
async function reproduceDirectorProject() { const job = await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/reproduce`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); if (job?.job_id) pollDirectorOperation(job.job_id); }

async function pollDirectorOperation(jobId) {
  const operation = await directorFetch(`/api/v1/voice-project-jobs/${jobId}`).catch(() => null);
  if (!operation) return;
  showToast('info', `${operation.operation}: ${operation.status}`);
  if (!['completed','failed','cancelled'].includes(operation.status)) setTimeout(() => pollDirectorOperation(jobId), 1500);
  else refreshDirectorActive();
}

async function refreshDirectorActive() {
  if (!directorActive) return;
  directorActive = await directorFetch(`/api/v1/voice-workflows/${directorActive.workflow_id}`);
  directorReview = await directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/director-review`).catch(() => directorReview);
  directorSource = await directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/script`).catch(() => directorSource);
  renderDirectorShell();
  await loadDirectorWorkflows();
}

function scheduleDirectorPolling() {
  clearInterval(directorPollTimer);
  directorPollTimer = setInterval(() => {
    if (currentTab === 'director' && directorActive && ['queued','running','waiting_for_human','cancelling'].includes(directorActive.status)) refreshDirectorActive().catch(() => {});
  }, 2500);
}

window.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`));
