/**
 * Chatterbox TTS Studio - TTS Studio, Audio Player & Waveform Visualizer
 */

function handleModelChange(val) {
  userManuallyChangedModel = true;
  const hint = document.getElementById('modelDescHint');
  if (!hint) return;
  if (val === 'turbo') {
    hint.textContent = 'Chatterbox Turbo (350M - Tốc độ cao, hỗ trợ Tags cảm xúc)';
  } else if (val === 'standard') {
    hint.textContent = 'Chatterbox Standard (500M - Chất lượng âm thanh chuẩn cao nhất)';
  } else {
    hint.textContent = 'Chatterbox Nano (110M - Siêu nhẹ, an toàn tuyệt đối cho RAM ≤ 16GB)';
  }
}

function applyPreset(val) {
  if (val === 'news') {
    setSlider('sliderExaggeration', 'valExaggeration', 0.3);
    setSlider('sliderPace', 'valPace', 0.7);
    setSlider('sliderTemp', 'valTemp', 0.6);
  } else if (val === 'story') {
    setSlider('sliderExaggeration', 'valExaggeration', 0.8);
    setSlider('sliderPace', 'valPace', 0.5);
    setSlider('sliderTemp', 'valTemp', 0.8);
  } else if (val === 'expressive') {
    setSlider('sliderExaggeration', 'valExaggeration', 1.2);
    setSlider('sliderPace', 'valPace', 0.5);
    setSlider('sliderTemp', 'valTemp', 1.0);
  } else if (val === 'whisper') {
    setSlider('sliderExaggeration', 'valExaggeration', 0.2);
    setSlider('sliderPace', 'valPace', 0.8);
    setSlider('sliderTemp', 'valTemp', 0.7);
  } else {
    resetSliders();
  }
  showToast('info', `Đã áp dụng cấu hình: ${val}`);
}

function updateParamsSummaryBadge() {
  const badge = document.getElementById('paramsSummaryBadge');
  if (!badge) return;
  const exag = parseFloat(document.getElementById('sliderExaggeration')?.value || 0.5).toFixed(2);
  const pace = parseFloat(document.getElementById('sliderPace')?.value || 0.5).toFixed(2);
  const temp = parseFloat(document.getElementById('sliderTemp')?.value || 0.8).toFixed(2);
  badge.textContent = `Exag ${exag} · Pace ${pace} · Temp ${temp}`;
}

function toggleExtraTags() {
  const extra = document.getElementById('extraTagsContainer');
  const btn = document.getElementById('btnToggleExtraTags');
  if (!extra || !btn) return;
  const isHidden = extra.classList.contains('hidden');
  if (isHidden) {
    extra.classList.remove('hidden');
    btn.textContent = '- Ẩn';
  } else {
    extra.classList.add('hidden');
    btn.textContent = '+ Thêm';
  }
}

function previewCurrentVoice() {
  if (uploadedRefFile) {
    const url = URL.createObjectURL(uploadedRefFile);
    const a = new Audio(url);
    a.play();
    showToast('info', 'Đang phát file giọng đọc mẫu đã tải...');
    return;
  }
  const ttsSelect = document.getElementById('ttsCharacterSelect');
  const val = ttsSelect ? ttsSelect.value : '';
  if (val.startsWith('char:')) {
    const charId = val.replace('char:', '');
    const char = allCharactersCache.find(c => c.id === charId);
    if (char && char.has_reference_audio) {
      const a = new Audio(`/api/v1/characters/${char.id}/reference-audio`);
      a.play();
      showToast('info', `Đang phát giọng mẫu của "${char.name}"...`);
      return;
    }
  }
  showToast('info', 'Giọng mẫu sẵn có — Nhấn "SINH GIỌNG NÓI" để bắt đầu trải nghiệm!');
}

