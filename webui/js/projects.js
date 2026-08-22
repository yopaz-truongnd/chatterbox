/**
 * Chatterbox TTS Studio - Audio Projects Planner & Two-Stage Confirmation Module
 */

let allProjectsList = [];
let currentProjectFilter = 'all';
let activeProjectId = null;
let activeProjectData = null;
let projectJobPollInterval = null;

function setProjectTopicPrompt(text) {
  const input = document.getElementById('projectTopicInput');
  if (input) {
    input.value = text;
    input.focus();
  }
}

function renderDynamicQuestions(questions, answers = {}) {
  const container = document.getElementById('projectQuestionsList');
  if (!container) return;
  container.innerHTML = '';

  if (!questions || questions.length === 0) {
    container.innerHTML = '<div class="text-slate-400 text-xs italic">Không có câu hỏi nào cần trả lời.</div>';
    return;
  }

  questions.forEach((q, idx) => {
    const qCard = document.createElement('div');
    qCard.className = 'p-3.5 rounded-xl bg-[#14101A] border border-[#3F3A46]/60 space-y-2.5';

    const currentAnswer = answers[q.id] || '';

    let optionsHtml = '';
    if (q.options && q.options.length > 0) {
      optionsHtml = `
        <div class="flex flex-wrap gap-1.5 pt-1">
          ${q.options.map(opt => {
            const isSelected = currentAnswer === opt;
            const btnClass = isSelected
              ? 'bg-purple-600 text-white border-purple-500 font-bold'
              : 'bg-[#231F2A] hover:bg-[#2D2836] text-slate-300 border-[#3F3A46]';
            return `<button type="button" onclick="selectProjectOption('${q.id}', '${opt.replace(/'/g, "\\'")}')" class="px-2.5 py-1 rounded-full text-xs border transition-all cursor-pointer ${btnClass}">${opt}</button>`;
          }).join('')}
        </div>
      `;
    }

    qCard.innerHTML = `
      <div class="flex items-start justify-between gap-2">
        <label class="text-xs font-semibold text-white flex items-center gap-1.5">
          <span class="w-5 h-5 rounded-full bg-purple-900/60 text-purple-300 font-mono text-[11px] flex items-center justify-center border border-purple-700/50">${idx + 1}</span>
          <span>${q.question || q.id}</span>
          ${q.required ? '<span class="text-red-400 font-bold">*</span>' : ''}
        </label>
      </div>
      ${optionsHtml}
      <div>
        <input type="text" id="q_input_${q.id}" data-qid="${q.id}" value="${escapeHtml(currentAnswer)}" placeholder="Hoặc nhập câu trả lời tùy chỉnh..." class="w-full bg-[#18151E] border border-[#3F3A46] rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none transition-colors">
      </div>
    `;

    container.appendChild(qCard);
  });
}

function selectProjectOption(qid, optValue) {
  const input = document.getElementById(`q_input_${qid}`);
  if (input) {
    input.value = optValue;
  }
  // Update button active styles
  const allBtns = document.querySelectorAll(`button[onclick*="selectProjectOption('${qid}'"]`);
  allBtns.forEach(btn => {
    if (btn.textContent.trim() === optValue) {
      btn.className = 'px-2.5 py-1 rounded-full text-xs border transition-all cursor-pointer bg-purple-600 text-white border-purple-500 font-bold';
    } else {
      btn.className = 'px-2.5 py-1 rounded-full text-xs border transition-all cursor-pointer bg-[#231F2A] hover:bg-[#2D2836] text-slate-300 border-[#3F3A46]';
    }
  });
}

function renderSummaryMarkdown(summary) {
  if (!summary) return 'Chưa có cấu hình tóm tắt.';
  return summary
    .replace(/^# (.+)$/gm, '<h1 class="text-sm font-bold text-white mb-2">$1</h1>')
    .replace(/^## (.+)$/gm, '<h2 class="text-xs font-bold text-purple-300 mt-2 mb-1">$1</h2>')
    .replace(/^\- \*\*([^*]+)\*\*: (.*)$/gm, '<div class="text-xs text-slate-200 py-0.5"><strong class="text-purple-400">$1:</strong> $2</div>')
    .replace(/^\- (.*)$/gm, '<div class="text-xs text-slate-300 py-0.5">• $1</div>')
    .replace(/\n/g, '<br/>');
}

function renderProjectActiveState(data) {
  activeProjectData = data;
  const stepInit = document.getElementById('projectStepInit');
  const stepAwaiting = document.getElementById('projectStepAwaiting');
  const stepConfirm = document.getElementById('projectStepConfirm');
  const stepApproved = document.getElementById('projectStepApproved');

  // Hide all steps initially
  if (stepInit) stepInit.classList.add('hidden');
  if (stepAwaiting) stepAwaiting.classList.add('hidden');
  if (stepConfirm) stepConfirm.classList.add('hidden');
  if (stepApproved) stepApproved.classList.add('hidden');

  if (!data || !data.status) {
    if (stepInit) stepInit.classList.remove('hidden');
    return;
  }

  if (data.status === 'awaiting_answers') {
    if (stepAwaiting) stepAwaiting.classList.remove('hidden');
    const tagsBox = document.getElementById('projectRecognizedTags');
    if (tagsBox && data.recognized_specs) {
      const entries = Object.entries(data.recognized_specs);
      if (entries.length > 0) {
        tagsBox.innerHTML = entries.map(([k, v]) => `
          <span class="px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[11px]">✓ ${k}: ${v}</span>
        `).join('');
      } else {
        tagsBox.innerHTML = '<span class="text-slate-500 text-[11px]">Chưa nhận diện trước thông số nào</span>';
      }
    }
    renderDynamicQuestions(data.questions || [], data.answers || {});
  } else if (data.status === 'awaiting_confirmation') {
    if (stepConfirm) stepConfirm.classList.remove('hidden');
    const summaryCard = document.getElementById('projectSummaryCard');
    if (summaryCard) {
      summaryCard.innerHTML = renderSummaryMarkdown(data.summary_markdown || 'Vui lòng xác nhận cấu hình dự án.');
    }
  } else if (data.status === 'approved' || data.status === 'rendering' || data.status === 'completed' || data.status === 'failed') {
    if (stepApproved) stepApproved.classList.remove('hidden');
    const scriptInput = document.getElementById('projectNarrationScript');
    if (scriptInput && !scriptInput.value) {
      scriptInput.value = data.final_script || (data.outline ? data.outline.join('\n\n') : '');
    }
    
    // Check if there is audio output
    if (data.audio_url) {
      const resCard = document.getElementById('projectRenderResultCard');
      const player = document.getElementById('projectAudioPlayer');
      const dlLink = document.getElementById('projectDownloadWav');
      if (resCard) resCard.classList.remove('hidden');
      if (player) player.src = data.audio_url;
      if (dlLink) {
        dlLink.href = data.audio_url;
        dlLink.download = `chatterbox_project_${data.id}.wav`;
      }
    }
  } else {
    if (stepInit) stepInit.classList.remove('hidden');
  }
}

async function createAudioProject() {
  const btn = document.getElementById('btnStartProject');
  const topic = document.getElementById('projectTopicInput')?.value.trim();
  if (!topic) return showToast('warning', 'Vui lòng nhập chủ đề hoặc yêu cầu kịch bản.');

  const autoDefaults = document.getElementById('chkAutoFillDefaults')?.checked ?? true;

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span><span>Đang phân tích...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch('/api/v1/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic, auto_fill_defaults: autoDefaults })
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectId = data.id;
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      showToast('success', 'Đã khởi tạo dự án âm thanh thành công!');
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Không thể tạo dự án.');
    }
  } catch (e) {
    showToast('error', 'Lỗi kết nối tạo dự án: ' + e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">smart_toy</span><span>Phân tích & Lập kế hoạch (AI Planner)</span>';
      btn.disabled = false;
    }
  }
}

async function submitProjectAnswers() {
  if (!activeProjectId) return showToast('warning', 'Không có dự án nào đang chọn.');
  const btn = document.getElementById('btnSubmitAnswers');

  const answers = {};
  const inputs = document.querySelectorAll('#projectQuestionsList input[data-qid]');
  inputs.forEach(input => {
    const qid = input.getAttribute('data-qid');
    const val = input.value.trim();
    if (val) answers[qid] = val;
  });

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang xử lý...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/answers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers: answers })
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      showToast('success', 'Đã lưu câu trả lời! Mời bạn duyệt cấu hình.');
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi gửi câu trả lời.');
    }
  } catch (e) {
    showToast('error', 'Lỗi mạng: ' + e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '<span>Lưu & Tiếp tục duyệt cấu hình</span><span class="material-symbols-outlined text-[16px]">arrow_forward</span>';
      btn.disabled = false;
    }
  }
}

async function confirmProject(approve = true) {
  if (!activeProjectId) return showToast('warning', 'Không có dự án nào đang chọn.');
  const btn = document.getElementById('btnApproveProject');

  if (btn && approve) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang duyệt...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: approve })
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      if (approve) {
        showToast('success', 'Dự án đã được duyệt! Bạn có thể bắt đầu tạo audio.');
      } else {
        showToast('info', 'Đã hủy duyệt dự án.');
      }
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi xác nhận dự án.');
    }
  } catch (e) {
    showToast('error', 'Lỗi xác nhận: ' + e.message);
  } finally {
    if (btn && approve) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">check_circle</span><span>Duyệt & Chuyển sang Triển khai</span>';
      btn.disabled = false;
    }
  }
}

function generateStarterScript() {
  const p = activeProjectData;
  if (!p) return;
  const topic = p.topic || 'Chủ đề dự án';
  const format = p.recognized_specs?.content_format || p.answers?.content_format || 'Podcast';
  const tone = p.recognized_specs?.voice_style || p.answers?.voice_style || 'Truyền cảm';

  const starter = `[Narrator]: Chào mừng các bạn đến với chương trình âm thanh hôm nay về "${topic}".\n\n` +
    `[Speaker 1]: Trong phần này, chúng ta sẽ tìm hiểu về các khía cạnh thú vị và cốt lõi nhất.\n\n` +
    `[Speaker 2]: Cảm ơn các bạn đã lắng nghe. Hẹn gặp lại trong các tập tiếp theo!`;

  const scriptInput = document.getElementById('projectNarrationScript');
  if (scriptInput) {
    scriptInput.value = starter;
    showToast('info', 'Đã tạo khung kịch bản khởi đầu!');
  }
}

async function renderProjectAudio() {
  if (!activeProjectId) return showToast('warning', 'Chưa có dự án nào.');
  const btn = document.getElementById('btnRenderProjectAudio');
  const script = document.getElementById('projectNarrationScript')?.value.trim();
  if (!script) return showToast('warning', 'Vui lòng nhập nội dung kịch bản cần đọc.');

  const charVal = document.getElementById('projectCharacterSelect')?.value || '';
  const presetVal = document.getElementById('projectPresetSelect')?.value || 'balanced';

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang khởi tạo render...</span>';
    btn.disabled = true;
  }

  const payload = {
    script: script,
    character_id: charVal.startsWith('char:') ? charVal.replace('char:', '') : null,
    preset: presetVal
  };

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const data = await res.json();
      showToast('info', 'Đã gửi lệnh tổng hợp âm thanh dự án!');
      if (data.job_id) {
        pollProjectJob(data.job_id);
      }
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi khởi chạy render.');
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">record_voice_over</span><span>Tổng hợp Âm thanh Dự án</span>';
        btn.disabled = false;
      }
    }
  } catch (e) {
    showToast('error', 'Lỗi kết nối render: ' + e.message);
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">record_voice_over</span><span>Tổng hợp Âm thanh Dự án</span>';
      btn.disabled = false;
    }
  }
}

function pollProjectJob(jobId) {
  const progressBox = document.getElementById('projectRenderProgress');
  const progressFill = document.getElementById('projectRenderFill');
  const progressPercent = document.getElementById('projectRenderPercent');
  const progressStage = document.getElementById('projectRenderStage');
  const btn = document.getElementById('btnRenderProjectAudio');

  if (progressBox) progressBox.classList.remove('hidden');

  if (projectJobPollInterval) clearInterval(projectJobPollInterval);

  projectJobPollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}`);
      if (res.ok) {
        const jdata = await res.json();
        const pct = jdata.progress_percent || 0;
        if (progressFill) progressFill.style.width = `${pct}%`;
        if (progressPercent) progressPercent.textContent = `${pct}%`;
        if (progressStage) {
          progressStage.textContent = jdata.phase ? `Giai đoạn: ${jdata.phase}...` : 'Đang xử lý...';
        }

        if (jdata.status === 'completed' || jdata.status === 'failed' || jdata.status === 'cancelled') {
          clearInterval(projectJobPollInterval);
          if (btn) {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">record_voice_over</span><span>Tổng hợp Âm thanh Dự án</span>';
            btn.disabled = false;
          }

          if (jdata.status === 'completed') {
            const card = document.getElementById('projectRenderResultCard');
            const player = document.getElementById('projectAudioPlayer');
            const dlLink = document.getElementById('projectDownloadWav');

            if (card) card.classList.remove('hidden');
            if (player && jdata.audio_url) player.src = jdata.audio_url;
            if (dlLink && jdata.audio_url) {
              dlLink.href = jdata.audio_url;
              dlLink.download = `chatterbox_project_${activeProjectId}.wav`;
            }
            showToast('success', 'Hoàn tất render âm thanh dự án thành công!');
          } else {
            showToast('error', `Render thất bại: ${jdata.error || 'Lỗi không xác định'}`);
          }
          loadProjects();
        }
      }
    } catch (e) {
      clearInterval(projectJobPollInterval);
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">record_voice_over</span><span>Tổng hợp Âm thanh Dự án</span>';
        btn.disabled = false;
      }
    }
  }, 500);
}

