/**
 * Chatterbox TTS Studio - Voice Conversion (VC) Module
 */

function updateVcLabel(input, labelId) {
  if (input.files && input.files[0]) {
    const el = document.getElementById(labelId);
    if (el) el.textContent = `✓ ${input.files[0].name}`;
    showToast('success', `Đã chọn file "${input.files[0].name}"`);
  }
}

async function triggerVcConversion() {
  const btn = document.getElementById('vcGenerateBtn');
  const src = document.getElementById('vcSourceInput')?.files[0];
  const tgt = document.getElementById('vcTargetInput')?.files[0];
  if (!src || !tgt) return showToast('warning', 'Vui lòng chọn cả File Nguồn và File Mẫu Đích.');

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[22px]">progress_activity</span><span>Đang chuyển đổi âm sắc...</span>';
    btn.classList.add('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = true;
  }

  const formData = new FormData();
  formData.append('source_audio', src);
  formData.append('target_voice', tgt);

  try {
    const res = await fetch('/api/v1/voice-conversion', { method: 'POST', body: formData });
    if (res.ok) {
      const job = await res.json();
      showToast('info', 'Đã bắt đầu chuyển đổi âm sắc giọng!');
      if (typeof pollJob === 'function') {
        await pollJob(job.id, btn, 'Chuyển đổi âm sắc giọng nói', '<span class="material-symbols-outlined text-[22px]">sync</span>');
      }
    } else {
      showToast('error', 'Lỗi Voice Conversion.');
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[22px]">sync</span><span>Chuyển đổi âm sắc giọng nói</span>';
        btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
        btn.disabled = false;
      }
    }
  } catch (e) {
    showToast('error', 'Lỗi Voice Conversion: ' + e.message);
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[22px]">sync</span><span>Chuyển đổi âm sắc giọng nói</span>';
      btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
      btn.disabled = false;
    }
  }
}
