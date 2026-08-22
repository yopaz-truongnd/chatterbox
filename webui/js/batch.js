/**
 * Chatterbox TTS Studio - Batch Studio, Script Parser & Long Audio Engine
 */

const BUILTIN_VOICES = {
  'mc_male': { name: 'MC Nam Thời Sự', exag: 0.35, pace: 0.55, temp: 0.65 },
  'editor_female': { name: 'Nữ Biên Tập Viên', exag: 0.45, pace: 0.50, temp: 0.70 },
  'story_night': { name: 'Kể Chuyện Đêm Khuya', exag: 0.85, pace: 0.45, temp: 0.85 },
  'review_fast': { name: 'Review & Recap', exag: 0.60, pace: 0.75, temp: 0.80 },
  'anime_fun': { name: 'Hoạt Hình / Anime', exag: 1.25, pace: 0.60, temp: 0.95 },
  'ai_assistant': { name: 'Trợ Lý Ảo AI', exag: 0.40, pace: 0.50, temp: 0.60 }
};

let lastBatchJobId = null;

function applyBuiltinVoice(key, btnEl) {
  const v = BUILTIN_VOICES[key];
  if (!v) return;

  const exagEl = document.getElementById('sliderExaggeration');
  const valExag = document.getElementById('valExaggeration');
  const paceEl = document.getElementById('sliderPace');
  const valPace = document.getElementById('valPace');
  const tempEl = document.getElementById('sliderTemp');
  const valTemp = document.getElementById('valTemp');

  if (exagEl) exagEl.value = v.exag;
  if (valExag) valExag.textContent = v.exag.toFixed(2);
  if (paceEl) paceEl.value = v.pace;
  if (valPace) valPace.textContent = v.pace.toFixed(2);
  if (tempEl) tempEl.value = v.temp;
  if (valTemp) valTemp.textContent = v.temp.toFixed(2);
  if (typeof updateParamsSummaryBadge === 'function') updateParamsSummaryBadge();

  const ttsSelect = document.getElementById('ttsCharacterSelect');
  if (ttsSelect) ttsSelect.value = `builtin:${key}`;

  showToast('success', `Đã kích hoạt phong cách đọc "${v.name}"!`);
}

function handleBatchSplitRuleChange(val) {
  const box = document.getElementById('batchCustomDelimiterBox');
  if (box) {
    if (val === 'custom') box.classList.remove('hidden');
    else box.classList.add('hidden');
  }
}

function handleBatchTextareaInput() {
  const text = document.getElementById('batchTextarea')?.value || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const chars = text.length;
  const countEl = document.getElementById('batchTextareaWordCount');
  if (countEl) countEl.textContent = `${words} từ • ${chars} ký tự`;
  updateBatchEstimation();
}

function loadBatchSampleScript() {
  const sample = `[Narrator]: Chào mừng quý vị thính giả đang theo dõi bản tin công nghệ hôm nay.
[Sarah]: Hôm nay chúng tôi xin giới thiệu bản cập nhật Batch Studio hoàn toàn mới của Chatterbox.
[John]: Hệ thống đã chính thức hỗ trợ nạp model một lần, nhận dạng nhân vật và tự động hòa âm BGM.
[Sarah]: Tốc độ xử lý giờ đây nhanh hơn gấp nhiều lần và tiết kiệm tài nguyên bộ nhớ tối đa.
[Narrator]: Hãy cùng bắt đầu trải nghiệm ngay bây giờ!`;
  const txt = document.getElementById('batchTextarea');
  if (txt) txt.value = sample;
  handleBatchTextareaInput();
  parseBatchLines();
  showToast('success', 'Đã nạp kịch bản mẫu đối thoại đa nhân vật!');
}

function toggleBatchSearchReplace() {
  const bar = document.getElementById('batchSearchReplaceBar');
  if (bar) {
    bar.classList.toggle('hidden');
    if (!bar.classList.contains('hidden')) {
      document.getElementById('batchFindInput')?.focus();
    }
  }
}

function batchFindNext() {
  const query = document.getElementById('batchFindInput')?.value.trim();
  const statusEl = document.getElementById('batchSearchStatus');
  if (!query) return showToast('warning', 'Vui lòng nhập từ khóa cần tìm.');

  if (parsedBatchLines.length === 0) return showToast('warning', 'Chưa có dòng kịch bản nào.');

  const total = parsedBatchLines.length;
  let foundIdx = -1;
  for (let i = 1; i <= total; i++) {
    const checkIdx = (batchSearchIndex + i) % total;
    if (parsedBatchLines[checkIdx].toLowerCase().includes(query.toLowerCase())) {
      foundIdx = checkIdx;
      break;
    }
  }

  if (foundIdx !== -1) {
    batchSearchIndex = foundIdx;
    const inputEl = document.getElementById(`batchLineText-${foundIdx}`);
    if (inputEl) {
      inputEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      inputEl.focus();
      inputEl.select();
    }
    if (statusEl) statusEl.textContent = `Đã tìm thấy tại dòng #${foundIdx + 1}`;
  } else {
    if (statusEl) statusEl.textContent = 'Không tìm thấy kết quả phù hợp.';
    showToast('info', 'Không tìm thấy thêm kết quả.');
  }
}

function batchReplaceCurrent() {
  const query = document.getElementById('batchFindInput')?.value.trim();
  const replaceVal = document.getElementById('batchReplaceInput')?.value || '';
  if (!query) return showToast('warning', 'Vui lòng nhập từ khóa cần tìm.');

  if (batchSearchIndex >= 0 && batchSearchIndex < parsedBatchLines.length) {
    const currentText = parsedBatchLines[batchSearchIndex];
    const regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    if (regex.test(currentText)) {
      parsedBatchLines[batchSearchIndex] = currentText.replace(regex, replaceVal);
      const inputEl = document.getElementById(`batchLineText-${batchSearchIndex}`);
      if (inputEl) inputEl.value = parsedBatchLines[batchSearchIndex];
      showToast('success', `Đã thay thế tại dòng #${batchSearchIndex + 1}`);
      batchFindNext();
      return;
    }
  }
  batchFindNext();
}

function batchReplaceAll() {
  const query = document.getElementById('batchFindInput')?.value.trim();
  const replaceVal = document.getElementById('batchReplaceInput')?.value || '';
  const statusEl = document.getElementById('batchSearchStatus');
  if (!query) return showToast('warning', 'Vui lòng nhập từ khóa cần tìm.');

  let replaceCount = 0;
  const regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  parsedBatchLines = parsedBatchLines.map(line => {
    const matches = (line.match(regex) || []).length;
    replaceCount += matches;
    return line.replace(regex, replaceVal);
  });

  renderBatchTable();
  if (statusEl) statusEl.textContent = `Đã thay thế ${replaceCount} vị trí trong toàn bộ kịch bản.`;
  showToast('success', `Đã thay thế thành công ${replaceCount} vị trí!`);
}

function autoMatchSpeakerToCharacter(speakerName) {
  if (!speakerName || !allCharactersCache || allCharactersCache.length === 0) return null;
  const clean = speakerName.trim().toLowerCase();
  const exact = allCharactersCache.find(c => c.name.toLowerCase() === clean);
  if (exact) return `char:${exact.id}`;
  const partial = allCharactersCache.find(c => c.name.toLowerCase().includes(clean) || clean.includes(c.name.toLowerCase()));
  if (partial) return `char:${partial.id}`;
  return null;
}