async function loadProjects() {
  const container = document.getElementById('projectsListContainer');
  const countBadge = document.getElementById('projectsCountBadge');

  // Populate Character dropdown in Projects
  const charSelect = document.getElementById('projectCharacterSelect');
  if (charSelect && allCharactersCache && allCharactersCache.length > 0) {
    charSelect.innerHTML = '<option value="">-- Mặc định AI --</option>' +
      allCharactersCache.map(c => `<option value="char:${c.id}">${c.is_default ? '⭐ ' : ''}${c.name} (${c.language || 'vi'})</option>`).join('');
  }

  try {
    const res = await fetch('/api/v1/projects');
    if (res.ok) {
      const data = await res.json();
      allProjectsList = data.projects || [];
      if (countBadge) countBadge.textContent = `${allProjectsList.length} dự án`;
      renderProjectsList();
    }
  } catch (e) {
    if (container) container.innerHTML = '<div class="text-xs text-slate-500 py-6 text-center">Không tải được danh sách dự án.</div>';
  }
}

function filterProjectsList(status) {
  currentProjectFilter = status;
  document.querySelectorAll('.project-filter-btn').forEach(btn => {
    btn.className = 'project-filter-btn px-2 py-0.5 rounded-full text-slate-300 hover:text-white bg-[#14101A] border border-[#3F3A46] text-[11px] transition-all cursor-pointer';
  });
  const activeBtn = document.getElementById(`filterProject_${status}`);
  if (activeBtn) {
    activeBtn.className = 'project-filter-btn active px-2 py-0.5 rounded-full text-white bg-purple-600 border border-purple-500 font-bold text-[11px] transition-all cursor-pointer';
  }
  renderProjectsList();
}

