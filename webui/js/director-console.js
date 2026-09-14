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
let directorRefreshing = false;
let directorUserSelectedView = false;
let directorLastGateType = null;
let directorLastPollTime = 0;

let directorWorkflowsFp = '';
let directorShellFp = '';
let directorOperationsFp = '';
let directorRevisionsFp = '';
let directorContentFp = { workspace: '', review: '', mix: '', delivery: '', final: '' };

const directorInputClass = 'bg-[#0E0C12] border border-[#3F3A46] rounded-lg px-3 py-2 text-xs text-white focus:border-purple-500 focus:outline-hidden';
const directorStatusLabels = {queued:'đang chờ', running:'đang xử lý', waiting_for_human:'chờ bạn duyệt', completed:'hoàn tất', failed:'thất bại', cancelled:'đã hủy', cancelling:'đang hủy', interrupted:'bị gián đoạn', pending:'chưa chạy', skipped:'bỏ qua'};
const directorStepLabels = {create_project:'Tạo dự án', plan:'Lập kế hoạch', check_resources:'Kiểm tra tài nguyên', render:'Tạo giọng đọc', evaluate:'Kiểm tra chất lượng', prepare_mix:'Chuẩn bị phối', mix:'Phối âm', master:'Tạo master', export:'Xuất file'};
const directorStatusLabel = status => directorStatusLabels[status] || status;
const directorStepLabel = step => directorStepLabels[step] || step;

function formatDirectorBytes(bytes) {
  if (!bytes || isNaN(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDirectorDuration(ms) {
  if (!ms || isNaN(ms)) return '—';
  const totalSec = Math.round(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min > 0 ? `${min}p ` : ''}${sec}s (${Math.round(ms)} ms)`;
}

function copyDirectorScript() {
  const text = directorSource?.script_text || directorReview?.script_excerpt || '';
  if (!text) return showToast('warning', 'Không có nội dung kịch bản để sao chép.');
  navigator.clipboard.writeText(text).then(() => {
    showToast('success', 'Đã sao chép toàn bộ kịch bản gốc.');
  }).catch(() => {
    showToast('error', 'Không thể sao chép vào bộ nhớ tạm.');
  });
}

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

// ==================== IDEA-TO-SCRIPT WIZARD ====================
// Embeds the two-gate /api/v1/projects planner (topic -> clarifying questions ->
// Gate 1 requirements -> Gate 2 script) so a workflow can be created straight
// from an idea instead of requiring an already-written script.
let directorIdeaProjectId = null;
let directorIdeaData = null;

function setDirectorCreateMode(mode) {
  const manualBtn = document.getElementById('directorModeManualBtn');
  const ideaBtn = document.getElementById('directorModeIdeaBtn');
  const manualPanel = document.getElementById('directorManualPanel');
  const ideaPanel = document.getElementById('directorIdeaPanel');
  if (!manualBtn || !ideaBtn || !manualPanel || !ideaPanel) return;
  const isIdea = mode === 'idea';
  manualPanel.classList.toggle('hidden', isIdea);
  ideaPanel.classList.toggle('hidden', !isIdea);
  manualBtn.className = `px-3 py-1.5 rounded-md text-xs font-bold ${isIdea ? 'text-slate-300 font-medium' : 'bg-purple-600 text-white'}`;
  ideaBtn.className = `px-3 py-1.5 rounded-md text-xs font-bold ${isIdea ? 'bg-purple-600 text-white' : 'text-slate-300 font-medium'}`;
}

function directorIdeaStepVisibility(step) {
  ['step1', 'step2', 'step3'].forEach(s => {
    document.getElementById(`directorIdea${s.charAt(0).toUpperCase() + s.slice(1)}`)?.classList.toggle('hidden', s !== step);
  });
}

function directorIdeaSummaryMarkdown(summary) {
  if (!summary) return 'Chưa có cấu hình tóm tắt.';
  return escapeHtml(summary)
    .replace(/^### (.+)$/gm, '<h3 class="text-xs font-bold text-white mb-2">$1</h3>')
    .replace(/^\* \*\*([^*]+)\*\*: (.*)$/gm, '<div class="text-xs text-slate-200 py-0.5"><strong class="text-purple-400">$1:</strong> $2</div>')
    .replace(/^\* (.*)$/gm, '<div class="text-xs text-slate-300 py-0.5">• $1</div>')
    .replace(/\n/g, '<br/>');
}

function directorIdeaRenderQuestions(questions) {
  const container = document.getElementById('directorIdeaQuestions');
  if (!container) return;
  container.innerHTML = '';
  if (!questions || questions.length === 0) {
    container.innerHTML = '<div class="text-slate-400 text-xs italic">Tất cả thông số cơ bản đã đầy đủ. Vui lòng bấm tiếp tục!</div>';
    return;
  }
  questions.forEach((q, idx) => {
    const qCard = document.createElement('div');
    qCard.className = 'p-3 rounded-xl bg-[#0E0C12] border border-[#3F3A46]/60 space-y-2';
    let optionsHtml = '';
    if (q.options && q.options.length > 0) {
      optionsHtml = `<div class="flex flex-wrap gap-1.5 pt-1">${q.options.map(opt =>
        `<button type="button" onclick="selectDirectorIdeaOption('${q.id}', '${opt.replace(/'/g, "\\'")}')" class="director-idea-opt-${q.id} px-2.5 py-1 rounded-md text-[11px] border border-[#3F3A46] bg-[#18151E] hover:bg-purple-900/30 text-slate-300 cursor-pointer">${escapeHtml(opt)}</button>`
      ).join('')}</div>`;
    }
    qCard.innerHTML = `
      <div class="flex items-start justify-between gap-2">
        <label class="text-xs font-semibold text-white flex items-center gap-1.5">
          <span class="w-4 h-4 rounded-full bg-amber-600 text-white font-mono text-[10px] flex items-center justify-center">${idx + 1}</span>
          <span>${escapeHtml(q.question || q.id)}</span>
          ${q.required ? '<span class="text-red-400 font-bold">*</span>' : '<span class="text-slate-500 text-[10px]">(Khuyến nghị)</span>'}
        </label>
      </div>
      ${optionsHtml}
      <input type="text" id="director_idea_q_${q.id}" data-qid="${q.id}" placeholder="Hoặc nhập câu trả lời tùy chỉnh..." class="director-input w-full">
    `;
    container.appendChild(qCard);
  });
}

function selectDirectorIdeaOption(qid, val) {
  const input = document.getElementById(`director_idea_q_${qid}`);
  if (input) input.value = val;
  document.querySelectorAll(`.director-idea-opt-${qid}`).forEach(btn => {
    const active = btn.textContent.trim() === val;
    btn.className = `director-idea-opt-${qid} px-2.5 py-1 rounded-md text-[11px] border cursor-pointer ${active ? 'border-amber-500 bg-amber-600 text-white font-bold' : 'border-[#3F3A46] bg-[#18151E] hover:bg-amber-900/30 text-slate-300'}`;
  });
}

function directorIdeaExtractScript(data) {
  if (data.script && typeof data.script === 'object' && data.script.full_text) return data.script.full_text;
  if (typeof data.script === 'string') return data.script;
  if (data.script_text) return data.script_text;
  return '';
}

function directorIdeaScriptReady(data) {
  const scriptEl = document.getElementById('directorScript');
  const titleEl = document.getElementById('directorTitle');
  if (scriptEl) scriptEl.value = directorIdeaExtractScript(data);
  if (titleEl && !titleEl.value.trim()) titleEl.value = data.topic || '';
  setDirectorCreateMode('manual');
  directorIdeaStepVisibility('step1');
  const topicEl = document.getElementById('directorIdeaTopic');
  if (topicEl) topicEl.value = '';
  directorIdeaProjectId = null;
  directorIdeaData = null;
  showToast('success', 'Kịch bản đã sẵn sàng — kiểm tra rồi bấm "Bắt đầu sản xuất".');
}

function directorIdeaRenderState(data) {
  directorIdeaData = data;
  directorIdeaProjectId = data.id || data.project_id || directorIdeaProjectId;
  const status = data.status;

  if (status === 'awaiting_answers') {
    directorIdeaStepVisibility('step2');
    const tagsBox = document.getElementById('directorIdeaTags');
    if (tagsBox) {
      const entries = Object.entries(data.requirements || {}).filter(([, v]) => Boolean(v));
      tagsBox.innerHTML = entries.length
        ? entries.map(([k, v]) => `<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px]">✓ ${escapeHtml(k)}: ${escapeHtml(Array.isArray(v) ? v.join(', ') : String(v))}</span>`).join('')
        : '<span class="text-slate-500 text-[11px]">Chưa nhận diện được thông số</span>';
    }
    directorIdeaRenderQuestions(data.questions || []);
  } else if (status === 'awaiting_requirements_confirmation' || status === 'awaiting_confirmation' || status === 'awaiting_script_confirmation') {
    directorIdeaStepVisibility('step3');
    const isGate2 = status === 'awaiting_script_confirmation';
    const gateLabel = document.getElementById('directorIdeaGateLabel');
    if (gateLabel) {
      gateLabel.textContent = isGate2 ? 'Gate 2: Xác nhận kịch bản' : 'Gate 1: Xác nhận yêu cầu';
      gateLabel.className = `px-2 py-0.5 rounded text-[10px] font-bold border ${isGate2 ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/30' : 'bg-blue-600/20 text-blue-300 border-blue-500/30'}`;
    }
    const summaryBox = document.getElementById('directorIdeaSummaryBox');
    if (summaryBox) summaryBox.innerHTML = directorIdeaSummaryMarkdown(data.summary);
  } else if (status === 'approved') {
    // The "approved" confirm response doesn't carry the script body — re-fetch
    // the canonical project record so the generated text is never lost.
    directorFetch(`/api/v1/projects/${directorIdeaProjectId}`)
      .then(full => directorIdeaScriptReady(full))
      .catch(() => directorIdeaScriptReady(data));
  } else {
    directorIdeaStepVisibility('step1');
  }
}