function handleBatchFileUpload(input) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    const fname = file.name.toLowerCase();
    const reader = new FileReader();
    reader.onload = (e) => {
      let content = e.target.result || '';
      let extractedLines = [];
      let voiceOverrides = {};
      let pauseOverrides = {};

      if (fname.endsWith('.srt') || fname.endsWith('.vtt')) {
        const lines = content.split('\n');
        let currentTextLines = [];
        for (let line of lines) {
          line = line.trim();
          if (!line) {
            if (currentTextLines.length > 0) {
              const combined = currentTextLines.join(' ').replace(/<\/?[^>]+(>|$)/g, '').trim();
              if (combined) extractedLines.push(combined);
              currentTextLines = [];
            }
            continue;
          }
          if (/^\d+$/.test(line)) continue;
          if (/-->/.test(line)) continue;
          if (/^WEBVTT/i.test(line) || /^NOTE/i.test(line)) continue;
          currentTextLines.push(line);
        }
        if (currentTextLines.length > 0) {
          const combined = currentTextLines.join(' ').replace(/<\/?[^>]+(>|$)/g, '').trim();
          if (combined) extractedLines.push(combined);
        }
      } else if (fname.endsWith('.csv')) {
        const rows = content.split('\n').map(r => r.trim()).filter(r => r.length > 0);
        if (rows.length > 0) {
          const hasHeader = /speaker|text|dialogue|voice|thoai/i.test(rows[0]);
          const dataRows = hasHeader ? rows.slice(1) : rows;
          dataRows.forEach((row, idx) => {
            const cols = row.split(',').map(c => c.trim().replace(/^"|"$/g, '').replace(/""/g, '"'));
            if (cols.length >= 2) {
              const spk = cols[0];
              const txt = cols[1];
              if (txt) {
                extractedLines.push(txt);
                const matchedChar = autoMatchSpeakerToCharacter(spk);
                if (matchedChar) voiceOverrides[idx] = matchedChar;
              }
            } else if (cols.length === 1 && cols[0]) {
              extractedLines.push(cols[0]);
            }
          });
        }
      } else if (fname.endsWith('.md')) {
        const lines = content.split('\n');
        for (let line of lines) {
          line = line.trim();
          if (!line || line.startsWith('```') || line.startsWith('![')) continue;
          line = line.replace(/^#{1,6}\s+/, '').replace(/^[-*+]\s+/, '').replace(/^\d+\.\s+/, '').replace(/^>\s+/, '');
          line = line.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*_~]{1,3}/g, '').trim();
          if (line) extractedLines.push(line);
        }
      } else {
        const rawLines = content.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        const dialogRegex = /^(?:\[(?<spk>[^\]]+)\]|(?<raw_spk>[A-Za-z0-9_\u00C0-\u1EF9\s\.\-]+?))\s*(?:\([^)]*\))?\s*[:：]\s*(?<diag>.*)$/;

        rawLines.forEach((line, idx) => {
          const match = line.match(dialogRegex);
          if (match && match.groups && match.groups.diag && match.groups.diag.trim()) {
            const spk = (match.groups.spk || match.groups.raw_spk || '').trim();
            const diag = match.groups.diag.trim();
            extractedLines.push(diag);
            const matchedChar = autoMatchSpeakerToCharacter(spk);
            if (matchedChar) voiceOverrides[idx] = matchedChar;
          } else {
            extractedLines.push(line);
          }
        });
      }

      if (extractedLines.length > 0) {
        document.getElementById('batchTextarea').value = extractedLines.join('\n');
        parsedBatchLines = extractedLines;
        parsedBatchVoiceOverrides = voiceOverrides;
        parsedBatchPauseOverrides = pauseOverrides;
        batchRowData = {};
        renderBatchTable();
        updateBatchEstimation();
        showToast('success', `Đã phân tích thành công ${extractedLines.length} dòng từ file "${file.name}"!`);
      } else {
        showToast('warning', 'Không tìm thấy nội dung văn bản hợp lệ trong file.');
      }
    };
    reader.onerror = () => {
      showToast('error', `Không thể đọc file "${file.name}"`);
    };
    reader.readAsText(file);
  }
}

function parseBatchLines() {
  const text = document.getElementById('batchTextarea')?.value || '';
  if (!text.trim()) {
    parsedBatchLines = [];
    parsedBatchVoiceOverrides = {};
    parsedBatchPauseOverrides = {};
    batchRowData = {};
    renderBatchTable();
    updateBatchEstimation();
    return showToast('warning', 'Vui lòng nhập hoặc dán nội dung kịch bản.');
  }

  const rule = document.getElementById('batchSplitRule')?.value || 'line';
  let rawPieces = [];

  if (rule === 'sentence') {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    for (const line of lines) {
      const parts = line.split(/(?<=[.?!…])\s+/);
      for (const part of parts) {
        const p = part.trim();
        if (!p) continue;
        if (!/[A-Za-z0-9\u00C0-\u1EF9]/.test(p)) {
          if (rawPieces.length > 0) {
            rawPieces[rawPieces.length - 1] = (rawPieces[rawPieces.length - 1] + ' ' + p).trim();
          }
        } else {
          rawPieces.push(p);
        }
      }
    }
  } else if (rule === 'paragraph') {
    rawPieces = text.split(/\n\s*\n/).map(l => l.trim()).filter(l => l.length > 0);
  } else if (rule === 'custom') {
    const delim = document.getElementById('batchCustomDelimiter')?.value || '|';
    rawPieces = text.split(delim).map(l => l.trim()).filter(l => l.length > 0);
  } else {
    rawPieces = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  }

  const dialogRegex = /^(?:\[(?<spk>[^\]]+)\]|(?<raw_spk>[A-Za-z0-9_\u00C0-\u1EF9\s\.\-]+?))\s*(?:\([^)]*\))?\s*[:：]\s*(?<diag>.*)$/;
  const finalLines = [];
  const newVoiceOverrides = {};

  rawPieces.forEach((piece, idx) => {
    const match = piece.match(dialogRegex);
    if (match && match.groups && match.groups.diag && match.groups.diag.trim()) {
      const spk = (match.groups.spk || match.groups.raw_spk || '').trim();
      const diag = match.groups.diag.trim();
      finalLines.push(diag);
      const matchedChar = autoMatchSpeakerToCharacter(spk);
      if (matchedChar) {
        newVoiceOverrides[finalLines.length - 1] = matchedChar;
      }
    } else {
      finalLines.push(piece);
    }
  });

  parsedBatchLines = finalLines;
  parsedBatchVoiceOverrides = newVoiceOverrides;
  parsedBatchPauseOverrides = {};
  batchRowData = {};
  renderBatchTable();
  updateBatchEstimation();
  showToast('info', `Đã tách thành công ${parsedBatchLines.length} dòng kịch bản.`);
}

