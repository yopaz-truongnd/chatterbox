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
let directorGateSubmitting = false;

const directorInputClass = 'bg-[#0E0C12] border border-[#3F3A46] rounded-lg px-3 py-2 text-xs text-white focus:border-purple-500 focus:outline-hidden';
const directorStatusLabels = {queued:'đang chờ', running:'đang xử lý', waiting_for_human:'chờ bạn duyệt', completed:'hoàn tất', failed:'thất bại', cancelled:'đã hủy', cancelling:'đang hủy', interrupted:'bị gián đoạn', pending:'chưa chạy', skipped:'bỏ qua'};
const directorStepLabels = {create_project:'Tạo dự án', plan:'Lập kế hoạch', check_resources:'Kiểm tra tài nguyên', render:'Tạo giọng đọc', evaluate:'Kiểm tra chất lượng', prepare_mix:'Chuẩn bị phối', mix:'Phối âm', master:'Tạo master', export:'Xuất file'};
const directorStatusLabel = status => directorStatusLabels[status] || status;
const directorStepLabel = step => directorStepLabels[step] || step;

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
  if (!script) return showToast('warning', 'Vui lòng nhập kịch bản gốc.');
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
    showToast('success', 'Đã bắt đầu quy trình sản xuất.');
    await loadDirectorWorkflows();
    openDirectorWorkflow(workflow.workflow_id);
  } catch (error) { showToast('error', escapeHtml(error.message)); }
}