async function directorIdeaPrepare() {
  const btn = document.getElementById('directorIdeaPrepareBtn');
  const topic = document.getElementById('directorIdeaTopic')?.value.trim();
  if (!topic) return showToast('warning', 'Vui lòng nhập chủ đề dự án âm thanh.');
  const autoDefaults = document.getElementById('directorIdeaAutoDefaults')?.checked ?? true;
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang phân tích...</span>'; }
  try {
    const data = await directorFetch('/api/v1/projects/prepare', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ topic, auto_defaults: autoDefaults }),
    });
    directorIdeaRenderState(data);
  } catch (error) {
    showToast('error', escapeHtml(error.message));
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">psychology</span><span>Phân tích & Khởi tạo</span>'; }
  }
}

async function directorIdeaSubmitAnswers() {
  if (!directorIdeaProjectId) return showToast('warning', 'Chưa có dự án nào được chọn.');
  const btn = document.getElementById('directorIdeaAnswersBtn');
  const answers = {};
  document.querySelectorAll('#directorIdeaQuestions input[data-qid]').forEach(input => {
    const val = input.value.trim();
    if (val) answers[input.getAttribute('data-qid')] = val;
  });
  const freeform = document.getElementById('directorIdeaFreeform')?.value.trim();
  const autoDefaults = document.getElementById('directorIdeaAnswersAutoDefaults')?.checked ?? true;
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang cập nhật...</span>'; }
  try {
    const data = await directorFetch(`/api/v1/projects/${directorIdeaProjectId}/answer`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ answers: freeform || answers, auto_defaults: autoDefaults }),
    });
    directorIdeaRenderState(data);
  } catch (error) {
    showToast('error', escapeHtml(error.message));
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">send</span><span>Gửi câu trả lời & Tóm tắt</span>'; }
  }
}

async function directorIdeaConfirm(approve) {
  if (!directorIdeaProjectId) return showToast('warning', 'Chưa có dự án nào.');
  try {
    const data = await directorFetch(`/api/v1/projects/${directorIdeaProjectId}/confirm`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ confirmed: approve }),
    });
    if (!approve) {
      directorIdeaProjectId = null;
      directorIdeaData = null;
      directorIdeaStepVisibility('step1');
      const topicEl = document.getElementById('directorIdeaTopic');
      if (topicEl) topicEl.value = '';
      showToast('info', 'Đã hủy ý tưởng dự án.');
      return;
    }
    directorIdeaRenderState(data);
  } catch (error) {
    showToast('error', escapeHtml(error.message));
  }
}