function getVoiceOptionsHtml(selectedVal = '', rowIdx = null) {
  let html = '<option value="">-- Mặc định --</option>';
  html += '<optgroup label="🎭 Style Presets (Bộ chỉnh phong cách)">';
  for (const [k, v] of Object.entries(BUILTIN_VOICES)) {
    html += `<option value="builtin:${k}" ${selectedVal === 'builtin:' + k ? 'selected' : ''}>🎙️ ${v.name}</option>`;
  }
  html += '</optgroup>';
  if (allCharactersCache.length > 0) {
    html += '<optgroup label="👤 Nhân vật đã lưu (Characters)">';
    allCharactersCache.forEach(c => {
      const val = `char:${c.id}`;
      const star = c.is_default ? '⭐ ' : '';
      const hasAudio = c.has_reference_audio ? '🎵 ' : '⚠️ ';
      html += `<option value="${val}" ${selectedVal === val ? 'selected' : ''}>${hasAudio}${star}${c.name} (${c.language || 'vi'})</option>`;
    });
    html += '</optgroup>';
  }
  return html;
}

function playGlobalVoicePreview() {
  const globalVoice = document.getElementById('batchGlobalVoiceSelect')?.value || '';
  playVoiceValuePreview(globalVoice);
}

function playLineVoicePreview(idx) {
  const globalVoice = document.getElementById('batchGlobalVoiceSelect')?.value || '';
  const voice = parsedBatchVoiceOverrides[idx] !== undefined ? parsedBatchVoiceOverrides[idx] : globalVoice;
  playVoiceValuePreview(voice);
}

function playVoiceValuePreview(voiceVal) {
  if (!voiceVal) {
    return showToast('info', 'Giọng mặc định theo cấu hình model.');
  }
  if (voiceVal.startsWith('char:')) {
    const charId = voiceVal.replace('char:', '');
    const char = allCharactersCache.find(c => c.id === charId);
    if (char && char.reference_audio_url) {
      if (typeof playAudioUrl === 'function') playAudioUrl(char.reference_audio_url);
      showToast('info', `Đang nghe thử mẫu giọng nhân vật "${char.name}"`);
    } else {
      showToast('warning', `Nhân vật "${char?.name || charId}" chưa có file reference audio mẫu.`);
    }
  } else if (voiceVal.startsWith('builtin:')) {
    const key = voiceVal.replace('builtin:', '');
    const v = BUILTIN_VOICES[key];
    showToast('info', `Style Preset: ${v ? v.name : key} (Điều chỉnh phong cách đọc)`);
  }
}

function applyGlobalVoiceToAllBatchLines() {
  const globalVoice = document.getElementById('batchGlobalVoiceSelect')?.value || '';
  parsedBatchLines.forEach((_, idx) => {
    parsedBatchVoiceOverrides[idx] = globalVoice;
    const sel = document.getElementById(`batchLineVoice-${idx}`);
    if (sel) sel.value = globalVoice;
  });
  const name = document.getElementById('batchGlobalVoiceSelect')?.selectedOptions[0]?.text || 'Mặc định';
  showToast('success', `Đã gán giọng "${name}" cho tất cả ${parsedBatchLines.length} dòng!`);
}

function updateBatchLineVoice(idx, val) {
  parsedBatchVoiceOverrides[idx] = val;
}

function updateBatchLineText(idx, val) {
  parsedBatchLines[idx] = val;
  updateBatchEstimation();
}

function updateBatchLinePause(idx, val) {
  const p = parseFloat(val);
  if (!isNaN(p) && p >= 0) {
    parsedBatchPauseOverrides[idx] = p;
  }
}

function handleGlobalPauseChange(val) {
  const el = document.getElementById('valBatchPause');
  if (el) el.textContent = parseFloat(val).toFixed(1) + 's';
}

function addBatchEmptyLine() {
  parsedBatchLines.push("Dòng kịch bản mới...");
  renderBatchTable();
  updateBatchEstimation();
}

function deleteBatchLine(idx) {
  batchUndoBuffer = {
    deletedLine: parsedBatchLines[idx],
    deletedVoice: parsedBatchVoiceOverrides[idx],
    deletedPause: parsedBatchPauseOverrides[idx],
    deletedRowData: batchRowData[idx],
    deletedIdx: idx,
    lines: [...parsedBatchLines],
    voices: { ...parsedBatchVoiceOverrides },
    pauses: { ...parsedBatchPauseOverrides },
    rowData: { ...batchRowData },
  };

  parsedBatchLines.splice(idx, 1);
  const newOverrides = {};
  const newPauses = {};
  const newRowData = {};
  let newIdx = 0;
  for (let i = 0; i <= parsedBatchLines.length; i++) {
    if (i === idx) continue;
    if (parsedBatchVoiceOverrides[i] !== undefined) newOverrides[newIdx] = parsedBatchVoiceOverrides[i];
    if (parsedBatchPauseOverrides[i] !== undefined) newPauses[newIdx] = parsedBatchPauseOverrides[i];
    if (batchRowData[i] !== undefined) newRowData[newIdx] = batchRowData[i];
    newIdx++;
  }
  parsedBatchVoiceOverrides = newOverrides;
  parsedBatchPauseOverrides = newPauses;
  batchRowData = newRowData;

  renderBatchTable();
  updateBatchEstimation();
  showToastWithUndo(`Đã xóa dòng #${idx + 1}`, () => undoBatchDelete());
}

function undoBatchDelete() {
  if (!batchUndoBuffer) return;
  parsedBatchLines = [...batchUndoBuffer.lines];
  parsedBatchVoiceOverrides = { ...batchUndoBuffer.voices };
  parsedBatchPauseOverrides = { ...batchUndoBuffer.pauses };
  batchRowData = { ...batchUndoBuffer.rowData };
  batchUndoBuffer = null;
  renderBatchTable();
  updateBatchEstimation();
  showToast('success', 'Đã hoàn tác khôi phục dòng kịch bản!');
}

function showToastWithUndo(message, undoFn) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'pointer-events-auto flex items-center justify-between gap-2 p-3 rounded-xl bg-[#18151E] border border-purple-500/50 shadow-m3-2 text-xs text-white toast-enter';
  toast.innerHTML = `
    <div class="flex items-center gap-2">
      <span class="material-symbols-outlined text-purple-400 text-[18px]">info</span>
      <span>${message}</span>
    </div>
    <button type="button" id="undoBtnToast" class="px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-700 font-bold text-white text-xs cursor-pointer shadow-m3-1">Hoàn tác</button>
  `;
  const undoBtn = toast.querySelector('#undoBtnToast');
  if (undoBtn) {
    undoBtn.addEventListener('click', () => {
      undoFn();
      toast.remove();
    });
  }
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-leave');
    setTimeout(() => toast.remove(), 250);
  }, 6000);
}

function clearBatchAll() {
  if (parsedBatchLines.length === 0) return;
  batchUndoBuffer = {
    lines: [...parsedBatchLines],
    voices: { ...parsedBatchVoiceOverrides },
    pauses: { ...parsedBatchPauseOverrides },
    rowData: { ...batchRowData },
  };
  parsedBatchLines = [];
  parsedBatchVoiceOverrides = {};
  parsedBatchPauseOverrides = {};
  batchRowData = {};
  const txt = document.getElementById('batchTextarea');
  if (txt) txt.value = '';
  renderBatchTable();
  updateBatchEstimation();
  showToastWithUndo('Đã xóa toàn bộ danh sách kịch bản.', () => undoBatchDelete());
}

function toggleSelectAllBatch(master) {
  document.querySelectorAll('.batch-row-chk').forEach(c => c.checked = master.checked);
}

function toggleBgmControls(enabled) {
  const el = document.getElementById('bgmControls');
  if (!el) return;
  if (enabled) {
    el.className = 'space-y-2 transition-opacity';
  } else {
    el.className = 'space-y-2 opacity-40 pointer-events-none transition-opacity';
  }
}