async function loadDirectorWorkflows() {
  const list = document.getElementById('directorWorkflowList');
  if (!list) return;
  try {
    directorWorkflows = await directorFetch('/api/v1/voice-workflows?limit=100');
    document.getElementById('directorCount').textContent = `${directorWorkflows.length} quy trình`;
    list.innerHTML = directorWorkflows.length ? directorWorkflows.map(workflow => {
      const progress = workflow.steps.length ? Math.round(workflow.steps.filter(s => ['completed', 'skipped'].includes(s.status)).length * 100 / workflow.steps.length) : 0;
      return `<div class="relative"><button onclick="openDirectorWorkflow('${escapeHtml(workflow.workflow_id)}')" class="w-full text-left p-3 pr-10 rounded-lg border ${directorActive?.workflow_id === workflow.workflow_id ? 'border-purple-500' : 'border-[#3F3A46]'} bg-[#0E0C12] hover:bg-[#231F2A]">
        <div class="flex justify-between gap-2"><strong class="text-xs text-white truncate">${escapeHtml(workflow.project_id)}</strong>${directorStatusChip(workflow.status)}</div>
        <div class="mt-2 h-1 bg-[#3F3A46] rounded"><div class="h-1 bg-purple-500 rounded" style="width:${progress}%"></div></div>
        <div class="mt-1 flex justify-between text-[10px] text-slate-500"><span>${escapeHtml(workflow.policy.provider)} / ${escapeHtml(workflow.policy.model || 'mặc định')}</span><span>${progress}%</span></div>
      </button><button onclick="deleteDirectorProduction('${escapeHtml(workflow.workflow_id)}','${escapeHtml(workflow.project_id)}')" class="absolute right-2 top-8 px-2 py-1 rounded bg-red-950 text-red-300 hover:bg-red-900 text-[10px] font-bold" title="Xóa bản sản xuất và tất cả file liên quan" aria-label="Xóa bản sản xuất ${escapeHtml(workflow.project_id)}">Xóa</button></div>`;
    }).join('') : '<p class="text-xs text-slate-500 py-6 text-center">Chưa có bản sản xuất nào.</p>';
    if (directorActive) {
      const fresh = directorWorkflows.find(w => w.workflow_id === directorActive.workflow_id);
      if (fresh) { directorActive = fresh; renderDirectorShell(); }
    }
  } catch (error) { list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`; }
}

function directorStatusChip(status) {
  const color = status === 'completed' ? 'emerald' : status === 'waiting_for_human' ? 'amber' : ['failed', 'cancelled'].includes(status) ? 'red' : 'purple';
  return `<span class="px-2 py-0.5 rounded bg-${color}-950/60 text-${color}-300 text-[10px]">${escapeHtml(directorStatusLabel(status))}</span>`;
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
  document.getElementById('directorActiveMeta').textContent = `${workflow.workflow_id} · ${directorStatusLabel(workflow.status)} · cập nhật ${workflow.updated_at}`;
  document.getElementById('directorFlowGuide').innerHTML = renderDirectorFlowGuide(workflow);
  document.getElementById('directorProgress').innerHTML = workflow.steps.map(step => `<div class="rounded p-2 border border-[#3F3A46] text-center"><div class="text-[10px] ${step.status === 'completed' ? 'text-emerald-400' : step.status === 'running' ? 'text-purple-300' : 'text-slate-500'}">${escapeHtml(directorStepLabel(step.name))}</div><div class="text-[9px] text-slate-500">${escapeHtml(directorStatusLabel(step.status))}</div></div>`).join('');
  const actions = document.getElementById('directorGateActions');
  const gate = workflow.human_action?.action_type;
  if (workflow.status === 'waiting_for_human' && gate) {
    if (gate === 'audio_quality_review') {
      actions.innerHTML = '<button onclick="showDirectorView(\'review\')" class="px-3 py-2 rounded-lg bg-purple-600 text-white text-xs font-bold">Mở đánh giá chất lượng</button><button onclick="cancelDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Hủy</button>';
    } else {
      const label = gate === 'narration_acceptance' ? 'Duyệt toàn bộ giọng đọc & tiếp tục' : gate === 'final_audio_approval' ? 'Duyệt bản master này & xuất file' : 'Tiếp tục';
      actions.innerHTML = `<button data-director-gate onclick="approveDirectorGate(true)" class="px-3 py-2 rounded-lg bg-emerald-600 text-white text-xs font-bold">${label}</button><button data-director-gate onclick="approveDirectorGate(false)" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Từ chối</button>`;
    }
  } else if (['queued', 'running', 'cancelling'].includes(workflow.status)) {
    actions.innerHTML = '<button onclick="cancelDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Hủy</button>';
  } else if (workflow.status === 'interrupted') {
    actions.innerHTML = '<button onclick="resumeDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-purple-600 text-white text-xs">Tiếp tục từ trạng thái đã lưu</button>';
  } else actions.innerHTML = '';
  renderDirectorOperations();
  renderDirectorPendingRevisions();
  if (workflow.status === 'waiting_for_human' && ['audio_quality_review', 'narration_acceptance'].includes(gate)) directorView = 'review';
  if (workflow.status === 'waiting_for_human' && gate === 'final_audio_approval') directorView = 'delivery';
  showDirectorView(directorView);
}

function renderDirectorFlowGuide(workflow) {
  const gate = workflow.human_action?.action_type;
  let title = 'Hệ thống đang tự xử lý';
  let detail = 'Bạn có thể rời trang này. Tiến độ được lưu trên máy chủ và sẽ khôi phục khi quay lại.';
  if (gate === 'resource_required') { title = 'Cần bạn bổ sung tài nguyên'; detail = 'Cung cấp cách đọc hoặc tệp âm thanh còn thiếu, sau đó tiếp tục. Hệ thống không tự bịa tài nguyên.'; }
  else if (gate === 'audio_quality_review') { title = 'Cần đánh giá chất lượng giọng đọc'; detail = 'Mở mục duyệt để nghe các đoạn cần xem xét và chọn bản phù hợp hoặc tạo lại đoạn lỗi.'; }
  else if (gate === 'narration_acceptance') { title = 'Bước 1/2 cần bạn duyệt: giọng đọc'; detail = 'Nghe các attempt đã chọn bên dưới. Nút xanh duyệt TOÀN BỘ narration một lần, sau đó hệ thống tự phối âm và tạo master.'; }
  else if (gate === 'final_audio_approval') { title = 'Bước 2/2 cần bạn duyệt: bản master'; detail = 'Nghe bản master và kiểm tra SHA-256. Nút xanh chỉ duyệt đúng file hiện tại, rồi hệ thống mới xuất WAV/MP3.'; }
  else if (workflow.status === 'completed') { title = 'Sản xuất đã hoàn tất'; detail = 'Chỉ tải file có nhãn ĐÃ XÁC MINH. Khi sửa giọng hoặc timing, approval cũ sẽ mất hiệu lực và cần duyệt master mới.'; }
  return `<div class="p-3 rounded-lg bg-purple-950/20 border border-purple-500/30"><b class="text-xs text-purple-200">${title}</b><p class="text-[11px] text-slate-300 mt-1">${detail}</p><p class="text-[10px] text-slate-500 mt-1">Luồng: Kế hoạch → Tài nguyên → Tạo giọng → QC → Duyệt giọng → Phối/Master → Duyệt master → Xuất file.</p></div>`;
}

function renderDirectorOperations() {
  const panel = document.getElementById('directorOperations');
  if (!panel) return;
  const visible = directorOperations.filter(op => ['queued','running','cancelling','interrupted','failed'].includes(op.status)).slice(0, 5);
  panel.classList.toggle('hidden', !visible.length);
  panel.innerHTML = visible.length ? `<h4 class="text-xs font-bold text-white mb-3">Tác vụ đang xử lý</h4>${visible.map(op => `<div class="mb-3 last:mb-0"><div class="flex justify-between text-[11px]"><b>${escapeHtml(directorStepLabel(op.operation))}${op.beat_id ? ` · ${escapeHtml(op.beat_id)}` : ''}</b><span>${escapeHtml(directorStatusLabel(op.status))}</span></div><div class="h-1.5 bg-[#3F3A46] rounded mt-1"><div class="h-1.5 bg-purple-500 rounded" style="width:${Math.max(0, Math.min(100, op.progress_percent || 0))}%"></div></div><div class="flex justify-between items-center mt-1 text-[9px] text-slate-500 font-mono"><span>${escapeHtml(op.id)} · ${escapeHtml(op.stage || 'đang chờ')} · ${Math.round(op.progress_percent || 0)}%</span>${['queued','running'].includes(op.status) ? `<button onclick="cancelDirectorOperation('${escapeHtml(op.id)}')" class="text-red-400">Hủy</button>` : ''}</div></div>`).join('')}` : '';
}

function renderDirectorPendingRevisions() {
  const panel = document.getElementById('directorPendingRevisions');
  if (!panel) return;
  const pendingIds = directorRevisions?.state?.pending_revision_ids || [];
  const events = (directorRevisions?.events || []).filter(event => pendingIds.includes(event.revision_id));
  panel.classList.toggle('hidden', !events.length);
  panel.innerHTML = events.length ? `<div class="flex flex-wrap justify-between gap-3"><div><h4 class="text-xs font-bold text-amber-300">Chỉnh sửa chưa tái tạo</h4>${events.map(event => `<p class="text-[11px] text-slate-300 mt-1"><b>${escapeHtml(event.beat_id || event.affected_beats?.join(', ') || 'Dự án')}</b> · ${escapeHtml(event.revision_type.replaceAll('_',' '))}</p>`).join('')}</div><button onclick="reproduceDirectorProject()" class="self-end px-3 py-2 rounded bg-amber-600 text-white text-xs font-bold">Tái tạo các thay đổi</button></div>` : '';
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
  if (!directorReview) return '<p class="text-xs text-slate-500">Nội dung duyệt sẽ xuất hiện sau khi tạo dự án.</p>';
  const gaps = [...directorReview.required_resource_gaps, ...directorReview.recommended_resource_gaps];
  return `<h4 class="text-xs font-bold text-white mb-1">Kịch bản gốc (không thể sửa)</h4><p class="text-[9px] text-slate-500 font-mono mb-3">SHA-256 ${escapeHtml(directorSource?.sha256 || directorReview.source_script_sha256)}</p><div class="p-3 rounded bg-[#0E0C12] text-xs text-slate-300 whitespace-pre-wrap">${escapeHtml(directorSource?.script_text || directorReview.script_excerpt)}</div>
    <div class="grid md:grid-cols-2 gap-3 mt-4"><div><h4 class="text-xs font-bold text-white mb-2">Các đoạn giọng đọc</h4>${directorReview.beats.map(b => `<button onclick="openDirectorBeat('${escapeHtml(b.beat_id)}')" class="block w-full text-left p-2 mb-1 rounded bg-[#0E0C12] text-xs"><b class="text-white">${escapeHtml(b.beat_id)}</b> <span class="text-slate-400">${escapeHtml(b.emotion)} · năng lượng ${b.energy} · ${escapeHtml(directorStatusLabel(b.render_status))}</span></button>`).join('')}</div><div><h4 class="text-xs font-bold text-white mb-2">Mức sẵn sàng tài nguyên ${directorReview.resource_readiness ?? '—'}%</h4>${gaps.length ? gaps.map(renderDirectorGap).join('') : '<p class="text-xs text-emerald-400">Không thiếu tài nguyên.</p>'}</div></div>`;
}

function renderDirectorGap(gap) {
  const required = gap.priority === 'required';
  const action = gap.resource_type === 'knowledge'
    ? gap.term ? `<div class="flex gap-1 mt-2"><input class="director-input flex-1" placeholder="Cách phát âm đã xác nhận"><button onclick="resolveDirectorPronunciation('${escapeHtml(gap.term)}',this)" class="px-2 rounded bg-purple-700 text-[10px]">Xác nhận</button></div>` : '<p class="text-[10px] text-slate-500 mt-2">Chưa có từ cần xác nhận phát âm.</p>'
    : `<div class="flex gap-1 mt-2"><input class="director-input flex-1" placeholder="Mã tài nguyên hiện có"><button onclick="bindDirectorResource('${escapeHtml(gap.resource_id)}',this)" class="px-2 rounded bg-purple-700 text-[10px]">Liên kết</button></div>`;
  return `<div class="p-2 mb-2 rounded ${required ? 'bg-red-950/30 border-red-800' : 'bg-amber-950/30 border-amber-800'} border text-xs text-amber-200"><div class="flex justify-between"><span>${escapeHtml(gap.resource_type)}: ${escapeHtml(gap.description)}</span><b class="text-[9px] uppercase">${escapeHtml(gap.priority)}</b></div>${action}</div>`;
}

function renderDirectorReview() {
  if (!directorReview?.beats?.length) return '<p class="text-xs text-slate-500">Chưa có đoạn giọng đọc nào.</p>';
  const gated = directorActive.status === 'waiting_for_human' && directorActive.human_action?.action_type === 'narration_acceptance';
  return `${gated ? '<div class="mb-3 p-3 rounded-lg border border-amber-500/50 bg-amber-950/30 text-xs text-amber-200"><b>Cần duyệt giọng đọc:</b> nghe các bản đã chọn. Nút xanh phía trên duyệt toàn bộ một lần.</div>' : ''}<div class="space-y-3">${directorReview.beats.map(beat => `<article class="p-3 rounded-lg bg-[#0E0C12] border ${beat.selected_attempt ? 'border-emerald-700/50' : 'border-[#3F3A46]'}"><div class="flex flex-wrap justify-between gap-2"><div><b class="text-white text-xs">${escapeHtml(beat.beat_id)} · ${escapeHtml(beat.emotion)}</b><p class="text-[11px] text-slate-400 mt-1">${escapeHtml(beat.source_text)}</p></div><span class="text-[10px] text-slate-400">bản đã chọn ${beat.selected_attempt ?? 'chưa có'} · QC ${beat.qc_summary?.qc_score ?? beat.qc_summary?.score ?? beat.qc_summary?.overall_score ?? '—'}</span></div>
    <div class="flex flex-wrap gap-2 mt-3">${beat.available_attempts.map(a => `<div class="flex items-center gap-1"><audio controls preload="none" class="h-8 w-44" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(a.artifact_id)}"></audio><button onclick="selectDirectorAttempt('${escapeHtml(beat.beat_id)}',${a.attempt_id})" class="px-2 py-1 rounded ${a.selected ? 'bg-emerald-700' : 'bg-[#231F2A]'} text-[10px] text-white">Bản ${a.attempt_id}${a.selected ? ' · đã chọn' : ''}</button></div>`).join('')}</div>
    <div class="flex gap-2 mt-3"><button onclick="openDirectorBeat('${escapeHtml(beat.beat_id)}')" class="px-3 py-1 rounded bg-purple-600 text-white text-[10px]">Mở chi tiết đoạn</button></div></article>`).join('')}</div>`;
}

function renderDirectorMix() {
  const done = name => directorActive.steps.find(s => s.name === name);
  return `<div class="grid md:grid-cols-3 gap-3">${['prepare_mix','mix','master'].map(name => { const step = done(name); return `<div class="p-4 rounded bg-[#0E0C12]"><b class="text-white text-xs">${escapeHtml(directorStepLabel(name))}</b><p class="text-[11px] text-slate-400 mt-2">${escapeHtml(directorStatusLabel(step?.status || 'pending'))}</p><p class="text-[10px] text-slate-500">${escapeHtml(JSON.stringify(step?.result_summary || {}))}</p></div>`; }).join('')}</div>`;
}

async function renderDirectorDelivery(content) {
  content.innerHTML = '<p class="text-xs text-slate-500">Đang tải danh sách file…</p>';
  try {
    const [data, mixPlan] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/artifacts`),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/mix-plan`).catch(() => null),
    ]);
    const gate = directorActive.human_action?.action_type === 'final_audio_approval' ? directorActive.human_action.items?.[0] : null;
    const metrics = directorOperations.find(op => op.operation === 'master' && op.status === 'completed')?.result?.metrics || {};
    const masterStatus = directorReview?.artifact_status?.find(item => item.artifact_id === 'master_wav');
    const masterVerified = masterStatus?.exists && masterStatus?.fresh && masterStatus?.sha256 === gate?.sha256;
    const masterLabel = masterVerified ? 'ĐÃ XÁC MINH' : masterStatus?.exists && !masterStatus?.fresh ? 'ĐÃ CŨ' : 'CHƯA XÁC MINH';
    const masterApproval = masterVerified ? '<button data-director-gate onclick="approveDirectorGate(true)" class="px-3 py-2 rounded bg-emerald-600 text-white text-xs font-bold">Duyệt bản master này & xuất file</button>' : '<span class="px-3 py-2 rounded bg-[#231F2A] text-slate-500 text-xs">Chưa thể duyệt</span>';
    const masterCard = gate ? `<div class="mb-4 p-4 rounded-lg border border-amber-500/50 bg-amber-950/20"><div class="flex flex-wrap justify-between gap-3"><div><h4 class="font-bold text-white">master.wav</h4><p class="text-[10px] text-slate-400 font-mono break-all">SHA-256 ${escapeHtml(gate.sha256)}</p><p class="text-[10px] text-slate-400">Thời lượng ${mixPlan?.duration_ms ? `${Math.round(mixPlan.duration_ms)} ms` : 'chưa có'} · Âm lượng ${metrics.output_lufs ?? 'chưa có'} LUFS · Dòng dữ liệu <span class="${masterVerified ? 'text-emerald-400' : 'text-amber-400'}">${masterLabel}</span></p></div>${masterApproval}</div><p class="text-[11px] text-amber-200 mt-2">Hãy nghe toàn bộ file này. Khi duyệt, SHA-256 hiện tại sẽ được khóa vào phê duyệt.</p><audio controls preload="metadata" class="w-full h-9 mt-3" src="${escapeHtml(gate.download_url)}"></audio></div>` : '';
    const artifactsHtml = data.artifacts.map(a => {
      const lineage = directorReview?.artifact_status?.find(item => item.artifact_id === a.id);
      const valid = lineage?.exists && lineage?.fresh && lineage?.sha256 === a.sha256;
      const label = valid ? 'ĐÃ XÁC MINH' : lineage?.exists && !lineage?.fresh ? 'ĐÃ CŨ' : 'CHƯA XÁC MINH';
      const download = valid ? `<a class="px-3 py-1 rounded bg-purple-600 text-white text-xs" href="${escapeHtml(lineage.download_url)}">Tải xuống</a>` : '<span class="px-3 py-1 rounded bg-[#231F2A] text-slate-500 text-xs">Chưa thể tải</span>';
      return `<div class="flex flex-wrap items-center justify-between gap-2 p-3 mb-2 rounded bg-[#0E0C12]"><div><b class="text-xs text-white">${escapeHtml(a.id)}</b><p class="text-[10px] text-slate-500 font-mono">SHA-256 ${escapeHtml(a.sha256 || 'not reported')}</p><p class="text-[10px] ${valid ? 'text-emerald-400' : 'text-amber-400'}">${label}</p></div>${download}</div>`;
    }).join('') || '<p class="text-xs text-slate-500">Chưa có file bàn giao.</p>';
    content.innerHTML = `${masterCard}<div class="mb-3">${directorStatusChip(directorActive.status)} <span class="text-xs text-slate-400 ml-2">Chỉ file mới nhất và đã xác minh mới được tải.</span></div>${artifactsHtml}`;
  } catch (error) { content.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`; }
}

async function directorMutation(url, options = {}) {
  try { const result = await directorFetch(url, options); await refreshDirectorActive(); return result; }
  catch (error) { showToast('error', escapeHtml(error.message)); return null; }
}

async function approveDirectorGate(approved) {
  if (directorGateSubmitting) return;
  const gate = directorActive.human_action;
  if (!gate) return;
  const action = {narration_acceptance:'approve_narration', final_audio_approval:'approve_final_audio'}[gate.action_type];
  if (!action) return showToast('error', `Bước duyệt chưa được hỗ trợ: ${escapeHtml(gate.action_type)}`);
  const artifact = gate.action_type === 'final_audio_approval' ? gate.items?.[0] || {} : {};
  directorGateSubmitting = true;
  document.querySelectorAll('[data-director-gate]').forEach(button => { button.disabled = true; button.classList.add('opacity-50'); });
  try {
    await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/approve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, approved, artifact_id:artifact.artifact_id || null, artifact_sha256:artifact.sha256 || null})});
  } finally { directorGateSubmitting = false; }
}
async function cancelDirectorWorkflow() { await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/cancel`, {method:'POST'}); }
async function resumeDirectorWorkflow() { await directorMutation(`/api/v1/voice-workflows/${directorActive.workflow_id}/resume`, {method:'POST'}); }
async function deleteDirectorProduction(workflowId, projectId) {
  if (!confirm(`Xóa vĩnh viễn bản sản xuất "${projectId}"?\n\nToàn bộ kịch bản, bản thu, mix/master, file xuất, revision và lịch sử tác vụ liên quan sẽ bị xóa.`)) return;
  try {
    await directorFetch(`/api/v1/voice-workflows/${workflowId}`, {method:'DELETE'});
    if (directorActive?.workflow_id === workflowId) {
      directorActive = directorReview = directorSource = directorRevisions = null;
      directorOperations = [];
      document.getElementById('directorWorkspace').classList.add('hidden');
      document.getElementById('directorEmpty').classList.remove('hidden');
    }
    showToast('success', 'Đã xóa bản sản xuất và các file liên quan.');
    await loadDirectorWorkflows();
  } catch (error) { showToast('error', escapeHtml(error.message)); }
}
async function selectDirectorAttempt(beat, attempt) { await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/beats/${beat}/attempts/${attempt}/select`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor_id:'director-console',explicit_approval:true})}); }

async function resolveDirectorPronunciation(term, button) {
  const phonetic = button.parentElement.querySelector('input').value.trim();
  if (!phonetic) return showToast('warning', 'Vui lòng nhập cách phát âm đã xác nhận.');
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/pronunciations`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({term,phonetic,actor_id:'director-console'})});
}