async function loadDirectorWorkflows(syncActive = false) {
  const list = document.getElementById('directorWorkflowList');
  if (!list) return;
  try {
    directorWorkflows = await directorFetch('/api/v1/voice-workflows?limit=100');
    const countEl = document.getElementById('directorCount');
    if (countEl) countEl.textContent = `${directorWorkflows.length} quy trình`;
    const fp = JSON.stringify(directorWorkflows.map(w => [w.workflow_id, w.status, w.updated_at, (w.steps || []).map(s => s.status)])) + `|${directorActive?.workflow_id || ''}`;
    if (fp !== directorWorkflowsFp) {
      directorWorkflowsFp = fp;
      const prevScroll = list.scrollTop;
      list.innerHTML = directorWorkflows.length ? directorWorkflows.map(workflow => {
        const progress = workflow.steps.length ? Math.round(workflow.steps.filter(s => ['completed', 'skipped'].includes(s.status)).length * 100 / workflow.steps.length) : 0;
        return `<div class="relative"><button onclick="openDirectorWorkflow('${escapeHtml(workflow.workflow_id)}')" class="w-full text-left p-3 pr-10 rounded-lg border ${directorActive?.workflow_id === workflow.workflow_id ? 'border-purple-500' : 'border-[#3F3A46]'} bg-[#0E0C12] hover:bg-[#231F2A]">
          <div class="flex justify-between gap-2"><strong class="text-xs text-white truncate">${escapeHtml(workflow.project_id)}</strong>${directorStatusChip(workflow.status)}</div>
          <div class="mt-2 h-1 bg-[#3F3A46] rounded"><div class="h-1 bg-purple-500 rounded" style="width:${progress}%"></div></div>
          <div class="mt-1 flex justify-between text-[10px] text-slate-500"><span>${escapeHtml(workflow.policy.provider)} / ${escapeHtml(workflow.policy.model || 'mặc định')}</span><span>${progress}%</span></div>
        </button><button onclick="deleteDirectorProduction('${escapeHtml(workflow.workflow_id)}','${escapeHtml(workflow.project_id)}')" class="absolute right-2 top-8 px-2 py-1 rounded bg-red-950 text-red-300 hover:bg-red-900 text-[10px] font-bold" title="Xóa bản sản xuất và tất cả file liên quan" aria-label="Xóa bản sản xuất ${escapeHtml(workflow.project_id)}">Xóa</button></div>`;
      }).join('') : '<p class="text-xs text-slate-500 py-6 text-center">Chưa có bản sản xuất nào.</p>';
      list.scrollTop = prevScroll;
    }
    if (syncActive && directorActive) {
      const fresh = directorWorkflows.find(w => w.workflow_id === directorActive.workflow_id);
      if (fresh) { directorActive = fresh; renderDirectorShell(); }
    }
  } catch (error) {
    if (!list.innerHTML || list.innerHTML.includes('Đang tải…')) {
      list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`;
    }
  }
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

    directorShellFp = '';
    directorOperationsFp = '';
    directorRevisionsFp = '';
    directorContentFp = { workspace: '', review: '', mix: '', delivery: '', final: '' };
    directorUserSelectedView = false;

    const gate = directorActive.human_action?.action_type;
    directorLastGateType = gate || null;
    if (directorActive.status === 'waiting_for_human' && ['audio_quality_review', 'narration_acceptance'].includes(gate)) {
      directorView = 'review';
    } else if (directorActive.status === 'waiting_for_human' && gate === 'final_audio_approval') {
      directorView = 'delivery';
    } else if (directorActive.status === 'completed') {
      directorView = 'final';
    } else {
      directorView = 'workspace';
    }

    renderDirectorShell(true);
    scheduleDirectorPolling();
  } catch (error) { showToast('error', escapeHtml(error.message)); }
}

function renderDirectorShell(force = false) {
  const workflow = directorActive;
  if (!workflow) return;
  const gate = workflow.human_action?.action_type;

  const shellFp = `${workflow.workflow_id}|${workflow.status}|${workflow.updated_at}|${gate || ''}|${(workflow.steps || []).map(s => `${s.name}:${s.status}:${s.progress_percent}`).join(',')}`;
  if (force || shellFp !== directorShellFp) {
    directorShellFp = shellFp;
    document.getElementById('directorActiveTitle').textContent = directorReview?.title || workflow.project_id;
    document.getElementById('directorActiveMeta').textContent = `${workflow.workflow_id} · ${directorStatusLabel(workflow.status)} · cập nhật ${workflow.updated_at}`;
    document.getElementById('directorFlowGuide').innerHTML = renderDirectorFlowGuide(workflow);
    document.getElementById('directorProgress').innerHTML = workflow.steps.map(step => `<div class="rounded p-2 border border-[#3F3A46] text-center"><div class="text-[10px] ${step.status === 'completed' ? 'text-emerald-400' : step.status === 'running' ? 'text-purple-300' : 'text-slate-500'}">${escapeHtml(directorStepLabel(step.name))}</div><div class="text-[9px] text-slate-500">${escapeHtml(directorStatusLabel(step.status))}</div></div>`).join('');
    
    const actions = document.getElementById('directorGateActions');
    if (workflow.status === 'waiting_for_human' && gate) {
      if (gate === 'audio_quality_review') {
        actions.innerHTML = '<button onclick="showDirectorView(\'review\', true)" class="px-3 py-2 rounded-lg bg-purple-600 text-white text-xs font-bold">Mở đánh giá chất lượng</button><button onclick="cancelDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Hủy</button>';
      } else {
        const label = gate === 'narration_acceptance' ? 'Duyệt toàn bộ giọng đọc & tiếp tục' : gate === 'final_audio_approval' ? 'Duyệt bản master này & xuất file' : 'Tiếp tục';
        actions.innerHTML = `<button data-director-gate onclick="approveDirectorGate(true)" class="px-3 py-2 rounded-lg bg-emerald-600 text-white text-xs font-bold">${label}</button><button data-director-gate onclick="approveDirectorGate(false)" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Từ chối</button>`;
      }
    } else if (['queued', 'running', 'cancelling'].includes(workflow.status)) {
      actions.innerHTML = '<button onclick="cancelDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-red-950 text-red-300 text-xs">Hủy</button>';
    } else if (workflow.status === 'interrupted') {
      actions.innerHTML = '<button onclick="resumeDirectorWorkflow()" class="px-3 py-2 rounded-lg bg-purple-600 text-white text-xs">Tiếp tục từ trạng thái đã lưu</button>';
    } else actions.innerHTML = '';
  }

  renderDirectorOperations(force);
  renderDirectorPendingRevisions(force);

  if (gate && gate !== directorLastGateType) {
    directorLastGateType = gate;
    if (!directorUserSelectedView) {
      if (['audio_quality_review', 'narration_acceptance'].includes(gate)) directorView = 'review';
      else if (gate === 'final_audio_approval') directorView = 'delivery';
    }
  }

  showDirectorView(directorView, false, force);
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

function renderDirectorOperations(force = false) {
  const panel = document.getElementById('directorOperations');
  if (!panel) return;
  const visible = directorOperations.filter(op => ['queued','running','cancelling','interrupted','failed'].includes(op.status)).slice(0, 5);
  panel.classList.toggle('hidden', !visible.length);
  const fp = visible.map(op => `${op.id}:${op.status}:${op.progress_percent}:${op.stage}`).join(';');
  if (!force && fp === directorOperationsFp) return;
  directorOperationsFp = fp;
  panel.innerHTML = visible.length ? `<h4 class="text-xs font-bold text-white mb-3">Tác vụ đang xử lý</h4>${visible.map(op => `<div class="mb-3 last:mb-0"><div class="flex justify-between text-[11px]"><b>${escapeHtml(directorStepLabel(op.operation))}${op.beat_id ? ` · ${escapeHtml(op.beat_id)}` : ''}</b><span>${escapeHtml(directorStatusLabel(op.status))}</span></div><div class="h-1.5 bg-[#3F3A46] rounded mt-1"><div class="h-1.5 bg-purple-500 rounded" style="width:${Math.max(0, Math.min(100, op.progress_percent || 0))}%"></div></div><div class="flex justify-between items-center mt-1 text-[9px] text-slate-500 font-mono"><span>${escapeHtml(op.id)} · ${escapeHtml(op.stage || 'đang chờ')} · ${Math.round(op.progress_percent || 0)}%</span>${['queued','running'].includes(op.status) ? `<button onclick="cancelDirectorOperation('${escapeHtml(op.id)}')" class="text-red-400">Hủy</button>` : ''}</div></div>`).join('')}` : '';
}

function renderDirectorPendingRevisions(force = false) {
  const panel = document.getElementById('directorPendingRevisions');
  if (!panel) return;
  const pendingIds = directorRevisions?.state?.pending_revision_ids || [];
  const events = (directorRevisions?.events || []).filter(event => pendingIds.includes(event.revision_id));
  panel.classList.toggle('hidden', !events.length);
  const fp = events.map(e => `${e.revision_id}:${e.revision_type}:${e.beat_id || ''}`).join(';');
  if (!force && fp === directorRevisionsFp) return;
  directorRevisionsFp = fp;
  panel.innerHTML = events.length ? `<div class="flex flex-wrap justify-between gap-3"><div><h4 class="text-xs font-bold text-amber-300">Chỉnh sửa chưa tái tạo</h4>${events.map(event => `<p class="text-[11px] text-slate-300 mt-1"><b>${escapeHtml(event.beat_id || event.affected_beats?.join(', ') || 'Dự án')}</b> · ${escapeHtml(event.revision_type.replaceAll('_',' '))}</p>`).join('')}</div><button onclick="reproduceDirectorProject()" class="self-end px-3 py-2 rounded bg-amber-600 text-white text-xs font-bold">Tái tạo các thay đổi</button></div>` : '';
}

function showDirectorView(view, userInitiated = false, force = false) {
  if (userInitiated || (window.event && window.event.type === 'click')) {
    directorUserSelectedView = true;
  }
  directorView = view;
  document.querySelectorAll('#directorViews button').forEach(button => {
    button.className = `px-3 py-2 rounded-lg text-xs whitespace-nowrap ${button.dataset.view === view ? 'bg-purple-600 text-white font-bold' : 'bg-[#231F2A] text-slate-300'}`;
  });
  const content = document.getElementById('directorViewContent');
  if (!directorActive || !content) return;

  const isInputFocused = document.activeElement && content.contains(document.activeElement) && ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (!force && isInputFocused) return;

  const hasPlayingAudio = Array.from(content.querySelectorAll('audio')).some(a => !a.paused && !a.ended && a.currentTime > 0);
  if (!force && hasPlayingAudio && !userInitiated) return;

  if (view === 'review') {
    const fp = JSON.stringify((directorReview?.beats || []).map(b => [b.beat_id, b.selected_attempt, b.render_status, b.available_attempts?.length, b.qc_summary?.qc_score ?? b.qc_summary?.score ?? b.qc_summary?.overall_score])) + `|${directorActive.status}|${directorActive.human_action?.action_type}`;
    if (force || userInitiated || fp !== directorContentFp.review || !content.innerHTML.trim()) {
      directorContentFp.review = fp;
      const prevScroll = content.scrollTop;
      content.innerHTML = renderDirectorReview();
      content.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`);
      if (!userInitiated) content.scrollTop = prevScroll;
    }
  } else if (view === 'mix') {
    const fp = JSON.stringify((directorActive.steps || []).filter(s => ['prepare_mix','mix','master'].includes(s.name)).map(s => [s.name, s.status, s.result_summary]));
    if (force || userInitiated || fp !== directorContentFp.mix || !content.innerHTML.trim()) {
      directorContentFp.mix = fp;
      const prevScroll = content.scrollTop;
      content.innerHTML = renderDirectorMix();
      content.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`);
      if (!userInitiated) content.scrollTop = prevScroll;
    }
  } else if (view === 'delivery') {
    renderDirectorDelivery(content, force, userInitiated);
  } else if (view === 'final') {
    renderDirectorFinal(content, force, userInitiated);
  } else {
    // workspace
    const gaps = [...(directorReview?.required_resource_gaps || []), ...(directorReview?.recommended_resource_gaps || [])];
    const fp = `${directorSource?.sha256 || ''}|${directorReview?.source_script_sha256 || ''}|${directorReview?.resource_readiness || ''}|${gaps.map(g => `${g.resource_id || g.term}:${g.priority}`).join(';')}|${(directorReview?.beats || []).map(b => `${b.beat_id}:${b.render_status}`).join(';')}`;
    if (force || userInitiated || fp !== directorContentFp.workspace || !content.innerHTML.trim()) {
      directorContentFp.workspace = fp;
      const prevScroll = content.scrollTop;
      content.innerHTML = renderDirectorWorkspace();
      content.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`);
      if (!userInitiated) content.scrollTop = prevScroll;
    }
  }
}

