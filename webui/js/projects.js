/**
 * Chatterbox TTS Studio - Audio Projects Planner & Two-Gate Confirmation Module (English Workflow)
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

function resetProjectPlannerForm() {
  activeProjectId = null;
  activeProjectData = null;
  const topicInput = document.getElementById('projectTopicInput');
  if (topicInput) topicInput.value = '';

  const idBadge = document.getElementById('projectActiveIdBadge');
  if (idBadge) idBadge.textContent = 'Mới';

  renderProjectStepVisibility('step1');
  showToast('info', 'Đã khởi tạo form dự án mới.');
}

function renderProjectStepVisibility(step) {
  const s1 = document.getElementById('projectStep1Card');
  const s2 = document.getElementById('projectStep2Card');
  const s3 = document.getElementById('projectStep3Card');
  const s4 = document.getElementById('projectStep4Card');

  if (s1) s1.classList.remove('hidden'); // Always keep Step 1 accessible
  if (s2) s2.classList.add('hidden');
  if (s3) s3.classList.add('hidden');
  if (s4) s4.classList.add('hidden');

  if (step === 'step2' && s2) s2.classList.remove('hidden');
  if (step === 'step3' && s3) s3.classList.remove('hidden');
  if (step === 'step4' && s4) s4.classList.remove('hidden');
}

function renderSummaryMarkdown(summary) {
  if (!summary) return 'Chưa có cấu hình tóm tắt.';
  return summary
    .replace(/^### (.+)$/gm, '<h3 class="text-xs font-bold text-white mb-2">$1</h3>')
    .replace(/^#### (.+)$/gm, '<h4 class="text-[11px] font-bold text-purple-300 mt-2 mb-1">$1</h4>')
    .replace(/^\* \*\*([^*]+)\*\*: (.*)$/gm, '<div class="text-xs text-slate-200 py-0.5"><strong class="text-purple-400">$1:</strong> $2</div>')
    .replace(/^- \*\*([^*]+)\*\* (.*)$/gm, '<div class="text-xs text-slate-300 py-0.5">• <strong class="text-emerald-400">$1</strong> $2</div>')
    .replace(/^\* (.*)$/gm, '<div class="text-xs text-slate-300 py-0.5">• $1</div>')
    .replace(/```text\n([\s\S]*?)\n```/gm, '<div class="p-2.5 my-1.5 rounded-lg bg-[#14101A] border border-[#3F3A46]/60 font-mono text-[11px] text-slate-300 whitespace-pre-wrap">$1</div>')
    .replace(/\n/g, '<br/>');
}

function renderDynamicQuestions(questions) {
  const container = document.getElementById('projectQuestionsContainer');
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
      optionsHtml = `
        <div class="flex flex-wrap gap-1.5 pt-1">
          ${q.options.map(opt => {
            return `<button type="button" onclick="selectProjectQuestionOption('${q.id}', '${opt.replace(/'/g, "\\'")}')" class="project-opt-btn-${q.id} px-2.5 py-1 rounded-md text-[11px] border border-[#3F3A46] bg-[#18151E] hover:bg-purple-900/30 text-slate-300 transition-all cursor-pointer">${opt}</button>`;
          }).join('')}
        </div>
      `;
    }

    qCard.innerHTML = `
      <div class="flex items-start justify-between gap-2">
        <label class="text-xs font-semibold text-white flex items-center gap-1.5">
          <span class="w-4 h-4 rounded-full bg-amber-600 text-white font-mono text-[10px] flex items-center justify-center">${idx + 1}</span>
          <span>${q.question || q.id}</span>
          ${q.required ? '<span class="text-red-400 font-bold">*</span>' : '<span class="text-slate-500 text-[10px]">(Khuyến nghị)</span>'}
        </label>
      </div>
      ${optionsHtml}
      <div>
        <input type="text" id="q_input_${q.id}" data-qid="${q.id}" placeholder="Hoặc nhập câu trả lời tùy chỉnh..." class="w-full bg-[#18151E] border border-[#3F3A46] focus:border-amber-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none">
      </div>
    `;

    container.appendChild(qCard);
  });
}

function selectProjectQuestionOption(qid, val) {
  const input = document.getElementById(`q_input_${qid}`);
  if (input) input.value = val;

  document.querySelectorAll(`.project-opt-btn-${qid}`).forEach(btn => {
    if (btn.textContent.trim() === val) {
      btn.className = `project-opt-btn-${qid} px-2.5 py-1 rounded-md text-[11px] border border-amber-500 bg-amber-600 text-white font-bold transition-all cursor-pointer`;
    } else {
      btn.className = `project-opt-btn-${qid} px-2.5 py-1 rounded-md text-[11px] border border-[#3F3A46] bg-[#18151E] hover:bg-amber-900/30 text-slate-300 transition-all cursor-pointer`;
    }
  });
}

function renderProjectActiveState(data) {
  activeProjectData = data;
  if (!data) return;

  activeProjectId = data.id || data.project_id;
  const idBadge = document.getElementById('projectActiveIdBadge');
  if (idBadge) idBadge.textContent = activeProjectId || 'Mới';

  const status = data.status;

  if (status === 'awaiting_answers') {
    renderProjectStepVisibility('step2');
    const tagsBox = document.getElementById('projectRecognizedTags');
    if (tagsBox && data.requirements) {
      const entries = Object.entries(data.requirements).filter(([_, v]) => Boolean(v));
      if (entries.length > 0) {
        tagsBox.innerHTML = entries.map(([k, v]) => `
          <span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px]">✓ ${k}: ${Array.isArray(v) ? v.join(', ') : v}</span>
        `).join('');
      } else {
        tagsBox.innerHTML = '<span class="text-slate-500 text-[11px]">Chưa nhận diện được thông số</span>';
      }
    }
    renderDynamicQuestions(data.questions || []);
  } else if (status === 'awaiting_requirements_confirmation' || status === 'awaiting_confirmation') {
    renderProjectStepVisibility('step3');
    const summaryBox = document.getElementById('projectSummaryBox');
    if (summaryBox) {
      summaryBox.innerHTML = renderSummaryMarkdown(data.summary || formatSummaryFromData(data));
    }
  } else if (status === 'awaiting_script_confirmation') {
    renderProjectStepVisibility('step3');
    const summaryBox = document.getElementById('projectSummaryBox');
    if (summaryBox) {
      summaryBox.innerHTML = renderSummaryMarkdown(data.summary || formatSummaryFromData(data));
    }
  } else if (status === 'approved' || status === 'segmenting' || status === 'rendering_draft' || status === 'rendering' || status === 'completed') {
    renderProjectStepVisibility('step4');
    const scriptInput = document.getElementById('projectScriptInput');
    if (scriptInput) {
      if (data.script && typeof data.script === 'object' && data.script.full_text) {
        scriptInput.value = data.script.full_text;
      } else if (typeof data.script === 'string') {
        scriptInput.value = data.script;
      } else if (data.script_text) {
        scriptInput.value = data.script_text;
      }
    }

    if (data.final_job_id || data.job_id) {
      const jid = data.final_job_id || data.job_id;
      pollProjectJob(jid);
    }
  } else {
    renderProjectStepVisibility('step1');
  }
}

function formatSummaryFromData(p) {
  const req = p.requirements || {};
  return `### 📋 Tóm tắt cấu hình dự án: **${p.topic || 'Dự án'}**\n` +
    `* **Định dạng**: ${req.content_format || 'Podcast'}\n` +
    `* **Thời lượng**: ~${(req.target_duration_seconds || 300) / 60} phút (${req.target_duration_seconds || 300}s)\n` +
    `* **Đối tượng**: ${req.audience || 'General'}\n` +
    `* **Ngôn ngữ**: English (\`en\`)\n` +
    `* **Phong cách**: ${req.tone || 'Engaging storytelling'}\n` +
    `* **Hậu kỳ SFX**: ${req.sfx_level || 'Light'}\n` +
    `* **Đầu ra**: ${(req.output_formats || ['WAV', 'SRT']).join(', ').toUpperCase()}`;
}

async function prepareProjectAction() {
  const btn = document.getElementById('projectPrepareBtn');
  const topic = document.getElementById('projectTopicInput')?.value.trim();
  if (!topic) return showToast('warning', 'Vui lòng nhập chủ đề dự án âm thanh.');

  const autoDefaults = document.getElementById('projectAutoDefaultsCheck')?.checked ?? true;

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang phân tích...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch('/api/v1/projects/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic: topic,
        auto_defaults: autoDefaults,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectId = data.project_id;
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      showToast('success', 'Đã phân tích ý tưởng dự án thành công!');
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Không thể khởi tạo dự án.');
    }
  } catch (e) {
    showToast('error', 'Lỗi kết nối: ' + e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">psychology</span><span>Phân tích & Khởi tạo</span>';
      btn.disabled = false;
    }
  }
}

async function submitProjectAnswersAction() {
  if (!activeProjectId) return showToast('warning', 'Chưa có dự án nào được chọn.');
  const btn = document.getElementById('projectSubmitAnswersBtn');

  const answers = {};
  const inputs = document.querySelectorAll('#projectQuestionsContainer input[data-qid]');
  inputs.forEach(input => {
    const qid = input.getAttribute('data-qid');
    const val = input.value.trim();
    if (val) answers[qid] = val;
  });

  const freeform = document.getElementById('projectFreeformAnswersInput')?.value.trim();
  const autoDefaults = document.getElementById('projectAnswersAutoDefaultsCheck')?.checked ?? true;

  let finalAnswers = answers;
  if (freeform) {
    finalAnswers = freeform;
  }

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang cập nhật...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        answers: finalAnswers,
        auto_defaults: autoDefaults,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      showToast('success', 'Đã cập nhật yêu cầu! Mời bạn duyệt cấu hình.');
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi gửi câu trả lời.');
    }
  } catch (e) {
    showToast('error', 'Lỗi mạng: ' + e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">send</span><span>Gửi câu trả lời & Tóm tắt</span>';
      btn.disabled = false;
    }
  }
}

async function confirmProjectAction(approve = true) {
  if (!activeProjectId) return showToast('warning', 'Chưa có dự án nào.');

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: approve }),
    });

    if (res.ok) {
      const data = await res.json();
      activeProjectData = data;
      renderProjectActiveState(data);
      loadProjects();
      if (approve) {
        showToast('success', data.message || 'Đã phê duyệt thành công!');
      } else {
        showToast('info', 'Đã hủy dự án.');
      }
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi xác nhận dự án.');
    }
  } catch (e) {
    showToast('error', 'Lỗi xác nhận: ' + e.message);
  }
}

function generateProjectSampleScript() {
  const p = activeProjectData;
  if (!p) return;
  const topic = p.topic || 'Audio Project';

  const sample = `[Scene 1: Introduction]\n[Narrator]: Welcome to our exploration of ${topic}. In this episode, we unpack the fundamental ideas and remarkable insights.\n\n` +
    `[Scene 2: Core Discussion]\n[Narrator]: When looking closer at ${topic}, practical innovations and deeper perspectives begin to emerge clearly.\n\n` +
    `[Scene 3: Conclusion]\n[Narrator]: Thank you for tuning in today. Keep exploring, and stay curious!`;

  const scriptInput = document.getElementById('projectScriptInput');
  if (scriptInput) {
    scriptInput.value = sample;
    showToast('info', 'Đã tạo kịch bản tiếng Anh mẫu!');
  }
}

async function renderProjectAction() {
  if (!activeProjectId) return showToast('warning', 'Chưa có dự án nào.');
  const btn = document.getElementById('projectRenderBtn');
  const scriptText = document.getElementById('projectScriptInput')?.value.trim();

  const charSelect = document.getElementById('projectCharacterSelect')?.value || null;
  const presetSelect = document.getElementById('projectPresetSelect')?.value || 'balanced';

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang khởi tạo render...</span>';
    btn.disabled = true;
  }

  try {
    const res = await fetch(`/api/v1/projects/${activeProjectId}/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script_text: scriptText || null,
        character_id: charSelect || null,
        quality_preset: presetSelect,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      showToast('success', data.message || 'Đã bắt đầu sản xuất audio!');
      const jid = data.job_id || data.final_job_id;
      if (jid) {
        pollProjectJob(jid);
      }
    } else {
      const err = await res.json();
      showToast('error', err.detail || 'Lỗi khi bắt đầu render.');
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_circle</span><span>Bắt đầu Render Audio</span>';
        btn.disabled = false;
      }
    }
  } catch (e) {
    showToast('error', 'Lỗi kết nối render: ' + e.message);
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_circle</span><span>Bắt đầu Render Audio</span>';
      btn.disabled = false;
    }
  }
}

function pollProjectJob(jobId) {
  const resultBox = document.getElementById('projectJobResultBox');
  const statusTitle = document.getElementById('projectJobStatusTitle');
  const idText = document.getElementById('projectJobIdText');
  const progressBar = document.getElementById('projectJobProgressBar');
  const audioContainer = document.getElementById('projectAudioPlayerContainer');
  const audioEl = document.getElementById('projectAudioEl');
  const dlBtn = document.getElementById('projectDownloadWavBtn');
  const btn = document.getElementById('projectRenderBtn');

  if (resultBox) resultBox.classList.remove('hidden');
  if (idText) idText.textContent = `Job: ${jobId}`;

  if (projectJobPollInterval) clearInterval(projectJobPollInterval);

  projectJobPollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}`);
      if (res.ok) {
        const jdata = await res.json();
        const pct = jdata.progress_percent || 0;
        if (progressBar) progressBar.style.width = `${pct}%`;
        if (statusTitle) {
          statusTitle.textContent = jdata.phase ? `Giai đoạn: ${jdata.phase} (${pct}%)` : `Đang xử lý (${pct}%)...`;
        }

        if (jdata.status === 'completed' || jdata.status === 'failed' || jdata.status === 'cancelled') {
          clearInterval(projectJobPollInterval);
          if (btn) {
            btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_circle</span><span>Bắt đầu Render Audio</span>';
            btn.disabled = false;
          }

          if (jdata.status === 'completed') {
            if (statusTitle) statusTitle.textContent = '✅ Hoàn tất render âm thanh!';
            if (audioContainer) audioContainer.classList.remove('hidden');
            if (audioEl && jdata.audio_url) audioEl.src = jdata.audio_url;
            if (dlBtn && jdata.audio_url) {
              dlBtn.href = jdata.audio_url;
              dlBtn.download = `chatterbox_project_${activeProjectId || 'master'}.wav`;
            }
            showToast('success', 'Đã render hoàn tất sản phẩm âm thanh!');
          } else {
            if (statusTitle) statusTitle.textContent = `❌ Thất bại: ${jdata.error || 'Lỗi'}`;
            showToast('error', `Render thất bại: ${jdata.error || 'Lỗi không xác định'}`);
          }
          loadProjects();
        }
      }
    } catch (e) {
      clearInterval(projectJobPollInterval);
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">play_circle</span><span>Bắt đầu Render Audio</span>';
        btn.disabled = false;
      }
    }
  }, 500);
}

async function loadProjects() {
  const container = document.getElementById('projectsListContainer');
  const countBadge = document.getElementById('projectsCountBadge');

  // Populate Character dropdown
  const charSelect = document.getElementById('projectCharacterSelect');
  if (charSelect && typeof allCharactersCache !== 'undefined' && allCharactersCache.length > 0) {
    charSelect.innerHTML = '<option value="">Tự động tối ưu theo chủ đề</option>' +
      allCharactersCache.map(c => `<option value="${c.id}">${c.is_default ? '⭐ ' : ''}${c.name} (${c.language || 'en'})</option>`).join('');
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
      statusChip = '<span class="px-2 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800 text-[10px]">Cần trả lời</span>';
    } else if (p.status === 'awaiting_requirements_confirmation' || p.status === 'awaiting_confirmation') {
      statusChip = '<span class="px-2 py-0.5 rounded bg-blue-950/60 text-blue-300 border border-blue-800 text-[10px]">Gate 1: Duyệt yêu cầu</span>';
    } else if (p.status === 'awaiting_script_confirmation') {
      statusChip = '<span class="px-2 py-0.5 rounded bg-indigo-950/60 text-indigo-300 border border-indigo-800 text-[10px]">Gate 2: Duyệt kịch bản</span>';
    } else if (p.status === 'approved') {
      statusChip = '<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px] font-bold">✅ Đã duyệt</span>';
    } else if (p.status === 'rendering' || p.status === 'rendering_draft') {
      statusChip = '<span class="px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800 text-[10px] animate-pulse">🎙️ Đang render</span>';
    } else if (p.status === 'completed') {
      statusChip = '<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px] font-bold">✓ Hoàn tất</span>';
    } else {
      statusChip = `<span class="px-2 py-0.5 rounded bg-[#231F2A] text-slate-400 text-[10px]">${p.status}</span>`;
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