function handleBgmUpload(input) {
  if (input.files && input.files[0]) {
    const el = document.getElementById('bgmFileName');
    if (el) el.textContent = input.files[0].name;
    showToast('success', `Đã chọn file nhạc nền "${input.files[0].name}"`);
  }
}

function filterBatchStatus(status) {
  batchCurrentFilter = status;
  document.querySelectorAll('.batch-filter-btn').forEach(b => {
    b.className = 'batch-filter-btn px-2.5 py-0.5 rounded-full bg-[#231F2A] hover:bg-[#2D2836] text-slate-300 text-xs cursor-pointer';
  });
  const activeBtn = document.getElementById(`batchFilter-${status}`);
  if (activeBtn) {
    activeBtn.className = 'batch-filter-btn active px-2.5 py-0.5 rounded-full bg-purple-600 text-white font-medium text-xs cursor-pointer';
  }

  parsedBatchLines.forEach((_, idx) => {
    const row = document.getElementById(`batchRow-${idx}`);
    if (!row) return;
    const rowInfo = batchRowData[idx];
    const rowStatus = rowInfo ? rowInfo.status : 'ready';

    if (status === 'all' || rowStatus === status) {
      row.classList.remove('hidden');
    } else {
      row.classList.add('hidden');
    }
  });
}

function updateBatchFilterCounts() {
  let readyCount = 0;
  let procCount = 0;
  let compCount = 0;
  let failCount = 0;

  parsedBatchLines.forEach((_, idx) => {
    const r = batchRowData[idx];
    if (!r || r.status === 'ready') readyCount++;
    else if (r.status === 'processing') procCount++;
    else if (r.status === 'completed') compCount++;
    else if (r.status === 'failed') failCount++;
  });

  const elAll = document.getElementById('cntFilterAll');
  const elReady = document.getElementById('cntFilterReady');
  const elProc = document.getElementById('cntFilterProcessing');
  const elComp = document.getElementById('cntFilterCompleted');
  const elFail = document.getElementById('cntFilterFailed');

  if (elAll) elAll.textContent = parsedBatchLines.length;
  if (elReady) elReady.textContent = readyCount;
  if (elProc) elProc.textContent = procCount;
  if (elComp) elComp.textContent = compCount;
  if (elFail) elFail.textContent = failCount;
}

function updateBatchEstimation() {
  const card = document.getElementById('batchEstimationCard');
  const totalLines = parsedBatchLines.length;
  if (totalLines === 0) {
    if (card) card.classList.add('hidden');
    return;
  }
  if (card) card.classList.remove('hidden');

  let totalWords = 0;
  parsedBatchLines.forEach(l => {
    totalWords += l.trim().split(/\s+/).length;
  });

  const selectedModel = document.getElementById('batchModelSelect')?.value || 'auto';
  const effModel = (selectedModel === 'auto') ? systemRecommendedModel : selectedModel;

  const timePerLine = (effModel === 'nano') ? 1.2 : 2.5;
  const totalSecsEst = Math.round(totalLines * timePerLine);
  const estMin = Math.ceil(totalSecsEst / 60);
  const estMb = Math.max(1, Math.round((totalLines * 3 * 150) / 1024));

  const linesEl = document.getElementById('batchEstLinesCount');
  const wordsEl = document.getElementById('batchEstWordsCount');
  const durEl = document.getElementById('batchEstDuration');
  const sizeEl = document.getElementById('batchEstAudioSize');
  const hwEl = document.getElementById('batchEstHardwareProfile');

  if (linesEl) linesEl.textContent = `${totalLines} dòng`;
  if (wordsEl) wordsEl.textContent = `(~${totalWords} từ)`;
  if (durEl) durEl.textContent = estMin <= 1 ? `~${totalSecsEst}s` : `~${estMin} phút`;
  if (sizeEl) sizeEl.textContent = `~${estMb} MB`;
  if (hwEl) hwEl.textContent = `Model ${effModel.toUpperCase()} (Nạp 1 lần)`;
}