function renderDirectorWorkspace() {
  if (!directorReview) return '<p class="text-xs text-slate-500">Nội dung duyệt sẽ xuất hiện sau khi tạo dự án.</p>';
  const gaps = [...directorReview.required_resource_gaps, ...directorReview.recommended_resource_gaps];
  return `<h4 class="text-xs font-bold text-white mb-1">Kịch bản gốc (không thể sửa)</h4><p class="text-[9px] text-slate-500 font-mono mb-3">SHA-256 ${escapeHtml(directorSource?.sha256 || directorReview.source_script_sha256)}</p><div class="p-3 rounded bg-[#0E0C12] text-xs text-slate-300 whitespace-pre-wrap">${escapeHtml(directorSource?.script_text || directorReview.script_excerpt)}</div>
    <div class="grid md:grid-cols-2 gap-3 mt-4"><div><h4 class="text-xs font-bold text-white mb-2">Các đoạn giọng đọc</h4>${sortDirectorBeatsByAttention(directorReview.beats).map(b => `<button onclick="openDirectorBeat('${escapeHtml(b.beat_id)}')" class="block w-full text-left p-2 mb-1 rounded bg-[#0E0C12] text-xs ${directorBeatNeedsAttention(b) ? 'border border-amber-700/50' : ''}"><b class="text-white">${escapeHtml(b.beat_id)}</b> <span class="text-slate-400">${escapeHtml(b.emotion)} · năng lượng ${b.energy} · ${escapeHtml(directorStatusLabel(b.render_status))}</span>${directorBeatNeedsAttention(b) ? ' <span class="text-amber-400 text-[10px]">● cần chú ý</span>' : ''}</button>`).join('')}</div><div>${renderDirectorResourceReadiness(directorReview.resource_readiness, gaps)}</div></div>`;
}

function renderDirectorResourceReadiness(readiness, gaps) {
  const pct = Math.max(0, Math.min(100, readiness ?? 100));
  const barColor = pct >= 80 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';
  const pctColor = pct >= 80 ? 'text-emerald-400' : pct >= 40 ? 'text-amber-400' : 'text-red-400';
  const requiredCount = gaps.filter(g => g.priority === 'required').length;

  const header = `<div class="flex items-center justify-between mb-1"><h4 class="text-xs font-bold text-white">Mức sẵn sàng tài nguyên</h4><span class="text-xs font-mono font-bold ${pctColor}">${readiness ?? '—'}%</span></div>
    <div class="h-1.5 rounded-full bg-[#231F2A] overflow-hidden mb-2"><div class="h-full ${barColor} rounded-full transition-all" style="width:${pct}%"></div></div>`;

  if (!gaps.length) {
    return `${header}<p class="text-xs text-emerald-400">✓ Không thiếu tài nguyên nào.</p>`;
  }

  const pronunciationGaps = gaps.filter(g => g.resource_type === 'knowledge');
  const assetGaps = gaps.filter(g => g.resource_type !== 'knowledge');
  const summary = `<p class="text-[10px] text-slate-400 mb-2">${requiredCount ? `<span class="text-red-400 font-bold">${requiredCount} bắt buộc</span> · ` : ''}${gaps.length} mục cần xử lý</p>`;

  const pronBulkBtn = pronunciationGaps.length > 1 ? `<button onclick="confirmAllDirectorPronunciations(this)" class="text-[10px] text-purple-300 hover:text-purple-200 underline shrink-0">Xác nhận tất cả theo chính tả gốc</button>` : '';
  const pronSection = pronunciationGaps.length ? `<div class="mb-3"><div class="flex items-center justify-between gap-2 mb-1.5"><h5 class="text-[10px] font-bold text-slate-300 uppercase tracking-wider">Cần xác nhận phát âm (${pronunciationGaps.length})</h5>${pronBulkBtn}</div><div class="space-y-1.5 director-pron-list">${pronunciationGaps.map(renderDirectorPronunciationGap).join('')}</div></div>` : '';
  const assetSection = assetGaps.length ? `<div><h5 class="text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-1.5">Tài nguyên âm thanh còn thiếu (${assetGaps.length})</h5><div class="space-y-2">${assetGaps.map(renderDirectorAssetGap).join('')}</div></div>` : '';

  return `${header}${summary}${pronSection}${assetSection}`;
}

function renderDirectorPronunciationGap(gap) {
  const required = gap.priority === 'required';
  if (!gap.term) return `<p class="text-[10px] text-slate-500">Chưa có từ cần xác nhận phát âm.</p>`;
  return `<div class="flex items-center gap-1.5 p-1.5 rounded border ${required ? 'bg-red-950/30 border-red-800/60' : 'bg-amber-950/30 border-amber-800/60'}" data-pron-term="${escapeHtml(gap.term)}">
    <b class="text-white text-xs shrink-0" title="Thuật ngữ cần xác nhận phát âm">${escapeHtml(gap.term)}</b>
    <input class="director-input flex-1 min-w-0" value="${escapeHtml(gap.term)}" placeholder="Cách phát âm đã xác nhận..." onkeydown="if(event.key==='Enter'){event.preventDefault();this.nextElementSibling.click();}">
    <button onclick="resolveDirectorPronunciation('${escapeHtml(gap.term)}',this)" class="px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 text-[10px] text-white shrink-0">Xác nhận</button>
  </div>`;
}