function resetSliders() {
  setSlider('sliderExaggeration', 'valExaggeration', 0.5);
  setSlider('sliderPace', 'valPace', 0.5);
  setSlider('sliderTemp', 'valTemp', 0.8);
  setSlider('sliderMinP', 'valMinP', 0.05);
  const spd = document.getElementById('sliderSpeed');
  if (spd) spd.value = 1.0;
  const valSpd = document.getElementById('valSpeed');
  if (valSpd) valSpd.textContent = '1.0x';
  updateParamsSummaryBadge();
}

function handleSpeedChange(val) {
  const el = document.getElementById('valSpeed');
  if (el) el.textContent = parseFloat(val).toFixed(1) + 'x';
  audioElement.playbackRate = parseFloat(val);
}

function randomizeSeed() {
  const s = Math.floor(Math.random() * 999999);
  const input = document.getElementById('seedInput');
  if (input) input.value = s;
  showToast('info', `Đã tạo Random Seed: ${s}`);
}

// Drag & Drop on textareas
function setupDragAndDropTextarea(textareaId, counterId = null) {
  const textarea = document.getElementById(textareaId);
  if (!textarea) return;

  ['dragenter', 'dragover'].forEach(eventName => {
    textarea.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      textarea.classList.add('drag-over');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    textarea.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      textarea.classList.remove('drag-over');
    });
  });

  textarea.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files && files.length > 0) {
      const file = files[0];
      const reader = new FileReader();
      reader.onload = (event) => {
        textarea.value = event.target.result;
        if (counterId) {
          const counter = document.getElementById(counterId);
          if (counter) counter.textContent = `${textarea.value.length} / 4000 ký tự`;
        }
        showToast('success', `Đã nạp văn bản từ file "${file.name}"!`);
        if (textareaId === 'batchTextarea' && typeof parseBatchLines === 'function') parseBatchLines();
      };
      reader.onerror = () => {
        showToast('error', `Không thể đọc nội dung file "${file.name}"`);
      };
      reader.readAsText(file);
    }
  });
}

function insertTag(tag) {
  const promptInput = document.getElementById('promptInput');
  const charCount = document.getElementById('charCount');
  if (!promptInput) return;
  const start = promptInput.selectionStart;
  const end = promptInput.selectionEnd;
  const text = promptInput.value;
  if (start !== end) {
    const selected = text.substring(start, end);
    promptInput.value = text.substring(0, start) + `${selected} ${tag}` + text.substring(end);
    promptInput.selectionStart = promptInput.selectionEnd = start + selected.length + tag.length + 1;
  } else {
    promptInput.value = text.substring(0, start) + ' ' + tag + ' ' + text.substring(end);
    promptInput.selectionStart = promptInput.selectionEnd = start + tag.length + 2;
  }
  promptInput.focus();
  if (charCount) charCount.textContent = `${promptInput.value.length} / 4000 ký tự`;
  showToast('info', `Đã chèn thẻ cảm xúc: ${tag}`);
}

function cleanPromptText() {
  const promptInput = document.getElementById('promptInput');
  const charCount = document.getElementById('charCount');
  if (!promptInput) return;
  promptInput.value = promptInput.value.replace(/\s+/g, ' ').trim();
  if (charCount) charCount.textContent = `${promptInput.value.length} / 4000 ký tự`;
  showToast('info', 'Đã làm sạch khoảng trắng trong văn bản.');
}

function clearPromptText() {
  const promptInput = document.getElementById('promptInput');
  const charCount = document.getElementById('charCount');
  if (!promptInput) return;
  promptInput.value = '';
  if (charCount) charCount.textContent = '0 / 4000 ký tự';
}

function handleImportTextFile(input) {
  const promptInput = document.getElementById('promptInput');
  const charCount = document.getElementById('charCount');
  if (input.files && input.files[0] && promptInput) {
    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
      promptInput.value = e.target.result;
      if (charCount) charCount.textContent = `${promptInput.value.length} / 4000 ký tự`;
      showToast('success', `Đã nhập file "${file.name}"`);
    };
    reader.readAsText(file);
  }
}