function renderBatchTable() {
  const container = document.getElementById('batchTableContainer');
  const tbody = document.getElementById('batchTableBody');
  const badge = document.getElementById('batchCountBadge');
  const globalVoice = document.getElementById('batchGlobalVoiceSelect')?.value || '';
  const defaultGlobalPause = parseFloat(document.getElementById('batchPauseDuration')?.value) || 0.8;

  if (badge) badge.textContent = `${parsedBatchLines.length} dòng`;
  if (!tbody) return;
  tbody.innerHTML = '';

  if (parsedBatchLines.length > 0) {
    if (container) container.classList.remove('hidden');
    parsedBatchLines.forEach((line, idx) => {
      const selectedVoice = parsedBatchVoiceOverrides[idx] !== undefined ? parsedBatchVoiceOverrides[idx] : globalVoice;
      const linePause = parsedBatchPauseOverrides[idx] !== undefined ? parsedBatchPauseOverrides[idx] : defaultGlobalPause;
      const tr = document.createElement('tr');
      tr.id = `batchRow-${idx}`;
      tr.className = 'hover:bg-[#18151E] transition-colors border-b border-[#3F3A46]/30';

      const rowInfo = batchRowData[idx];
      let statusHtml = '<span class="px-2 py-0.5 rounded bg-[#231F2A] text-slate-400 text-[11px]">Sẵn sàng</span>';
      let playBtnStyle = 'hidden';
      let dlBtnStyle = 'hidden';
      let durText = '--';

      if (rowInfo && rowInfo.status === 'completed') {
        statusHtml = '<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[11px] font-bold">✓ Hoàn tất</span>';
        playBtnStyle = '';
        dlBtnStyle = '';
        durText = rowInfo.duration ? `${rowInfo.duration.toFixed(1)}s` : '--';
      } else if (rowInfo && rowInfo.status === 'processing') {
        statusHtml = '<span class="px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800 text-[11px] animate-pulse">⏳ Đang sinh...</span>';
      } else if (rowInfo && rowInfo.status === 'failed') {
        statusHtml = '<span class="px-2 py-0.5 rounded bg-red-950/60 text-red-300 border border-red-800 text-[11px]">❌ Lỗi</span>';
      }

      tr.innerHTML = `
        <td class="p-2.5 w-8 text-center"><input type="checkbox" class="batch-row-chk w-4 h-4 rounded text-purple-600 cursor-pointer" data-idx="${idx}" checked></td>
        <td class="p-2.5 w-10 font-mono text-purple-400 font-bold text-center">${idx + 1}</td>
        <td class="p-2.5 font-medium text-white max-w-sm">
          <input type="text" id="batchLineText-${idx}" value="${line.replace(/"/g, '&quot;')}" onchange="updateBatchLineText(${idx}, this.value)" class="w-full bg-[#14101A] border border-[#3F3A46]/70 focus:border-purple-500 rounded p-1.5 text-xs text-white focus:outline-none transition-colors">
        </td>
        <td class="p-2.5 w-52">
          <div class="flex items-center gap-1">
            <select id="batchLineVoice-${idx}" onchange="updateBatchLineVoice(${idx}, this.value)" class="bg-[#231F2A] border border-[#3F3A46] rounded-lg px-2 py-1.5 text-xs text-white cursor-pointer w-full focus:border-purple-500">
              ${getVoiceOptionsHtml(selectedVoice, idx)}
            </select>
            <button type="button" onclick="playLineVoicePreview(${idx})" class="p-1 rounded bg-[#231F2A] hover:bg-purple-600 border border-[#3F3A46] text-purple-300 hover:text-white cursor-pointer" title="Nghe thử giọng dòng này">
              <span class="material-symbols-outlined text-[13px]">volume_up</span>
            </button>
          </div>
        </td>
        <td class="p-2.5 w-24 text-center">
          <div class="flex items-center justify-center gap-1">
            <input type="number" step="0.1" min="0" max="5" value="${linePause.toFixed(1)}" onchange="updateBatchLinePause(${idx}, this.value)" class="w-14 bg-[#14101A] border border-[#3F3A46] rounded px-1.5 py-1 text-xs text-purple-300 text-center font-mono focus:outline-none focus:border-purple-500">
            <span class="text-slate-500 text-[10px]">s</span>
          </div>
        </td>
        <td class="p-2.5 w-20 text-center font-mono text-slate-300 text-[11px]" id="batchDur-${idx}">${durText}</td>
        <td class="p-2.5 w-28 text-center" id="batchStatus-${idx}">${statusHtml}</td>
        <td class="p-2.5 w-28 text-right">
          <div class="flex items-center justify-end gap-1">
            <button type="button" onclick="runSingleBatchLine(${idx})" class="p-1 rounded bg-[#231F2A] hover:bg-purple-600 text-purple-300 hover:text-white cursor-pointer transition-colors" title="Sinh audio dòng này">
              <span class="material-symbols-outlined text-[16px]">play_arrow</span>
            </button>
            <button type="button" id="batchPlayBtn-${idx}" onclick="playBatchLineAudio(${idx})" class="${playBtnStyle} p-1 rounded bg-[#231F2A] hover:bg-emerald-600 text-emerald-300 hover:text-white cursor-pointer transition-colors" title="Phát audio">
              <span class="material-symbols-outlined text-[16px]">volume_up</span>
            </button>
            <button type="button" id="batchDownloadBtn-${idx}" onclick="downloadBatchLineAudio(${idx})" class="${dlBtnStyle} p-1 rounded bg-[#231F2A] hover:bg-blue-600 text-blue-300 hover:text-white cursor-pointer transition-colors" title="Tải audio dòng này">
              <span class="material-symbols-outlined text-[16px]">download</span>
            </button>
            <button type="button" onclick="deleteBatchLine(${idx})" class="p-1 rounded hover:bg-red-900/50 text-slate-400 hover:text-red-400 cursor-pointer transition-colors" title="Xóa dòng">
              <span class="material-symbols-outlined text-[16px]">delete</span>
            </button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
    updateBatchFilterCounts();
  } else {
    if (container) container.classList.add('hidden');
  }
}

async function pollJobAsync(jobId) {
  return new Promise((resolve) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/jobs/${jobId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
            clearInterval(interval);
            resolve(data);
          }
        }
      } catch (e) {
        clearInterval(interval);
        resolve(null);
      }
    }, 400);
  });
}

async function runSingleBatchLine(idx) {
  const line = parsedBatchLines[idx];
  if (!line || !line.trim()) return null;

  const statusEl = document.getElementById(`batchStatus-${idx}`);
  const playBtn = document.getElementById(`batchPlayBtn-${idx}`);
  const dlBtn = document.getElementById(`batchDownloadBtn-${idx}`);
  const durEl = document.getElementById(`batchDur-${idx}`);
  if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800 text-[11px] animate-pulse">⏳ Đang sinh...</span>';

  const voice = parsedBatchVoiceOverrides[idx] !== undefined ? parsedBatchVoiceOverrides[idx] : (document.getElementById('batchGlobalVoiceSelect')?.value || '');
  const selectedModelRaw = document.getElementById('batchModelSelect')?.value || 'auto';
  const effModel = (selectedModelRaw === 'auto') ? systemRecommendedModel : selectedModelRaw;

  const formData = new FormData();
  formData.append('text', line);
  formData.append('model', effModel);

  if (voice.startsWith('char:')) {
    const charId = voice.replace('char:', '');
    const char = allCharactersCache.find(c => c.id === charId);
    if (char && !char.has_reference_audio) {
      showToast('warning', `Nhân vật "${char.name}" chưa có reference audio, đang dùng giọng mặc định.`);
    }
    formData.append('character_id', charId);
  } else if (voice.startsWith('builtin:')) {
    const key = voice.replace('builtin:', '');
    const v = BUILTIN_VOICES[key];
    if (v) {
      formData.append('temperature', v.temp.toString());
    }
  }

  batchRowData[idx] = { status: 'processing' };
  updateBatchFilterCounts();

  try {
    let endpoint = '/api/v1/tts/turbo';
    if (effModel === 'nano') endpoint = '/api/v1/tts/nano';
    else if (effModel === 'standard') endpoint = '/api/v1/tts/standard';
    else if (effModel === 'multilingual') {
      endpoint = '/api/v1/tts/multilingual';
      formData.append('language_id', selectedMtlLanguage || 'en');
    }

    const res = await fetch(endpoint, { method: 'POST', body: formData });
    if (res.ok) {
      const job = await res.json();
      const jobId = job.id;

      const resultJob = await pollJobAsync(jobId);
      if (resultJob && resultJob.status === 'completed') {
        const dur = resultJob.duration_seconds || 0.0;
        batchRowData[idx] = { jobId: jobId, audioUrl: resultJob.audio_url, status: 'completed', duration: dur };
        if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[11px] font-bold">✓ Hoàn tất</span>';
        if (durEl) durEl.textContent = `${dur.toFixed(1)}s`;
        if (playBtn) playBtn.classList.remove('hidden');
        if (dlBtn) dlBtn.classList.remove('hidden');
        updateBatchFilterCounts();
        return jobId;
      } else {
        batchRowData[idx] = { status: 'failed', error: resultJob?.error || 'Lỗi sinh audio' };
        if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-red-950/60 text-red-300 border border-red-800 text-[11px]">❌ Thất bại</span>';
        updateBatchFilterCounts();
        return null;
      }
    } else {
      batchRowData[idx] = { status: 'failed' };
      if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-red-950/60 text-red-300 border border-red-800 text-[11px]">❌ Lỗi API</span>';
      updateBatchFilterCounts();
    }
  } catch (e) {
    batchRowData[idx] = { status: 'failed', error: e.message };
    if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-red-950/60 text-red-300 border border-red-800 text-[11px]">❌ Lỗi mạng</span>';
    updateBatchFilterCounts();
  }
  return null;
}

function playBatchLineAudio(idx) {
  const info = batchRowData[idx];
  if (info && info.audioUrl) {
    if (typeof playAudioUrl === 'function') playAudioUrl(info.audioUrl);
    showToast('info', `Đang phát âm thanh dòng #${idx + 1}`);
  } else {
    showToast('warning', 'Chưa có audio cho dòng này.');
  }
}

function downloadBatchLineAudio(idx) {
  const info = batchRowData[idx];
  if (info && info.audioUrl) {
    const a = document.createElement('a');
    a.href = info.audioUrl;
    a.download = `chatterbox_line_${idx + 1}.wav`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('info', `Đang tải xuống audio dòng #${idx + 1}...`);
  } else {
    showToast('warning', 'Chưa có audio cho dòng này.');
  }
}

async function cancelBatchAll() {
  cancelBatchRequested = true;
  if (currentBatchJobId) {
    try {
      const res = await fetch(`/api/v1/jobs/${currentBatchJobId}/cancel`, { method: 'POST' });
      if (res.ok) {
        showToast('warning', 'Đã gửi lệnh hủy tiến trình Batch tới server!');
      }
    } catch (e) {
      showToast('error', 'Lỗi khi gửi yêu cầu hủy: ' + e.message);
    }
  } else {
    showToast('info', 'Đã dừng tiến trình Batch.');
  }
}

function runBatchRetryFailed() {
  const failedIndices = [];
  parsedBatchLines.forEach((_, idx) => {
    if (batchRowData[idx] && batchRowData[idx].status === 'failed') {
      failedIndices.push(idx);
    }
  });
  if (failedIndices.length === 0) {
    return showToast('info', 'Không có dòng nào bị lỗi cần thử lại.');
  }
  document.querySelectorAll('.batch-row-chk').forEach(c => {
    const idx = parseInt(c.getAttribute('data-idx'));
    c.checked = failedIndices.includes(idx);
  });
  runBatchAll({ parentBatchId: lastBatchJobId, retryOfIndices: failedIndices });
}

function runBatchResumeUnfinished() {
  const unfinishedIndices = [];
  parsedBatchLines.forEach((_, idx) => {
    if (!batchRowData[idx] || batchRowData[idx].status !== 'completed') {
      unfinishedIndices.push(idx);
    }
  });
  if (unfinishedIndices.length === 0) {
    return showToast('success', 'Toàn bộ các dòng đã hoàn tất!');
  }
  document.querySelectorAll('.batch-row-chk').forEach(c => {
    const idx = parseInt(c.getAttribute('data-idx'));
    c.checked = unfinishedIndices.includes(idx);
  });
  runBatchAll({ parentBatchId: lastBatchJobId, retryOfIndices: unfinishedIndices });
}

async function runBatchAll(retryContext = {}) {
  if (isBatchRunning) return;
  const btn = document.getElementById('batchRunAllBtn');
  const progressBox = document.getElementById('batchProgressBar');
  const progressFill = document.getElementById('batchProgressFill');
  const progressStage = document.getElementById('batchProgressStage');
  const progressCount = document.getElementById('batchProgressCount');
  const progressPercent = document.getElementById('batchProgressPercent');

  const checkboxes = Array.from(document.querySelectorAll('.batch-row-chk:checked'));
  if (checkboxes.length === 0) return showToast('warning', 'Vui lòng chọn ít nhất 1 dòng để chạy batch.');

  isBatchRunning = true;
  cancelBatchRequested = false;
  if (progressBox) progressBox.classList.remove('hidden');

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang chạy Batch...</span>';
    btn.classList.add('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = true;
  }

  const selectedModelRaw = document.getElementById('batchModelSelect')?.value || 'auto';
  const selectedModel = (selectedModelRaw === 'auto') ? systemRecommendedModel : selectedModelRaw;
  const pauseDur = parseFloat(document.getElementById('batchPauseDuration')?.value) || 0.8;
  const bgmInput = document.getElementById('bgmFileInput');
  const bgmVol = parseFloat(document.getElementById('bgmVolSlider')?.value) || 0.15;
  const chkBgm = document.getElementById('chkEnableBGM');
  const chkDucking = document.getElementById('chkEnableDucking')?.checked ?? true;
  const chkNormalize = document.getElementById('chkNormalizeLoudness')?.checked ?? true;
  const chkCrossfade = document.getElementById('chkCrossfade')?.checked ?? true;
  const exportSrt = document.getElementById('chkExportSrt')?.checked ?? true;

  const linesPayload = [];
  let missingAudioChars = [];

  checkboxes.forEach((c) => {
    const idx = parseInt(c.getAttribute('data-idx'));
    const text = parsedBatchLines[idx];
    const voice = parsedBatchVoiceOverrides[idx] !== undefined ? parsedBatchVoiceOverrides[idx] : (document.getElementById('batchGlobalVoiceSelect')?.value || '');
    const linePause = parsedBatchPauseOverrides[idx] !== undefined ? parsedBatchPauseOverrides[idx] : pauseDur;
    const item = { idx: idx, text: text, pause_duration: linePause };

    if (voice.startsWith('char:')) {
      const charId = voice.replace('char:', '');
      item.character_id = charId;
      const char = allCharactersCache.find(ch => ch.id === charId);
      if (char && !char.has_reference_audio && !missingAudioChars.includes(char.name)) {
        missingAudioChars.push(char.name);
      }
    } else if (voice.startsWith('builtin:')) {
      const key = voice.replace('builtin:', '');
      const v = BUILTIN_VOICES[key];
      if (v) {
        item.temperature = v.temp;
        item.exaggeration = v.exag;
        item.cfg_weight = v.pace;
      }
    }
    linesPayload.push(item);
    batchRowData[idx] = { status: 'processing' };
    const statusEl = document.getElementById(`batchStatus-${idx}`);
    if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800 text-[11px] animate-pulse">⏳ Đang sinh...</span>';
  });

  if (missingAudioChars.length > 0) {
    showToast('warning', `Lưu ý: Các nhân vật (${missingAudioChars.join(', ')}) chưa có file reference audio mẫu, sẽ áp dụng giọng mặc định.`);
  }

  updateBatchFilterCounts();

  const formData = new FormData();
  formData.append('lines_json', JSON.stringify(linesPayload));
  formData.append('model', selectedModel);
  formData.append('pause_duration', pauseDur.toString());
  formData.append('export_srt', exportSrt.toString());
  formData.append('normalize_loudness', chkNormalize.toString());
  formData.append('crossfade_ms', chkCrossfade ? '30' : '0');
  formData.append('bgm_ducking', chkDucking.toString());

  if (retryContext.parentBatchId) {
    formData.append('parent_batch_id', retryContext.parentBatchId);
  }
  if (retryContext.retryOfIndices && retryContext.retryOfIndices.length > 0) {
    formData.append('retry_of_indices', JSON.stringify(retryContext.retryOfIndices));
  }

  if (chkBgm && chkBgm.checked && bgmInput && bgmInput.files && bgmInput.files[0]) {
    formData.append('bgm_file', bgmInput.files[0]);
    formData.append('bgm_volume', bgmVol.toString());
  }

  showToast('info', `Bắt đầu xử lý ${checkboxes.length} dòng kịch bản với model ${selectedModel.toUpperCase()} (nạp 1 lần duy nhất)...`);

  try {
    const res = await fetch('/api/v1/tts/batch', {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Không thể tạo batch job');
    }

    const jobData = await res.json();
    currentBatchJobId = jobData.id;
    lastBatchJobId = jobData.id;

    await new Promise((resolve) => {
      const interval = setInterval(async () => {
        if (cancelBatchRequested) {
          clearInterval(interval);
          resolve();
          return;
        }
        try {
          const jres = await fetch(`/api/v1/jobs/${currentBatchJobId}`);
          if (jres.ok) {
            const jdata = await jres.json();
            const pct = jdata.progress_percent || 0;
            if (progressFill) progressFill.style.width = `${pct}%`;
            if (progressPercent) progressPercent.textContent = `${pct}%`;
            if (progressStage) {
              let msg = jdata.phase;
              if (msg === 'loading_model') msg = `Đang nạp mô hình ${selectedModel.toUpperCase()} một lần...`;
              else if (msg === 'generating_tokens') msg = `Đang sinh ngữ điệu các dòng thoại...`;
              else if (msg === 'merging_audio') msg = `Đang hòa âm & ghép nối toàn bộ...`;
              else if (msg === 'completed') msg = `Hoàn tất toàn bộ kịch bản!`;
              progressStage.textContent = msg;
            }

            if (jdata.lines_results && Array.isArray(jdata.lines_results)) {
              let compCount = 0;
              jdata.lines_results.forEach(r => {
                const rowIdx = r.idx;
                const dur = r.duration_seconds || 0.0;
                if (r.status === 'failed') {
                  batchRowData[rowIdx] = {
                    jobId: currentBatchJobId,
                    status: 'failed',
                    error: r.error || 'Lỗi sinh âm thanh',
                  };
                  const statusEl = document.getElementById(`batchStatus-${rowIdx}`);
                  if (statusEl) statusEl.innerHTML = `<span class="px-2 py-0.5 rounded bg-rose-950/60 text-rose-300 border border-rose-800 text-[11px] font-bold" title="${r.error || ''}">✗ Thất bại</span>`;
                  const playBtn = document.getElementById(`batchPlayBtn-${rowIdx}`);
                  if (playBtn) playBtn.classList.add('hidden');
                  const dlBtn = document.getElementById(`batchDownloadBtn-${rowIdx}`);
                  if (dlBtn) dlBtn.classList.add('hidden');
                } else {
                  compCount++;
                  batchRowData[rowIdx] = {
                    jobId: currentBatchJobId,
                    audioUrl: r.audio_url || `/api/v1/jobs/${currentBatchJobId}/lines/${rowIdx}`,
                    status: 'completed',
                    duration: dur,
                    start_s: r.start_seconds,
                    end_s: r.end_seconds,
                  };
                  const statusEl = document.getElementById(`batchStatus-${rowIdx}`);
                  if (statusEl) statusEl.innerHTML = '<span class="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[11px] font-bold">✓ Hoàn tất</span>';
                  const durEl = document.getElementById(`batchDur-${rowIdx}`);
                  if (durEl) durEl.textContent = `${dur.toFixed(1)}s`;
                  const playBtn = document.getElementById(`batchPlayBtn-${rowIdx}`);
                  if (playBtn) playBtn.classList.remove('hidden');
                  const dlBtn = document.getElementById(`batchDownloadBtn-${rowIdx}`);
                  if (dlBtn) dlBtn.classList.remove('hidden');
                }
              });
              if (progressCount) progressCount.textContent = `${compCount} / ${checkboxes.length}`;
              updateBatchFilterCounts();
            }

            if (jdata.status === 'completed' || jdata.status === 'failed' || jdata.status === 'cancelled') {
              clearInterval(interval);

              if (jdata.benchmark && jdata.benchmark.realtime_factor) {
                try {
                  localStorage.setItem(`chatterbox_rtf_${jdata.benchmark.device}_${jdata.benchmark.model_type}`, jdata.benchmark.realtime_factor.toString());
                } catch(e) {}
              }

              if (jdata.status === 'completed') {
                const card = document.getElementById('batchMergedResultCard');
                const player = document.getElementById('batchMergedAudioPlayer');
                const dlLink = document.getElementById('batchMergedDownloadLink');
                const srtLink = document.getElementById('batchSrtDownloadLink');
                const zipLink = document.getElementById('batchZipDownloadLink');
                const title = document.getElementById('batchMergedTitle');
                const meta = document.getElementById('batchMergedMeta');

                if (card) card.classList.remove('hidden');
                if (title) title.textContent = `Batch_Merged_${checkboxes.length}_lines_${selectedModel}.wav`;
                if (meta) meta.textContent = `Thời lượng: ${jdata.duration_seconds || '0'}s • ${checkboxes.length} dòng thoại`;
                if (player && jdata.audio_url) {
                  player.src = jdata.audio_url;
                }
                if (dlLink && jdata.audio_url) {
                  dlLink.href = jdata.audio_url;
                  dlLink.download = `chatterbox_batch_${currentBatchJobId}.wav`;
                }
                if (srtLink) {
                  if (jdata.srt_url) {
                    srtLink.href = jdata.srt_url;
                    srtLink.download = `chatterbox_subtitles_${currentBatchJobId}.srt`;
                    srtLink.classList.remove('hidden');
                  } else {
                    srtLink.classList.add('hidden');
                  }
                }
                if (zipLink) {
                  if (jdata.zip_url) {
                    zipLink.href = jdata.zip_url;
                    zipLink.download = `chatterbox_batch_package_${currentBatchJobId}.zip`;
                    zipLink.classList.remove('hidden');
                  } else {
                    zipLink.classList.add('hidden');
                  }
                }

                const failedLinesCount = jdata.benchmark?.failed_lines || (jdata.lines_results ? jdata.lines_results.filter(r => r.status === 'failed').length : 0);
                const compLinesCount = jdata.benchmark?.completed_lines || (jdata.lines_results ? jdata.lines_results.filter(r => r.status === 'completed').length : checkboxes.length);
                if (failedLinesCount > 0) {
                  showToast('warning', `Hoàn tất một phần: ${compLinesCount} thành công, ${failedLinesCount} lỗi.`);
                } else {
                  showToast('success', `Đã hoàn tất xử lý Batch ${checkboxes.length} dòng thành công!`);
                }
              } else if (jdata.status === 'cancelled') {
                showToast('warning', 'Tiến trình Batch đã được hủy.');
              } else {
                showToast('error', `Lỗi xử lý Batch: ${jdata.error || 'Lỗi không xác định'}`);
              }
              resolve();
            }
          }
        } catch (e) {
          clearInterval(interval);
          resolve();
        }
      }, 400);
    });

    if (typeof refreshHistory === 'function') refreshHistory();
  } catch (err) {
    showToast('error', `Lỗi Batch: ${err.message}`);
  } finally {
    isBatchRunning = false;
    currentBatchJobId = null;
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">play_arrow</span><span>Chạy Batch tất cả</span>';
      btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
      btn.disabled = false;
    }
    updateBatchFilterCounts();
  }
}

async function runBatchMergeAll() {
  const btn = document.getElementById('batchMergeAllBtn');
  const completedJobIds = [];

  const checkboxes = Array.from(document.querySelectorAll('.batch-row-chk:checked'));
  const targetIndices = checkboxes.length > 0 ? checkboxes.map(c => parseInt(c.getAttribute('data-idx'))) : parsedBatchLines.map((_, i) => i);

  for (const idx of targetIndices) {
    if (batchRowData[idx] && batchRowData[idx].jobId && batchRowData[idx].status === 'completed') {
      completedJobIds.push(batchRowData[idx].jobId);
    }
  }

  if (completedJobIds.length === 0) {
    return showToast('warning', 'Chưa có dòng nào hoàn tất để ghép. Hãy nhấn "Chạy Batch tất cả" trước!');
  }

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang hòa âm ghép nối...</span>';
    btn.classList.add('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = true;
  }

  const pauseDur = parseFloat(document.getElementById('batchPauseDuration')?.value) || 0.8;
  const bgmInput = document.getElementById('bgmFileInput');
  const bgmVol = parseFloat(document.getElementById('bgmVolSlider')?.value) || 0.15;
  const chkBgm = document.getElementById('chkEnableBGM');

  const formData = new FormData();
  formData.append('job_ids', completedJobIds.join(','));
  formData.append('pause_duration', pauseDur.toString());
  if (chkBgm && chkBgm.checked && bgmInput && bgmInput.files && bgmInput.files[0]) {
    formData.append('bgm_file', bgmInput.files[0]);
    formData.append('bgm_volume', bgmVol.toString());
  }

  showToast('info', `Đang tiến hành ghép ${completedJobIds.length} đoạn audio...`);

  try {
    const res = await fetch('/api/v1/batch/merge', {
      method: 'POST',
      body: formData
    });

    if (res.ok) {
      const data = await res.json();
      const card = document.getElementById('batchMergedResultCard');
      const player = document.getElementById('batchMergedAudioPlayer');
      const dlLink = document.getElementById('batchMergedDownloadLink');
      const title = document.getElementById('batchMergedTitle');
      const meta = document.getElementById('batchMergedMeta');

      if (card) card.classList.remove('hidden');
      if (title) title.textContent = `Batch_Merged_${completedJobIds.length}_lines.wav`;
      if (meta) meta.textContent = `Thời lượng: ${data.duration_seconds || '0'}s • Ghép từ ${data.chunks_count || completedJobIds.length} đoạn`;
      if (player) {
        player.src = data.audio_url;
        player.play();
      }
      if (dlLink) {
        dlLink.href = data.audio_url;
        dlLink.download = `chatterbox_merged_${Date.now()}.wav`;
      }

      if (typeof refreshHistory === 'function') refreshHistory();
      showToast('success', data.message || 'Ghép audio hoàn tất thành công!');
    } else {
      const err = await res.json();
      showToast('error', 'Lỗi khi ghép audio: ' + (err.detail || 'Không thể ghép'));
    }
  } catch (err) {
    showToast('error', 'Lỗi kết nối máy chủ: ' + err.message);
  } finally {
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">merge</span><span>Ghép toàn bộ (Merge All)</span>';
      btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
      btn.disabled = false;
    }
  }
}

// Batch project management
function openBatchProjectModal() {
  renderBatchSavedProjects();
  document.getElementById('batchProjectModal')?.classList.remove('hidden');
}

function closeBatchProjectModal() {
  document.getElementById('batchProjectModal')?.classList.add('hidden');
}

function getSavedBatchProjects() {
  try {
    const raw = localStorage.getItem('chatterbox_batch_projects');
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveBatchCurrentProject() {
  const nameInput = document.getElementById('batchProjectNameInput');
  const name = nameInput?.value.trim() || `Dự án Batch ${new Date().toLocaleDateString('vi-VN')}`;
  if (parsedBatchLines.length === 0) {
    return showToast('warning', 'Không có nội dung kịch bản để lưu dự án.');
  }

  const projects = getSavedBatchProjects();
  const projId = 'proj_' + Date.now();
  const newProj = {
    id: projId,
    name: name,
    created_at: new Date().toISOString(),
    lines: parsedBatchLines,
    voiceOverrides: parsedBatchVoiceOverrides,
    pauseOverrides: parsedBatchPauseOverrides,
    rowData: batchRowData,
    model: document.getElementById('batchModelSelect')?.value || 'auto',
    pauseDuration: document.getElementById('batchPauseDuration')?.value || '0.8',
  };

  projects.unshift(newProj);
  localStorage.setItem('chatterbox_batch_projects', JSON.stringify(projects.slice(0, 30)));
  renderBatchSavedProjects();
  if (nameInput) nameInput.value = '';
  showToast('success', `Đã lưu dự án "${name}" thành công!`);
}

function loadBatchProject(projId) {
  const projects = getSavedBatchProjects();
  const p = projects.find(item => item.id === projId);
  if (!p) return showToast('error', 'Không tìm thấy dự án đã chọn.');

  parsedBatchLines = p.lines || [];
  parsedBatchVoiceOverrides = p.voiceOverrides || {};
  parsedBatchPauseOverrides = p.pauseOverrides || {};
  batchRowData = p.rowData || {};

  if (p.model) {
    const mSel = document.getElementById('batchModelSelect');
    if (mSel) mSel.value = p.model;
  }
  if (p.pauseDuration) {
    const pSel = document.getElementById('batchPauseDuration');
    if (pSel) {
      pSel.value = p.pauseDuration;
      handleGlobalPauseChange(p.pauseDuration);
    }
  }

  const txt = document.getElementById('batchTextarea');
  if (txt) txt.value = parsedBatchLines.join('\n');
  renderBatchTable();
  updateBatchEstimation();
  closeBatchProjectModal();
  showToast('success', `Đã mở dự án "${p.name}" (${parsedBatchLines.length} dòng)!`);
}

function deleteBatchProject(projId) {
  let projects = getSavedBatchProjects();
  projects = projects.filter(item => item.id !== projId);
  localStorage.setItem('chatterbox_batch_projects', JSON.stringify(projects));
  renderBatchSavedProjects();
  showToast('info', 'Đã xóa dự án khỏi danh sách.');
}

function renderBatchSavedProjects() {
  const container = document.getElementById('batchSavedProjectsList');
  if (!container) return;
  const projects = getSavedBatchProjects();
  container.innerHTML = '';
  if (projects.length === 0) {
    container.innerHTML = '<div class="p-3 text-center text-slate-500 text-xs">Chưa có dự án nào được lưu.</div>';
    return;
  }

  projects.forEach(p => {
    const itemDiv = document.createElement('div');
    itemDiv.className = 'p-2 flex items-center justify-between hover:bg-[#18151E] transition-colors border-b border-[#2D2836] last:border-b-0';

    const infoDiv = document.createElement('div');
    infoDiv.className = 'min-w-0 pr-2';
    const nameDiv = document.createElement('div');
    nameDiv.className = 'font-bold text-white text-xs truncate max-w-[200px]';
    nameDiv.textContent = p.name || 'Dự án không tên';

    const metaDiv = document.createElement('div');
    metaDiv.className = 'text-[10px] text-slate-400 font-mono';
    const lineCount = (p.lines || []).length;
    const dateStr = p.created_at ? new Date(p.created_at).toLocaleString('vi-VN') : '';
    metaDiv.textContent = `${lineCount} dòng • ${dateStr}`;

    infoDiv.appendChild(nameDiv);
    infoDiv.appendChild(metaDiv);

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'flex items-center gap-1.5 shrink-0';

    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'px-2 py-1 rounded bg-[#231F2A] hover:bg-purple-600 text-purple-300 hover:text-white text-xs font-medium cursor-pointer';
    openBtn.textContent = 'Mở';
    openBtn.addEventListener('click', () => loadBatchProject(p.id));

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'p-1 rounded hover:bg-red-900/50 text-slate-400 hover:text-red-400 cursor-pointer';
    delBtn.title = 'Xóa';
    delBtn.innerHTML = '<span class="material-symbols-outlined text-[15px]">delete</span>';
    delBtn.addEventListener('click', () => deleteBatchProject(p.id));

    actionsDiv.appendChild(openBtn);
    actionsDiv.appendChild(delBtn);

    itemDiv.appendChild(infoDiv);
    itemDiv.appendChild(actionsDiv);
    container.appendChild(itemDiv);
  });
}