async function confirmAllDirectorPronunciations(button) {
  const rows = document.querySelectorAll('.director-pron-list [data-pron-term]');
  if (!rows.length) return;
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = 'Đang xác nhận...';
  try {
    const results = await Promise.allSettled(Array.from(rows).map(row => {
      const term = row.getAttribute('data-pron-term');
      const phonetic = row.querySelector('input')?.value.trim() || term;
      return directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/resources/pronunciations`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ term, phonetic, actor_id: 'director-console' }),
      });
    }));
    const failed = results.filter(r => r.status === 'rejected').length;
    if (failed) showToast('warning', `Đã xác nhận ${rows.length - failed}/${rows.length} từ, ${failed} từ bị lỗi.`);
    else showToast('success', `Đã xác nhận toàn bộ ${rows.length} từ theo chính tả gốc.`);
    await refreshDirectorActive();
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function renderDirectorAssetGap(gap) {
  const required = gap.priority === 'required';
  const wanted = gap.wanted || {};
  const label = gap.intent || gap.description || 'hiệu ứng âm thanh phù hợp';
  const details = `<div class="mt-1.5 text-[10px] text-slate-300 flex flex-wrap gap-x-3">${wanted.duration ? `<span><b>Thời lượng:</b> ${escapeHtml(String(wanted.duration))}</span>` : ''}${wanted.intensity ? `<span><b>Cường độ:</b> ${escapeHtml(String(wanted.intensity))}/5</span>` : ''}</div>${gap.narrative_context?.text ? `<p class="mt-1 text-[10px] text-slate-300"><b>Ngữ cảnh:</b> ${escapeHtml(gap.narrative_context.text)}</p>` : ''}${gap.suggested_search?.length ? `<p class="mt-1 text-[10px] text-slate-300"><b>Từ khóa:</b> ${escapeHtml(gap.suggested_search.slice(0, 3).join(' · '))}</p>` : ''}`;
  const canSuggest = ['sfx', 'ambience'].includes(gap.resource_type);
  const suggestBtn = canSuggest ? `<button type="button" onclick="directorFindAssetSuggestions('${escapeHtml(gap.resource_id)}',this)" class="px-2 rounded bg-[#231F2A] hover:bg-purple-900/40 text-[10px] text-purple-300 border border-purple-700/40">🔍 Tìm gợi ý</button>` : '';
  return `<div class="director-asset-gap p-2 rounded border ${required ? 'bg-red-950/30 border-red-800' : 'bg-amber-950/30 border-amber-800'} text-xs text-amber-200">
    <div class="flex justify-between items-start gap-2"><b class="text-white">${escapeHtml(label)}</b><b class="text-[9px] uppercase shrink-0">${escapeHtml(gap.priority)}</b></div>
    ${details}
    <div class="flex flex-wrap gap-1 mt-2"><input class="director-input flex-1 min-w-40" placeholder="Mã tài nguyên hiện có"><button onclick="bindDirectorResource('${escapeHtml(gap.resource_id)}',this)" class="px-2 rounded bg-purple-700 text-[10px]">Liên kết</button>${suggestBtn}${required ? '' : `<button onclick="omitDirectorResource('${escapeHtml(gap.resource_id)}')" class="px-2 rounded bg-[#231F2A] text-[10px]">Bỏ qua</button>`}</div>
    <div class="director-asset-suggestions mt-2 space-y-1"></div>
  </div>`;
}

function findDirectorGapById(resourceId) {
  const gaps = [...(directorReview?.required_resource_gaps || []), ...(directorReview?.recommended_resource_gaps || [])];
  return gaps.find(g => g.resource_id === resourceId);
}

async function directorFindAssetSuggestions(resourceId, button) {
  const gap = findDirectorGapById(resourceId);
  const container = button.closest('.director-asset-gap')?.querySelector('.director-asset-suggestions');
  if (!gap || !container) return;
  button.disabled = true;
  const originalLabel = button.innerHTML;
  button.innerHTML = '<span class="material-symbols-outlined animate-spin text-[12px] align-middle">progress_activity</span> Đang tìm...';
  try {
    const wanted = gap.wanted || {};
    const results = await directorFetch('/api/v1/voice-assets/match', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        intents: [gap.intent || gap.description || 'sound effect'],
        category: gap.resource_type,
        duration_ms: gap.duration_hint_ms || null,
        loopable: gap.loopable || null,
        story_context: gap.story_context || null,
        top_k: 5,
      }),
    });
    container.innerHTML = results.length ? results.map(r => `
      <div class="flex items-center gap-1.5 p-1.5 rounded bg-[#18151E] border border-[#3F3A46]">
        <audio controls preload="none" class="h-7 w-32 shrink-0" src="/api/v1/voice-assets/${encodeURIComponent(r.asset_id)}/preview"></audio>
        <span class="text-[10px] text-slate-300 flex-1 truncate" title="${escapeHtml((r.match_reasons || []).join(', '))}">${escapeHtml(r.asset_id)} <b class="${r.match_score >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}">${Math.round(r.match_score * 100)}%</b>${r.exact_or_substitute === 'substitute' ? ' <span class="text-slate-500">(thay thế)</span>' : ''}</span>
        <button onclick="bindDirectorResource('${escapeHtml(resourceId)}',this,'${escapeHtml(r.asset_id)}')" class="px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 text-[10px] text-white shrink-0">Dùng cái này</button>
      </div>`).join('') : '<p class="text-[10px] text-slate-500">Không tìm thấy tài nguyên phù hợp trong thư viện.</p>';
  } catch (error) {
    container.innerHTML = `<p class="text-[10px] text-red-400">${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.innerHTML = originalLabel;
  }
}

function renderDirectorReview() {
  if (!directorReview?.beats?.length) return '<p class="text-xs text-slate-500">Chưa có đoạn giọng đọc nào.</p>';
  const gated = directorActive.status === 'waiting_for_human' && directorActive.human_action?.action_type === 'narration_acceptance';
  return `${gated ? '<div class="mb-3 p-3 rounded-lg border border-amber-500/50 bg-amber-950/30 text-xs text-amber-200"><b>Cần duyệt giọng đọc:</b> nghe các bản đã chọn. Nút xanh phía trên duyệt toàn bộ một lần.</div>' : ''}<div class="space-y-3">${sortDirectorBeatsByAttention(directorReview.beats).map(beat => `<article class="p-3 rounded-lg bg-[#0E0C12] border ${directorBeatNeedsAttention(beat) ? 'border-amber-600/60' : 'border-emerald-700/50'}"><div class="flex flex-wrap justify-between gap-2"><div><b class="text-white text-xs">${escapeHtml(beat.beat_id)} · ${escapeHtml(beat.emotion)}</b><p class="text-[11px] text-slate-400 mt-1">${escapeHtml(beat.source_text)}</p></div><span class="text-[10px] text-slate-400">bản đã chọn ${beat.selected_attempt ?? 'chưa có'} · QC ${beat.qc_summary?.qc_score ?? beat.qc_summary?.score ?? beat.qc_summary?.overall_score ?? '—'}</span></div>
    <div class="flex flex-wrap gap-2 mt-3">${beat.available_attempts.map(a => `<div class="flex items-center gap-1"><audio controls preload="none" class="h-8 w-44" src="/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(a.artifact_id)}"></audio><button onclick="selectDirectorAttempt('${escapeHtml(beat.beat_id)}',${a.attempt_id})" class="px-2 py-1 rounded ${a.selected ? 'bg-emerald-700' : 'bg-[#231F2A]'} text-[10px] text-white">Bản ${a.attempt_id}${a.selected ? ' · đã chọn' : ''}</button></div>`).join('')}</div>
    <div class="flex gap-2 mt-3"><button onclick="openDirectorBeat('${escapeHtml(beat.beat_id)}')" class="px-3 py-1 rounded bg-purple-600 text-white text-[10px]">Mở chi tiết đoạn</button></div></article>`).join('')}</div>`;
}

function renderDirectorMix() {
  const done = name => directorActive.steps.find(s => s.name === name);
  return `<div class="grid md:grid-cols-3 gap-3">${['prepare_mix','mix','master'].map(name => { const step = done(name); return `<div class="p-4 rounded bg-[#0E0C12]"><b class="text-white text-xs">${escapeHtml(directorStepLabel(name))}</b><p class="text-[11px] text-slate-400 mt-2">${escapeHtml(directorStatusLabel(step?.status || 'pending'))}</p><p class="text-[10px] text-slate-500">${escapeHtml(JSON.stringify(step?.result_summary || {}))}</p></div>`; }).join('')}</div>`;
}

async function renderDirectorDelivery(content, force = false, userInitiated = false) {
  if (!content.innerHTML.trim()) {
    content.innerHTML = '<p class="text-xs text-slate-500">Đang tải danh sách file…</p>';
  }
  try {
    const [data, mixPlan] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/artifacts`),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/mix-plan`).catch(() => null),
    ]);
    if (directorView !== 'delivery') return;

    const gate = directorActive.human_action?.action_type === 'final_audio_approval' ? directorActive.human_action.items?.[0] : null;
    const metrics = directorOperations.find(op => op.operation === 'master' && op.status === 'completed')?.result?.metrics || {};
    const masterStatus = directorReview?.artifact_status?.find(item => item.artifact_id === 'master_wav');
    const masterVerified = masterStatus?.exists && masterStatus?.fresh && masterStatus?.sha256 === gate?.sha256;
    
    const fp = `${data.artifacts.map(a => `${a.id}:${a.sha256}`).join('|')}:${gate?.sha256 || ''}:${masterVerified}:${metrics.output_lufs || ''}:${directorActive.status}`;
    if (!force && !userInitiated && fp === directorContentFp.delivery && !content.innerHTML.includes('Đang tải danh sách file…')) {
      return;
    }
    directorContentFp.delivery = fp;

    const masterLabel = masterVerified ? 'ĐÃ XÁC MINH' : masterStatus?.exists && !masterStatus?.fresh ? 'ĐÃ CŨ' : 'CHƯA XÁC MINH';
    const masterApproval = masterVerified ? '<button data-director-gate onclick="approveDirectorGate(true)" class="px-3 py-2 rounded bg-emerald-600 text-white text-xs font-bold">Duyệt bản master này & xuất file</button>' : '<span class="px-3 py-2 rounded bg-[#231F2A] text-slate-500 text-xs">Chưa thể duyệt</span>';
    const masterCard = gate ? `<div class="mb-4 p-4 rounded-lg border border-amber-500/50 bg-amber-950/20"><div class="flex flex-wrap justify-between gap-3"><div><h4 class="font-bold text-white">master.wav</h4><p class="text-[10px] text-slate-400 font-mono break-all">SHA-256 ${escapeHtml(gate.sha256)}</p><p class="text-[10px] text-slate-400">Thời lượng ${mixPlan?.duration_ms ? `${Math.round(mixPlan.duration_ms)} ms` : 'chưa có'} · Âm lượng ${metrics.output_lufs ?? 'chưa có'} LUFS · Dòng dữ liệu <span class="${masterVerified ? 'text-emerald-400' : 'text-amber-400'}">${masterLabel}</span></p></div>${masterApproval}</div><p class="text-[11px] text-amber-200 mt-2">Hãy nghe toàn bộ file này. Khi duyệt, SHA-256 hiện tại sẽ được khóa vào phê duyệt.</p><audio controls preload="metadata" class="w-full h-9 mt-3" src="${escapeHtml(gate.download_url)}"></audio></div>` : '';
    
    const artifactsHtml = data.artifacts.map(a => {
      const lineage = directorReview?.artifact_status?.find(item => item.artifact_id === a.id);
      const valid = lineage?.exists && lineage?.fresh && lineage?.sha256 === a.sha256;
      const label = valid ? 'ĐÃ XÁC MINH' : lineage?.exists && !lineage?.fresh ? 'ĐÃ CŨ' : 'CHƯA XÁC MINH';
      const downloadUrl = escapeHtml(lineage?.download_url || a.download_url || `/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(a.id)}`);
      const download = valid ? `<a class="px-3 py-1.5 rounded bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold inline-flex items-center gap-1" href="${downloadUrl}" download><span class="material-symbols-outlined text-[14px]">download</span> Tải xuống</a>` : '<span class="px-3 py-1 rounded bg-[#231F2A] text-slate-500 text-xs">Chưa thể tải</span>';
      const isAudio = a.type === 'final_wav' || a.type === 'final_mp3' || a.id.endsWith('_wav') || a.id.endsWith('_mp3') || /\.(wav|mp3)$/i.test(a.filename || '');
      const audioPlayer = isAudio ? `<div class="mt-2 w-full pt-2 border-t border-[#231F2A]"><div class="flex items-center justify-between text-[10px] text-slate-400 mb-1"><span>Nghe trực tiếp ${escapeHtml(a.filename || a.id)}</span><span>${formatDirectorBytes(a.size_bytes)}</span></div><audio controls preload="metadata" class="w-full h-8" src="${downloadUrl}"></audio></div>` : '';

      return `<div class="p-3 mb-2 rounded bg-[#0E0C12] border border-[#231F2A]"><div class="flex flex-wrap items-center justify-between gap-2"><div><b class="text-xs text-white">${escapeHtml(a.id)}</b> <span class="text-[10px] text-slate-400">(${formatDirectorBytes(a.size_bytes)})</span><p class="text-[10px] text-slate-500 font-mono">SHA-256 ${escapeHtml(a.sha256 || 'not reported')}</p><p class="text-[10px] ${valid ? 'text-emerald-400' : 'text-amber-400'} font-semibold mt-0.5">${label}</p></div>${download}</div>${audioPlayer}</div>`;
    }).join('') || '<p class="text-xs text-slate-500">Chưa có file bàn giao.</p>';

    const scriptText = directorSource?.script_text || directorReview?.script_excerpt || '';
    const scriptBox = scriptText ? `<details class="mt-4 p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46] text-xs"><summary class="font-bold text-white cursor-pointer select-none flex items-center justify-between"><span>Kịch bản gốc đối chiếu (SHA-256 ${escapeHtml((directorSource?.sha256 || directorReview?.source_script_sha256 || '').slice(0, 16))}...)</span><span class="text-[10px] text-purple-300 font-normal">Bấm để mở/đóng</span></summary><div class="mt-3 p-3 rounded bg-[#18151E] text-slate-300 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">${escapeHtml(scriptText)}</div><div class="mt-2 flex justify-end"><button onclick="copyDirectorScript()" class="px-2.5 py-1 rounded bg-[#231F2A] hover:bg-purple-800 text-slate-300 text-[10px]">Sao chép kịch bản</button></div></details>` : '';

    const prevScroll = content.scrollTop;
    content.innerHTML = `${masterCard}<div class="mb-3 flex items-center justify-between">${directorStatusChip(directorActive.status)} <span class="text-xs text-slate-400">Chỉ file mới nhất và đã xác minh mới được tải.</span></div>${artifactsHtml}${scriptBox}`;
    if (!userInitiated) content.scrollTop = prevScroll;
  } catch (error) {
    if (!content.innerHTML.trim() || content.innerHTML.includes('Đang tải danh sách file…')) {
      content.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`;
    }
  }
}

async function renderDirectorFinal(content, force = false, userInitiated = false) {
  if (!content.innerHTML.trim()) {
    content.innerHTML = '<p class="text-xs text-slate-500">Đang tải bảng tổng kết và tra soát…</p>';
  }
  try {
    const [data, mixPlan] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/artifacts`),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/mix-plan`).catch(() => null),
    ]);
    if (directorView !== 'final') return;

    const fp = `${directorActive.workflow_id}|${directorActive.status}|${data.artifacts.map(a => `${a.id}:${a.sha256}`).join('|')}|${directorReview?.beats?.length || 0}|${directorReview?.resource_readiness || ''}`;
    if (!force && !userInitiated && fp === directorContentFp.final && !content.innerHTML.includes('Đang tải')) {
      return;
    }
    directorContentFp.final = fp;

    const beats = directorReview?.beats || [];
    const totalDuration = mixPlan?.duration_ms || directorActive.result?.manifest?.artifacts?.[0]?.duration_ms || 0;
    const avgScore = beats.length ? (beats.reduce((acc, b) => acc + (b.qc_summary?.qc_score ?? b.qc_summary?.score ?? 85), 0) / beats.length).toFixed(1) : '—';
    const scriptText = directorSource?.script_text || directorReview?.script_excerpt || '';
    const scriptSha = directorSource?.sha256 || directorReview?.source_script_sha256 || '—';
    const wordCount = scriptText ? scriptText.trim().split(/\s+/).length : 0;

    const finalWav = data.artifacts.find(a => a.id === 'final_wav') || data.artifacts.find(a => a.id === 'master_wav');
    const finalMp3 = data.artifacts.find(a => a.id === 'final_mp3');

    const audioDeliverables = [finalWav, finalMp3].filter(Boolean).map(art => {
      const lineage = directorReview?.artifact_status?.find(item => item.artifact_id === art.id);
      const isVerified = lineage?.exists && lineage?.fresh && lineage?.sha256 === art.sha256;
      const downloadUrl = escapeHtml(lineage?.download_url || art.download_url || `/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(art.id)}`);
      return `<div class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46] space-y-2">
        <div class="flex flex-wrap justify-between items-center gap-2">
          <div>
            <b class="text-xs text-white uppercase">${art.id === 'final_wav' ? 'Bản xuất Lossless WAV' : art.id === 'final_mp3' ? 'Bản xuất nén MP3 (192kbps)' : 'Bản Master WAV'}</b>
            <span class="text-[10px] text-slate-400 ml-2">(${formatDirectorBytes(art.size_bytes)})</span>
            <span class="ml-2 text-[10px] ${isVerified ? 'text-emerald-400' : 'text-amber-400'} font-semibold">${isVerified ? '✓ ĐÃ XÁC MINH' : 'CHƯA XÁC MINH'}</span>
          </div>
          <a href="${downloadUrl}" download class="px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-500 text-white text-[11px] font-bold inline-flex items-center gap-1">
            <span class="material-symbols-outlined text-[13px]">download</span> Tải file
          </a>
        </div>
        <audio controls preload="metadata" class="w-full h-8" src="${downloadUrl}"></audio>
        <p class="text-[9px] text-slate-500 font-mono break-all">SHA-256: ${escapeHtml(art.sha256)}</p>
      </div>`;
    }).join('');

    const beatRows = beats.map((b) => {
      const attempt = b.available_attempts?.find(a => a.attempt_id === b.selected_attempt) || b.available_attempts?.[0];
      const audioUrl = attempt?.artifact_id ? `/api/v1/voice-projects/${encodeURIComponent(directorActive.project_id)}/artifacts/${encodeURIComponent(attempt.artifact_id)}` : null;
      const qcScore = b.qc_summary?.qc_score ?? b.qc_summary?.score ?? attempt?.qc_score ?? '—';
      const qcPass = (b.qc_summary?.qc_verdict || attempt?.qc_verdict || b.render_status) === 'pass' || (typeof qcScore === 'number' && qcScore >= 80);

      return `<tr class="border-b border-[#231F2A] hover:bg-[#1C1824] text-[11px]">
        <td class="p-2.5 align-top font-bold text-white whitespace-nowrap">
          <div>${escapeHtml(b.beat_id)}</div>
          <div class="text-[9px] text-slate-500 uppercase">${escapeHtml(b.role || 'beat')}</div>
        </td>
        <td class="p-2.5 align-top text-slate-300 leading-relaxed min-w-[240px]">
          ${escapeHtml(b.source_text)}
          <div class="mt-1 flex flex-wrap gap-2 text-[9px] text-slate-500 font-mono">
            <span>Cảm xúc: <b class="text-purple-300">${escapeHtml(b.emotion || 'neutral')}</b></span>
            <span>Năng lượng: <b class="text-purple-300">${b.energy ?? 1}</b></span>
            <span>Nghỉ sau: <b class="text-purple-300">${b.pause_after_ms ?? 0} ms</b></span>
          </div>
        </td>
        <td class="p-2.5 align-top whitespace-nowrap min-w-[180px]">
          ${audioUrl ? `<audio controls preload="none" class="h-7 w-40" src="${escapeHtml(audioUrl)}"></audio><div class="text-[9px] text-slate-500 mt-0.5">Bản thu #${attempt.attempt_id} (${Math.round((attempt.duration_ms || 0) / 1000)}s)</div>` : '<span class="text-slate-500 text-[10px]">Chưa có audio</span>'}
        </td>
        <td class="p-2.5 align-top whitespace-nowrap">
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${qcPass ? 'bg-emerald-950/60 text-emerald-300' : 'bg-amber-950/60 text-amber-300'}">${qcScore} đ</span>
          <div class="text-[9px] text-slate-500 uppercase mt-0.5">${escapeHtml(b.render_status || 'ok')}</div>
        </td>
      </tr>`;
    }).join('') || '<tr><td colspan="4" class="p-4 text-center text-slate-500">Không có dữ liệu đoạn thoại.</td></tr>';

    const pronunciations = [];
    beats.forEach(b => {
      const terms = b.voice_direction?.pronunciation || {};
      for (const [k, v] of Object.entries(terms)) {
        if (!pronunciations.some(p => p.k === k)) pronunciations.push({k, v});
      }
    });
    const pronHtml = pronunciations.length ? pronunciations.map(p => `<span class="px-2 py-1 rounded bg-[#231F2A] text-slate-300 text-[10px] font-mono"><b class="text-white">${escapeHtml(p.k)}</b>: "${escapeHtml(p.v)}"</span>`).join(' ') : '<span class="text-slate-500 text-[11px]">Không có từ phát âm đặc biệt.</span>';

    const prevScroll = content.scrollTop;
    content.innerHTML = `
      <div class="space-y-4">
        <!-- Metric Cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          <div class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46]">
            <div class="text-[10px] uppercase text-slate-400">Trạng thái</div>
            <div class="mt-1">${directorStatusChip(directorActive.status)}</div>
            <div class="text-[9px] text-slate-500 font-mono mt-1 truncate">${escapeHtml(directorActive.workflow_id)}</div>
          </div>
          <div class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46]">
            <div class="text-[10px] uppercase text-slate-400">Thời lượng hoàn chỉnh</div>
            <div class="text-sm font-bold text-white mt-1">${formatDirectorDuration(totalDuration)}</div>
            <div class="text-[9px] text-slate-500 mt-1">${beats.length} đoạn thoại · ${wordCount} từ</div>
          </div>
          <div class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46]">
            <div class="text-[10px] uppercase text-slate-400">Điểm QC trung bình</div>
            <div class="text-sm font-bold text-emerald-400 mt-1">${avgScore} / 100</div>
            <div class="text-[9px] text-slate-500 mt-1">Hồ sơ: ${escapeHtml(directorActive.policy?.mixing_profile || 'storytelling')}</div>
          </div>
          <div class="p-3 rounded-lg bg-[#0E0C12] border border-[#3F3A46]">
            <div class="text-[10px] uppercase text-slate-400">Mức sẵn sàng tài nguyên</div>
            <div class="text-sm font-bold text-purple-300 mt-1">${directorReview?.resource_readiness ?? 100}%</div>
            <div class="text-[9px] text-slate-500 mt-1">${pronunciations.length} từ đã xác nhận</div>
          </div>
        </div>

        <!-- Audio Deliverables Players -->
        <div>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs font-bold text-white flex items-center gap-1.5">
              <span class="material-symbols-outlined text-purple-400 text-[16px]">play_circle</span>
              Thẻ nghe bản phát hành hoàn chỉnh (Master / Export)
            </h4>
            <span class="text-[10px] text-slate-400">Nghe trực tiếp trước khi phân phối</span>
          </div>
          <div class="grid md:grid-cols-2 gap-3">
            ${audioDeliverables || '<p class="text-xs text-slate-500 p-4 rounded bg-[#0E0C12]">Chưa có file âm thanh xuất xưởng.</p>'}
          </div>
        </div>

        <!-- Original Script Full Inspection Box -->
        <div class="p-3.5 rounded-lg bg-[#0E0C12] border border-[#3F3A46]">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div>
              <h4 class="text-xs font-bold text-white">Kịch bản ban đầu (Toàn văn đối chiếu)</h4>
              <p class="text-[9px] text-slate-400 font-mono mt-0.5">SHA-256: ${escapeHtml(scriptSha)} · ${wordCount} từ · ${scriptText.length} ký tự</p>
            </div>
            <button onclick="copyDirectorScript()" class="px-2.5 py-1 rounded bg-[#231F2A] hover:bg-purple-800 text-white text-[10px] font-medium inline-flex items-center gap-1">
              <span class="material-symbols-outlined text-[13px]">content_copy</span> Sao chép kịch bản
            </button>
          </div>
          <div class="p-3 rounded bg-[#18151E] text-slate-200 text-xs leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto border border-[#231F2A]">${escapeHtml(scriptText)}</div>
        </div>

        <!-- Beat by Beat Table -->
        <div>
          <h4 class="text-xs font-bold text-white mb-2 flex items-center gap-1.5">
            <span class="material-symbols-outlined text-purple-400 text-[16px]">list_alt</span>
            Bảng tra soát chi tiết từng câu thoại (Beat Audit Matrix)
          </h4>
          <div class="overflow-x-auto rounded-lg border border-[#3F3A46] bg-[#0E0C12]">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-[#3F3A46] bg-[#18151E] text-[10px] uppercase text-slate-400">
                  <th class="p-2.5">Mã</th>
                  <th class="p-2.5">Lời thoại & Hướng diễn</th>
                  <th class="p-2.5">Nghe giọng đọc</th>
                  <th class="p-2.5">Đánh giá QC</th>
                </tr>
              </thead>
              <tbody>
                ${beatRows}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Technical Verification & Pronunciations -->
        <div class="p-3.5 rounded-lg bg-[#0E0C12] border border-[#3F3A46] space-y-2">
          <h4 class="text-xs font-bold text-white">Tài nguyên & Tính toàn vẹn dữ liệu (Lineage & Integrity)</h4>
          <div class="text-[11px] text-slate-300">
            <span class="text-slate-400 font-semibold">Phát âm đã khóa:</span>
            <div class="mt-1 flex flex-wrap gap-1.5">${pronHtml}</div>
          </div>
          <div class="pt-2 border-t border-[#231F2A] text-[10px] text-slate-400 flex flex-wrap justify-between gap-2">
            <span>Provider: <b class="text-slate-200">${escapeHtml(directorActive.policy?.provider || 'local')}</b> / Model: <b class="text-slate-200">${escapeHtml(directorActive.policy?.model || 'mặc định')}</b></span>
            <span>Khóa duyệt SHA-256: <b class="text-emerald-400 font-mono">${escapeHtml((directorActive.result?.manifest?.source_master_sha256 || '').slice(0, 16) || 'N/A')}</b></span>
          </div>
        </div>
      </div>
    `;
    if (!userInitiated) content.scrollTop = prevScroll;
  } catch (error) {
    if (!content.innerHTML.trim() || content.innerHTML.includes('Đang tải')) {
      content.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(error.message)}</p>`;
    }
  }
}