function sendToBatchStudio() {
  const promptInput = document.getElementById('promptInput');
  const text = promptInput ? promptInput.value.trim() : '';
  if (!text) return showToast('warning', 'Vui lòng nhập văn bản trước khi chuyển sang Batch.');
  const batchTxt = document.getElementById('batchTextarea');
  if (batchTxt) batchTxt.value = text;
  switchTab('batch');
  if (typeof parseBatchLines === 'function') parseBatchLines();
  showToast('success', 'Đã chuyển văn bản sang Batch Studio!');
}

function handleAudioUpload(input) {
  if (input.files && input.files[0]) {
    uploadedRefFile = input.files[0];
    document.getElementById('refAudioName').textContent = uploadedRefFile.name;
    document.getElementById('dropZone').classList.add('hidden');
    document.getElementById('refAudioCard').classList.remove('hidden');
    showToast('success', `Đã chọn file mẫu "${uploadedRefFile.name}"`);
  }
}

function removeRefAudio() {
  uploadedRefFile = null;
  const input = document.getElementById('refAudioInput');
  if (input) input.value = '';
  document.getElementById('dropZone')?.classList.remove('hidden');
  document.getElementById('refAudioCard')?.classList.add('hidden');
  showToast('info', 'Đã hủy chọn file mẫu.');
}

async function toggleMicRecording() {
  const btn = document.getElementById('micRecordBtn');
  const icon = document.getElementById('micIcon');
  const label = document.getElementById('micLabel');

  if (!isRecordingMic) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        uploadedRefFile = new File([audioBlob], "recorded_voice.wav", { type: "audio/wav" });
        document.getElementById('refAudioName').textContent = "recorded_voice.wav (Từ Microphone)";
        document.getElementById('dropZone').classList.add('hidden');
        document.getElementById('refAudioCard').classList.remove('hidden');
        showToast('success', 'Đã lưu bản ghi âm làm giọng mẫu!');
      };

      mediaRecorder.start();
      isRecordingMic = true;
      if (btn) btn.className = 'px-3 py-1 rounded-full bg-red-600 text-xs text-white border border-red-500 flex items-center gap-1 cursor-pointer animate-pulse';
      if (icon) icon.textContent = 'stop';
      if (label) label.textContent = 'Dừng ghi';
      showToast('info', 'Đang ghi âm từ Microphone...');
    } catch (e) {
      showToast('error', 'Không thể truy cập Microphone: ' + e.message);
    }
  } else {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    isRecordingMic = false;
    if (btn) btn.className = 'px-3 py-1 rounded-full bg-[#231F2A] hover:bg-red-600 text-xs text-white border border-[#3F3A46] flex items-center gap-1 cursor-pointer transition-colors';
    if (icon) icon.textContent = 'mic';
    if (label) label.textContent = 'Ghi âm Mic';
  }
}

function openTrimmerModal() { document.getElementById('trimmerModal')?.classList.remove('hidden'); }
function closeTrimmerModal() { document.getElementById('trimmerModal')?.classList.add('hidden'); }
function applyAudioTrim() {
  const s = document.getElementById('trimStart')?.value;
  const e = document.getElementById('trimEnd')?.value;
  showToast('success', `Đã thiết lập đoạn cắt từ ${s}s đến ${e}s.`);
  closeTrimmerModal();
}

function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return '00:00';
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function drawWaveform(progressPct = 0) {
  const canvas = document.getElementById('waveformCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.offsetWidth;
  const h = canvas.height = canvas.offsetHeight;
  ctx.clearRect(0, 0, w, h);

  const numBars = 55;
  const barWidth = Math.max(2, (w - numBars * 3) / numBars);

  for (let i = 0; i < numBars; i++) {
    const x = i * (barWidth + 3);
    const norm = Math.sin((i / numBars) * Math.PI * 4) * 0.4 + 0.5;
    const barHeight = Math.max(6, norm * (h - 20));
    const y = (h - barHeight) / 2;

    const isPast = (x / w) <= progressPct;
    ctx.fillStyle = isPast ? '#A855F7' : '#3F3A46';
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barHeight, 3);
    ctx.fill();
  }

  if (progressPct > 0) {
    ctx.strokeStyle = '#D0BCFF';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(progressPct * w, 0);
    ctx.lineTo(progressPct * w, h);
    ctx.stroke();
  }
}

