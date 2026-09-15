/**
 * Chatterbox TTS Studio - Main App Bootstrap, System Health & Event Listeners
 */

async function checkSystemHealth() {
  // Targets the header's hardware chip (#deviceChip > #deviceIndicator +
  // #deviceStatus). All fields read from /health are already normalized
  // cross-platform by utils/platform_tools.py (device: 'cpu'|'cuda'|'mps',
  // total_ram_gb via GlobalMemoryStatusEx/sysctl/proc-meminfo per OS) --
  // this function must not re-derive or assume anything OS-specific itself.
  const indicator = document.getElementById('deviceIndicator');
  const status = document.getElementById('deviceStatus');
  const chip = document.getElementById('deviceChip');

  try {
    const res = await fetch('/health');
    if (res.ok) {
      const data = await res.json();
      if (indicator) indicator.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse';
      if (chip) chip.className = 'flex items-center gap-1 px-2.5 py-1 rounded-full bg-[#231F2A] border border-[#3F3A46] text-xs font-mono text-emerald-400';

      if (status) {
        const deviceLabel = (data.device || 'cpu').toUpperCase();
        const threadsLabel = data.device === 'cpu' && data.cpu_threads ? ` · ${data.cpu_threads} luồng` : '';
        status.textContent = `${deviceLabel}${threadsLabel}`;
      }
      if (chip) {
        const ramLabel = typeof data.total_ram_gb === 'number' ? `RAM: ${data.total_ram_gb} GB` : '';
        chip.title = [ramLabel, data.recommendation_reason].filter(Boolean).join(' — ');
      }

      // Backend already picks the resource-appropriate model per platform
      // (RAM, and GPU VRAM when device is cuda) -- just follow it here
      // instead of re-deriving a recommendation from raw fields.
      if (data.recommended_model) {
        systemRecommendedModel = data.recommended_model;
        if (!userManuallyChangedModel) {
          const mSelect = document.getElementById('ttsModelSelect');
          if (mSelect) mSelect.value = systemRecommendedModel;
          const bSelect = document.getElementById('batchModelSelect');
          if (bSelect) bSelect.value = systemRecommendedModel;
          if (typeof handleModelChange === 'function') handleModelChange(systemRecommendedModel);
        }
      }
    } else {
      if (indicator) indicator.className = 'w-1.5 h-1.5 rounded-full bg-amber-400';
      if (status) status.textContent = 'API đang khởi động...';
      if (chip) chip.className = 'flex items-center gap-1 px-2.5 py-1 rounded-full bg-amber-950/40 border border-amber-500/30 text-xs font-mono text-amber-400';
    }
  } catch (err) {
    if (indicator) indicator.className = 'w-1.5 h-1.5 rounded-full bg-red-400';
    if (status) status.textContent = 'Mất kết nối API';
    if (chip) chip.className = 'flex items-center gap-1 px-2.5 py-1 rounded-full bg-red-950/40 border border-red-500/30 text-xs font-mono text-red-400';
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