async function bindDirectorResource(resourceId, button) {
  const assetId = button.parentElement.querySelector('input').value.trim();
  if (!assetId) return showToast('warning', 'Vui lòng nhập mã tài nguyên hiện có.');
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/bind`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resource_id:resourceId,asset_id:assetId,actor_id:'director-console',allow_substitution:true})});
}

function openDirectorBeat(beatId) {
  directorBeat = directorReview?.beats.find(beat => beat.beat_id === beatId);
  if (!directorBeat) return;
  document.getElementById('directorBeatTitle').textContent = `${directorBeat.beat_id} · ${directorStatusLabel(directorBeat.render_status)}`;
  document.getElementById('directorBeatBody').innerHTML = `<section><label class="text-[10px] uppercase text-slate-500">Nội dung gốc không thể sửa</label><p class="mt-1 p-3 rounded bg-[#0E0C12] text-xs text-slate-300">${escapeHtml(directorBeat.source_text)}</p></section>
    <section class="grid grid-cols-2 md:grid-cols-4 gap-3"><label class="text-[10px] text-slate-400">Cảm xúc<input id="directorBeatEmotion" value="${escapeHtml(directorBeat.emotion)}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Năng lượng<input id="directorBeatEnergy" type="number" min="0" max="5" step="0.1" value="${directorBeat.energy}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Nhịp đọc<input id="directorBeatPace" type="number" min="0.1" step="0.1" value="${directorBeat.pace ?? ''}" class="director-input w-full mt-1"></label><label class="text-[10px] text-slate-400">Nghỉ sau đoạn (ms)<input id="directorBeatPause" type="number" min="0" step="10" value="${directorBeat.pause_after_ms}" class="director-input w-full mt-1"></label></section>
    <section><div class="flex justify-between"><h4 class="text-xs font-bold">Các bản thu</h4><span class="text-[10px] text-slate-400">Đã chọn: ${directorBeat.selected_attempt ?? 'chưa có'} · QC ${directorBeat.qc_summary?.qc_score ?? directorBeat.qc_summary?.score ?? directorBeat.qc_summary?.overall_score ?? '—'}</span></div>${directorBeat.available_attempts.map(attempt => `<div class="mt-2 p-2 rounded bg-[#0E0C12] flex flex-wrap items-center gap-2"><audio controls preload="none" class="h-8 flex-1" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(attempt.artifact_id)}"></audio><span class="text-[10px]">#${attempt.attempt_id} · ${escapeHtml(attempt.qc_verdict || attempt.status)} · ${attempt.qc_score ?? '—'}</span><button onclick="selectDirectorAttempt('${escapeHtml(directorBeat.beat_id)}',${attempt.attempt_id}).then(()=>openDirectorBeat('${escapeHtml(directorBeat.beat_id)}'))" class="px-2 py-1 rounded ${attempt.selected ? 'bg-emerald-700' : 'bg-purple-700'} text-[10px]">${attempt.selected ? 'Đang chọn' : 'Chọn bản này'}</button></div>`).join('') || '<p class="text-xs text-slate-500 mt-2">Chưa có bản thu.</p>'}</section>
    <section><h4 class="text-xs font-bold mb-1">Tóm tắt kiểm tra chất lượng (QC)</h4><pre class="p-3 rounded bg-[#0E0C12] text-[10px] text-slate-400 overflow-x-auto">${escapeHtml(JSON.stringify(directorBeat.qc_summary || {}, null, 2))}</pre></section>
    <div id="directorImpactPreview"></div><div class="flex flex-wrap justify-end gap-2"><button onclick="saveDirectorTiming()" class="px-3 py-2 rounded bg-[#231F2A] text-xs">Lưu thời gian nghỉ</button><button onclick="saveDirectorDirection()" class="px-3 py-2 rounded bg-purple-600 text-xs font-bold">Lưu hướng diễn</button><button onclick="rerenderDirectorBeat('${escapeHtml(directorBeat.beat_id)}')" class="px-3 py-2 rounded bg-emerald-700 text-xs font-bold">Tạo lại đoạn này</button></div>`;
  document.querySelectorAll('#directorBeatDialog .director-input').forEach(el => el.className += ` ${directorInputClass}`);
  document.getElementById('directorBeatDialog').showModal();
}

function closeDirectorBeat() { document.getElementById('directorBeatDialog').close(); directorBeat = null; }

function showDirectorImpact(result) {
  const steps = result?.required_reproduction_steps || [];
  document.getElementById('directorImpactPreview').innerHTML = `<div class="p-3 rounded border border-amber-500/40 bg-amber-950/20"><h4 class="text-xs font-bold text-amber-300">Ảnh hưởng do máy chủ xác định</h4><p class="text-[11px] text-slate-300 mt-1">${steps.length ? steps.map(directorStepLabel).map(escapeHtml).join(' → ') : 'Không cần tái tạo'}</p><p class="text-[10px] mt-1 ${steps.includes('render_beat') ? 'text-amber-300' : 'text-emerald-400'}">Tạo lại giọng đọc: ${steps.includes('render_beat') ? 'CÓ' : 'KHÔNG'}</p></div>`;
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