function renderProjectsList() {
  const container = document.getElementById('projectsListContainer');
  if (!container) return;

  let list = allProjectsList;
  if (currentProjectFilter !== 'all') {
    list = list.filter(p => p.status === currentProjectFilter);
  }

  if (list.length === 0) {
    container.innerHTML = '<div class="text-xs text-slate-500 py-8 text-center">Không có dự án nào phù hợp.</div>';
    return;
  }

  container.innerHTML = list.map(p => {
    let statusChip = '';
    if (p.status === 'awaiting_answers') {
      statusChip = '<span class="px-2 py-0.5 rounded-full bg-amber-950/60 text-amber-300 border border-amber-800 text-[10px]">Cần trả lời</span>';
    } else if (p.status === 'awaiting_confirmation') {
      statusChip = '<span class="px-2 py-0.5 rounded-full bg-blue-950/60 text-blue-300 border border-blue-800 text-[10px]">Chờ xác nhận</span>';
    } else if (p.status === 'approved') {
      statusChip = '<span class="px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px] font-bold">Đã duyệt</span>';
    } else if (p.status === 'rendering') {
      statusChip = '<span class="px-2 py-0.5 rounded-full bg-purple-950/60 text-purple-300 border border-purple-800 text-[10px] animate-pulse">Đang render</span>';
    } else if (p.status === 'completed') {
      statusChip = '<span class="px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px] font-bold">✓ Hoàn tất</span>';
    } else {
      statusChip = `<span class="px-2 py-0.5 rounded-full bg-[#231F2A] text-slate-400 text-[10px]">${p.status}</span>`;
    }

    const isSelected = p.id === activeProjectId;
    const borderClass = isSelected ? 'border-purple-500 bg-[#18151E]' : 'border-[#3F3A46]/60 bg-[#0E0C12] hover:bg-[#14101A]';

    return `
      <div class="p-3 rounded-xl border ${borderClass} transition-colors space-y-2 cursor-pointer" onclick="openProjectDetail('${p.id}')">
        <div class="flex items-start justify-between gap-2">
          <div class="font-bold text-xs text-white line-clamp-2">${p.topic || 'Dự án không tên'}</div>
          ${statusChip}
        </div>
        <div class="flex items-center justify-between text-[10px] text-slate-400 font-mono pt-1 border-t border-[#3F3A46]/30">
          <span>${p.created_at ? p.created_at.substring(0, 10) : ''}</span>
          <button type="button" onclick="event.stopPropagation(); openProjectDetail('${p.id}')" class="px-2 py-0.5 rounded bg-purple-600/30 hover:bg-purple-600 text-purple-300 hover:text-white transition-colors cursor-pointer">Mở dự án</button>
        </div>
      </div>
    `;
  }).join('');
}

async function openProjectDetail(projectId) {
  activeProjectId = projectId;
  try {
    const res = await fetch(`/api/v1/projects/${projectId}`);
    if (res.ok) {
      const data = await res.json();
      const topicInput = document.getElementById('projectTopicInput');
      if (topicInput) topicInput.value = data.topic || '';
      renderProjectActiveState(data);
      renderProjectsList();
      showToast('info', `Đã mở dự án ${activeProjectId}`);
    }
  } catch (err) {
    showToast('error', 'Không thể tải chi tiết dự án.');
  }
}