function seekWaveform(e) {
  if (!audioElement.duration) return;
  const canvas = document.getElementById('waveformCanvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  audioElement.currentTime = pct * audioElement.duration;
}

function togglePlayPause() {
  const btn = document.getElementById('btnPlayPause');
  if (audioElement.src && !audioElement.paused) {
    audioElement.pause();
    isPlaying = false;
    if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[24px]">play_arrow</span>';
  } else if (audioElement.src) {
    audioElement.play().catch(() => {});
    isPlaying = true;
    if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[24px]">pause</span>';
  }
}

function stopAudio() {
  isPlaying = false;
  if (audioElement.src) {
    audioElement.pause();
    audioElement.currentTime = 0;
  }
  const btn = document.getElementById('btnPlayPause');
  if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[24px]">play_arrow</span>';
  const timer = document.getElementById('playbackTimer');
  if (timer) timer.textContent = '00:00 / 00:00';
  drawWaveform(0);
}

function playAudioUrl(url, title = "Generated Audio") {
  currentAudioUrl = url;
  audioElement.src = url;
  audioElement.load();
  const placeholder = document.getElementById('waveformPlaceholder');
  if (placeholder) placeholder.classList.add('hidden');
  const btnPlay = document.getElementById('btnPlayPause');
  const btnStop = document.getElementById('btnStop');
  const btnDl = document.getElementById('btnDownload');
  if (btnPlay) btnPlay.disabled = false;
  if (btnStop) btnStop.disabled = false;
  if (btnDl) btnDl.disabled = false;

  audioElement.play().catch(() => {});
  isPlaying = true;
  if (btnPlay) btnPlay.innerHTML = '<span class="material-symbols-outlined text-[24px]">pause</span>';
}

function downloadCurrentWav() {
  if (currentAudioUrl) {
    const fmt = document.getElementById('exportFormatSelect')?.value || 'wav';
    const a = document.createElement('a');
    a.href = currentAudioUrl;
    a.download = `chatterbox-${Date.now()}.${fmt}`;
    a.click();
    showToast('success', `Đang tải file âm thanh (${fmt.toUpperCase()})...`);
  } else {
    showToast('warning', 'Chưa có file âm thanh để tải về.');
  }
}

// A/B Comparison Slots
function saveSlotA() {
  if (!currentAudioUrl) return showToast('warning', 'Chưa có audio để lưu vào Bản A.');
  slotA = currentAudioUrl;
  const btn = document.getElementById('btnPlayA');
  if (btn) {
    btn.disabled = false;
    btn.className = 'px-2.5 py-1 rounded bg-purple-600 text-white border border-purple-500 cursor-pointer font-bold';
  }
  showToast('success', 'Đã lưu audio hiện tại vào Bản A!');
}

function saveSlotB() {
  if (!currentAudioUrl) return showToast('warning', 'Chưa có audio để lưu vào Bản B.');
  slotB = currentAudioUrl;
  const btn = document.getElementById('btnPlayB');
  if (btn) {
    btn.disabled = false;
    btn.className = 'px-2.5 py-1 rounded bg-blue-600 text-white border border-blue-500 cursor-pointer font-bold';
  }
  showToast('success', 'Đã lưu audio hiện tại vào Bản B!');
}

function playSlotA() {
  if (slotA) {
    playAudioUrl(slotA);
    showToast('info', 'Đang phát Bản A');
  }
}

function playSlotB() {
  if (slotB) {
    playAudioUrl(slotB);
    showToast('info', 'Đang phát Bản B');
  }
}

function applyQualityPreset(val) {
  if (!val) return;
  const modelSelect = document.getElementById('ttsModelSelect');
  if (val === 'fast') {
    if (modelSelect) modelSelect.value = 'nano';
    handleModelChange('nano');
    setSlider('sliderTemp', 'valTemp', 0.50);
    setSlider('sliderPace', 'valPace', 0.60);
    showToast('info', 'Đã áp dụng Preset: Siêu Nhanh (Nano / Low Latency)');
  } else if (val === 'balanced') {
    setSlider('sliderTemp', 'valTemp', 0.65);
    setSlider('sliderPace', 'valPace', 0.50);
    showToast('info', 'Đã áp dụng Preset: Cân Bằng (Tự nhiên / Mượt mà)');
  } else if (val === 'expressive') {
    if (modelSelect) modelSelect.value = 'turbo';
    handleModelChange('turbo');
    setSlider('sliderTemp', 'valTemp', 0.85);
    setSlider('sliderExaggeration', 'valExaggeration', 1.0);
    showToast('info', 'Đã áp dụng Preset: Biểu Cảm Cao (Turbo / Expressive)');
  }
}

async function cancelCurrentJob() {
  if (!currentActiveJobId) return;
  try {
    const res = await fetch(`/api/v1/jobs/${currentActiveJobId}/cancel`, { method: 'POST' });
    if (res.ok) {
      showToast('warning', 'Đã gửi lệnh hủy tác vụ tới server!');
    }
  } catch (e) {
    showToast('error', 'Lỗi khi gửi yêu cầu hủy: ' + e.message);
  }
}

function resetTtsUi(btn, origIcon, origText) {
  if (btn) {
    btn.innerHTML = `${origIcon}<span>${origText}</span>`;
    btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = false;
  }
  const progressBox = document.getElementById('ttsProgressContainer');
  if (progressBox) progressBox.classList.add('hidden');
  currentActiveJobId = null;
}

async function triggerSynthesis() {
  const btn = document.getElementById('generateBtn');
  const promptInput = document.getElementById('promptInput');
  const text = promptInput ? promptInput.value.trim() : '';
  if (!text) return showToast('warning', 'Vui lòng nhập văn bản cần phát âm.');

  const isLongText = document.getElementById('chkLongTextMode')?.checked;
  const progressBox = document.getElementById('ttsProgressContainer');
  const progressFill = document.getElementById('ttsProgressFill');
  const progressPercent = document.getElementById('ttsProgressPercent');
  const stageMsg = document.getElementById('ttsStageMessage');

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[22px]">progress_activity</span><span>Đang xử lý...</span>';
    btn.classList.add('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = true;
  }

  if (progressBox) {
    progressBox.classList.remove('hidden');
    if (progressFill) progressFill.style.width = '5%';
    if (progressPercent) progressPercent.textContent = '5%';
    if (stageMsg) stageMsg.textContent = isLongText ? '📖 Đang phân đoạn & chuẩn bị render...' : '⏳ Đang khởi chạy tiến trình...';
  }

  try {
    const formData = new FormData();
    formData.append('text', text);
    const selectedModel = document.getElementById('ttsModelSelect')?.value || 'nano';
    formData.append('model', selectedModel);
    formData.append('temperature', document.getElementById('sliderTemp')?.value || '0.8');
    formData.append('repetition_penalty', '1.2');
    if (uploadedRefFile) {
      formData.append('audio_prompt', uploadedRefFile);
    }

    let endpoint = '/api/v1/tts/turbo';
    if (isLongText) {
      endpoint = '/api/v1/tts/long-text';
      formData.append('pause_duration', '0.6');
    } else if (selectedModel === 'standard') {
      endpoint = '/api/v1/tts/standard';
    }

    const response = await fetch(endpoint, { method: 'POST', body: formData });

    if (response.ok) {
      const job = await response.json();
      currentActiveJobId = job.id;
      await pollJob(job.id, btn, 'SINH GIỌNG NÓI (Ctrl + Enter)', '<span class="material-symbols-outlined text-[22px]">play_circle</span>');
    } else {
      const errData = await response.json().catch(() => ({}));
      showToast('error', 'Lỗi khi gửi yêu cầu tới server API: ' + (errData.detail || response.statusText));
      resetTtsUi(btn, '<span class="material-symbols-outlined text-[22px]">play_circle</span>', 'SINH GIỌNG NÓI (Ctrl + Enter)');
    }
  } catch (err) {
    showToast('error', 'Không thể kết nối tới server API: ' + err.message);
    resetTtsUi(btn, '<span class="material-symbols-outlined text-[22px]">play_circle</span>', 'SINH GIỌNG NÓI (Ctrl + Enter)');
  }
}

async function pollJob(jobId, btn = null, origText = 'SINH GIỌNG NÓI (Ctrl + Enter)', origIcon = '<span class="material-symbols-outlined text-[22px]">play_circle</span>') {
  const generateBtn = btn || document.getElementById('generateBtn');
  const progressFill = document.getElementById('ttsProgressFill');
  const progressPercent = document.getElementById('ttsProgressPercent');
  const stageMsg = document.getElementById('ttsStageMessage');
  currentActiveJobId = jobId;

  const phaseLabels = {
    'queued': '⏳ Đang chờ trong hàng đợi...',
    'loading_model': '🧠 Đang nạp mô hình vào bộ nhớ...',
    'generating_tokens': '⚡ Đang sinh ngữ điệu & mã âm thanh...',
    'generating_audio': '🔊 Đang giải mã sóng âm thanh (WAV)...',
    'merging_audio': '✂️ Đang nối ghép các đoạn hoàn chỉnh...',
    'completed': '✅ Hoàn tất thành công!',
    'failed': '❌ Thất bại',
    'cancelled': '⚠️ Đã hủy tác vụ'
  };

  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}`);
      if (res.ok) {
        const data = await res.json();
        
        if (progressFill && progressPercent && stageMsg) {
          const pct = Math.max(5, data.progress_percent || 0);
          progressFill.style.width = `${pct}%`;
          progressPercent.textContent = `${pct}%`;
          stageMsg.textContent = phaseLabels[data.phase] || (data.phase ? `⏳ Đang xử lý (${data.phase})...` : '⏳ Đang xử lý...');
        }

        if (data.status === 'completed' && data.audio_url) {
          clearInterval(interval);
          resetTtsUi(generateBtn, origIcon, origText);

          const bmBadge = document.getElementById('benchmarkBadge');
          if (bmBadge) {
            if (data.benchmark) {
              const bm = data.benchmark;
              const bmSpeed = document.getElementById('bmSpeedText');
              const bmRtf = document.getElementById('bmRtfText');
              const bmInfer = document.getElementById('bmInferTime');
              const bmDur = document.getElementById('bmAudioDur');
              if (bmSpeed) bmSpeed.textContent = bm.faster_than_realtime ? `Nhanh hơn thời gian thực ${bm.faster_than_realtime}x` : 'Hoàn tất';
              if (bmRtf) bmRtf.textContent = `RTF: ${bm.realtime_factor || 'N/A'}`;
              if (bmInfer) bmInfer.textContent = `Inference: ${bm.inference_seconds || 0}s`;
              if (bmDur) bmDur.textContent = `Thời lượng: ${bm.audio_duration_seconds || 0}s`;
              bmBadge.classList.remove('hidden');
            } else {
              bmBadge.classList.add('hidden');
            }
          }

          playAudioUrl(data.audio_url);
          if (typeof refreshHistory === 'function') refreshHistory();
          showToast('success', 'Sinh giọng nói hoàn tất thành công!');
        } else if (data.status === 'failed') {
          clearInterval(interval);
          resetTtsUi(generateBtn, origIcon, origText);
          showToast('error', 'Quá trình sinh giọng bị lỗi: ' + (data.error || "Lỗi không xác định"));
        } else if (data.status === 'cancelled') {
          clearInterval(interval);
          resetTtsUi(generateBtn, origIcon, origText);
          showToast('info', 'Tác vụ đã được hủy theo yêu cầu.');
        }
      }
    } catch (e) {}
  }, 400);
}