async function directorMutation(url, options = {}) {
  try { const result = await directorFetch(url, options); await refreshDirectorActive(); return result; }
  catch (error) { showToast('error', escapeHtml(error.message)); return null; }
}

function directorBeatQcPassed(beat) {
  const qcScore = beat.qc_summary?.qc_score ?? beat.qc_summary?.score ?? beat.qc_summary?.overall_score;
  return beat.qc_summary?.qc_verdict === 'pass' || (typeof qcScore === 'number' && qcScore >= 80);
}

function directorBeatNeedsAttention(beat) {
  return ['failed', 'needs_review', 'error'].includes(beat.render_status) || !beat.selected_attempt || !directorBeatQcPassed(beat);
}

function sortDirectorBeatsByAttention(beats) {
  return [...beats].sort((a, b) => Number(!directorBeatNeedsAttention(a)) - Number(!directorBeatNeedsAttention(b)));
}

async function approveDirectorGate(approved) {
  if (directorGateSubmitting) return;
  const gate = directorActive.human_action;
  if (!gate) return;
  const action = {narration_acceptance:'approve_narration', final_audio_approval:'approve_final_audio'}[gate.action_type];
  if (!action) return showToast('error', `Bước duyệt chưa được hỗ trợ: ${escapeHtml(gate.action_type)}`);

  if (approved && gate.action_type === 'narration_acceptance') {
    const problems = (directorReview?.beats || []).filter(b => !b.selected_attempt || !directorBeatQcPassed(b));
    if (problems.length) {
      const names = problems.slice(0, 5).map(b => b.beat_id).join(', ');
      const more = problems.length > 5 ? ` và ${problems.length - 5} đoạn khác` : '';
      const proceed = confirm(`Có ${problems.length} đoạn cần chú ý trước khi duyệt toàn bộ: ${names}${more}.\n\nLý do: chưa chọn bản thu, hoặc điểm QC dưới 80.\n\nBạn vẫn muốn duyệt TOÀN BỘ giọng đọc ngay bây giờ?`);
      if (!proceed) return;
    }
  }

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

async function bindDirectorResource(resourceId, button, assetIdOverride) {
  const assetId = assetIdOverride || button.parentElement.querySelector('input').value.trim();
  if (!assetId) return showToast('warning', 'Vui lòng nhập mã tài nguyên hiện có.');
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/bind`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resource_id:resourceId,asset_id:assetId,actor_id:'director-console',allow_substitution:true})});
}

async function omitDirectorResource(resourceId) {
  await directorMutation(`/api/v1/voice-projects/${directorActive.project_id}/resources/omit`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resource_id:resourceId,actor_id:'director-console',reason:'Optional resource omitted by director'})});
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
  if (!directorActive || directorRefreshing) return;
  directorRefreshing = true;
  try {
    directorActive = await directorFetch(`/api/v1/voice-workflows/${directorActive.workflow_id}`);
    [directorReview, directorSource, directorRevisions, directorOperations] = await Promise.all([
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/director-review`).catch(() => directorReview),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/script`).catch(() => directorSource),
      directorFetch(`/api/v1/voice-projects/${directorActive.project_id}/revisions`).catch(() => directorRevisions),
      directorFetch(`/api/v1/voice-project-jobs?project_id=${encodeURIComponent(directorActive.project_id)}&limit=20`).catch(() => directorOperations),
    ]);
    renderDirectorShell(false);
    await loadDirectorWorkflows(false);
  } finally {
    directorRefreshing = false;
  }
}

function scheduleDirectorPolling() {
  clearInterval(directorPollTimer);
  directorPollTimer = setInterval(() => {
    if (currentTab !== 'director' || !directorActive) return;
    const activeJob = directorOperations.some(op => ['queued','running','cancelling'].includes(op.status));
    const isWorkflowBusy = ['queued','running','cancelling'].includes(directorActive.status);
    const isWaitingHuman = directorActive.status === 'waiting_for_human';
    
    const now = Date.now();
    if (!activeJob && isWaitingHuman && (now - directorLastPollTime < 7500)) {
      return;
    }
    if (activeJob || isWorkflowBusy || isWaitingHuman) {
      directorLastPollTime = now;
      refreshDirectorActive().catch(() => {});
    }
  }, 2500);
}

window.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.director-input').forEach(el => el.className += ` ${directorInputClass}`));
