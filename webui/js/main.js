/**
 * Chatterbox TTS Studio - Main App Bootstrap, System Health & Event Listeners
 */

async function checkSystemHealth() {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  const chip = document.getElementById('statusChip');
  const ramBadge = document.getElementById('ramBadge');
  const ramUsage = document.getElementById('ramUsage');
  const deviceBadge = document.getElementById('deviceBadge');
  const modelRecBadge = document.getElementById('modelRecBadge');

  try {
    const res = await fetch('/health');
    if (res.ok) {
      const data = await res.json();
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
      if (text) text.textContent = 'API Sẵn Sàng (Online)';
      if (chip) chip.className = 'flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-950/40 border border-emerald-500/30 text-emerald-400 font-medium';

      if (data.device && deviceBadge) {
        deviceBadge.textContent = data.device.toUpperCase();
      }

      if (data.memory) {
        if (ramBadge) ramBadge.classList.remove('hidden');
        if (ramUsage) ramUsage.textContent = `${data.memory.process_ram_mb} MB / ${data.memory.system_ram_gb} GB`;

        if (data.memory.system_ram_gb <= 16) {
          systemRecommendedModel = 'nano';
          if (modelRecBadge) {
            modelRecBadge.textContent = 'Khuyên dùng: NANO (RAM ≤ 16GB)';
            modelRecBadge.className = 'px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px]';
          }
          if (!userManuallyChangedModel) {
            const mSelect = document.getElementById('ttsModelSelect');
            if (mSelect) mSelect.value = 'nano';
            const bSelect = document.getElementById('batchModelSelect');
            if (bSelect) bSelect.value = 'nano';
            if (typeof handleModelChange === 'function') handleModelChange('nano');
          }
        } else {
          systemRecommendedModel = 'turbo';
          if (modelRecBadge) {
            modelRecBadge.textContent = 'Khuyên dùng: TURBO (RAM > 16GB)';
            modelRecBadge.className = 'px-2 py-0.5 rounded-full bg-purple-950/60 text-purple-300 border border-purple-800 text-[10px]';
          }
        }
      }
    } else {
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-yellow-400';
      if (text) text.textContent = 'API Đang khởi động...';
      if (chip) chip.className = 'flex items-center gap-2 px-3 py-1.5 rounded-full bg-yellow-950/40 border border-yellow-500/30 text-yellow-400 font-medium';
    }
  } catch (err) {
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-red-400';
    if (text) text.textContent = 'Mất kết nối API';
    if (chip) chip.className = 'flex items-center gap-2 px-3 py-1.5 rounded-full bg-red-950/40 border border-red-500/30 text-red-400 font-medium';
  }
}

// Audio element event handlers
audioElement.addEventListener('timeupdate', () => {
  if (audioElement.duration) {
    const cur = audioElement.currentTime;
    const dur = audioElement.duration;
    const timer = document.getElementById('playbackTimer');
    if (timer && typeof formatTime === 'function') {
      timer.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
    }
    if (typeof drawWaveform === 'function') {
      drawWaveform(cur / dur);
    }
  }
});

audioElement.addEventListener('ended', () => {
  isPlaying = false;
  const btn = document.getElementById('btnPlayPause');
  if (btn) btn.innerHTML = '<span class="material-symbols-outlined text-[24px]">play_arrow</span>';
  if (typeof drawWaveform === 'function') {
    drawWaveform(0);
  }
});

// Page leave confirmation when batch is running
window.addEventListener('beforeunload', (e) => {
  if (isBatchRunning) {
    e.preventDefault();
    e.returnValue = 'Tác vụ Batch đang chạy. Bạn có chắc muốn rời khỏi trang?';
    return e.returnValue;
  }
});

// Keyboard event shortcuts
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    if (typeof triggerSynthesis === 'function') triggerSynthesis();
  } else if (e.key === 'Escape') {
    if (typeof stopAudio === 'function') stopAudio();
    if (typeof closeShortcutsModal === 'function') closeShortcutsModal();
    if (typeof closeCreateCharacterModal === 'function') closeCreateCharacterModal();
    if (typeof closeModelCompareModal === 'function') closeModelCompareModal();
    if (typeof closeTrimmerModal === 'function') closeTrimmerModal();
    if (typeof closeBatchProjectModal === 'function') closeBatchProjectModal();
  } else if (e.key === 'F1') {
    e.preventDefault();
    if (typeof openShortcutsModal === 'function') openShortcutsModal();
  } else if (e.key === ' ' && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    if (typeof togglePlayPause === 'function') togglePlayPause();
  }
});

// Window resize handler
window.addEventListener('resize', () => {
  const placeholder = document.getElementById('waveformPlaceholder');
  if (placeholder && placeholder.classList.contains('hidden') && typeof drawWaveform === 'function') {
    drawWaveform(audioElement.duration ? (audioElement.currentTime / audioElement.duration) : 0);
  }
});

// Application bootstrap on DOM ready
window.addEventListener('DOMContentLoaded', () => {
  if (typeof initTheme === 'function') initTheme();
  checkSystemHealth();
  if (typeof refreshHistory === 'function') refreshHistory();
  if (typeof loadCharacters === 'function') loadCharacters();
  if (typeof fetchModelsStatus === 'function') fetchModelsStatus();
  if (typeof updateParamsSummaryBadge === 'function') updateParamsSummaryBadge();
  if (typeof initUrlRoute === 'function') initUrlRoute();

  // Setup Drag & Drop File Reading on all textareas
  if (typeof setupDragAndDropTextarea === 'function') {
    setupDragAndDropTextarea('promptInput', 'charCount');
    setupDragAndDropTextarea('batchTextarea');
    setupDragAndDropTextarea('mtlPromptInput', 'mtlCharCount');
  }
  if (typeof updateMtlCharCount === 'function') updateMtlCharCount();

  // Periodic health check every 15 seconds
  setInterval(checkSystemHealth, 15000);
});
