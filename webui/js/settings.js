/**
 * Chatterbox TTS Studio - Settings, Models Registry & Disk Management Module
 */

async function loadSettings() {
  try {
    const res = await fetch('/api/v1/settings');
    if (res.ok) {
      const data = await res.json();
      const s = data.settings || {};
      if (s.export_dir) document.getElementById('settingExportDir').value = s.export_dir;
      if (s.model_cache_dir) document.getElementById('settingModelDir').value = s.model_cache_dir;
      if (s.device) document.getElementById('settingDevice').value = s.device;
      if (s.cpu_threads_limit) document.getElementById('settingCpuThreads').value = s.cpu_threads_limit;
      if (s.max_chunk_chars) document.getElementById('settingMaxChunk').value = s.max_chunk_chars;
      if (s.auto_unload_models !== undefined) document.getElementById('settingAutoUnload').checked = s.auto_unload_models;
    }
  } catch (e) {}
}

async function saveAllSettings() {
  const payload = {
    export_dir: document.getElementById('settingExportDir')?.value,
    model_cache_dir: document.getElementById('settingModelDir')?.value,
    device: document.getElementById('settingDevice')?.value,
    cpu_threads_limit: parseInt(document.getElementById('settingCpuThreads')?.value) || 4,
    max_chunk_chars: parseInt(document.getElementById('settingMaxChunk')?.value) || 4000,
    auto_unload_models: document.getElementById('settingAutoUnload')?.checked ?? false,
  };

  try {
    const res = await fetch('/api/v1/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      showToast('success', 'Đã lưu toàn bộ cấu hình hệ thống thành công!');
    }
  } catch (e) {
    showToast('error', 'Lỗi khi lưu cài đặt: ' + e.message);
  }
}

async function cleanProjectTmpFiles() {
  if (!confirm("Bạn có chắc muốn dọn sạch các file audio tạm trong thư mục tmp?")) return;
  try {
    const res = await fetch('/api/v1/system/clean-tmp', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      const mb = (data.freed_bytes / (1024 * 1024)).toFixed(2);
      showToast('success', `Đã dọn sạch ${data.deleted_files} file tạm (${mb} MB) trong thư mục tmp!`);
    }
  } catch (e) {
    showToast('error', 'Lỗi khi dọn dẹp file tạm: ' + e.message);
  }
}

async function preloadModel(modelName) {
  const statusEl = document.getElementById(`modelStatus-${modelName}`);
  const oldHtml = statusEl ? statusEl.innerHTML : '';
  if (statusEl) statusEl.innerHTML = '<span class="text-purple-400 animate-pulse">⏳ Đang nạp...</span>';
  try {
    const res = await fetch(`/api/v1/models/${modelName}/load`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      if (statusEl) statusEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400 inline-block mr-1"></span> Đã nạp';
      showToast('success', data.message || `Mô hình ${modelName} đã được nạp sẵn sàng!`);
    } else {
      if (statusEl) statusEl.innerHTML = oldHtml || '<span class="text-slate-400">Chưa nạp</span>';
      showToast('error', data.detail || `Lỗi khi nạp mô hình ${modelName}`);
    }
    fetchModelsStatus();
  } catch (e) {
    if (statusEl) statusEl.innerHTML = oldHtml || '<span class="text-slate-400">Chưa nạp</span>';
    showToast('error', 'Lỗi nạp model: ' + e.message);
    fetchModelsStatus();
  }
}

async function unloadModel(modelName) {
  const statusEl = document.getElementById(`modelStatus-${modelName}`);
  try {
    const res = await fetch(`/api/v1/models/${modelName}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      if (statusEl) statusEl.innerHTML = '<span class="text-slate-400">Chưa nạp</span>';
      showToast('info', data.message || `Đã giải phóng mô hình ${modelName} khỏi bộ nhớ.`);
    } else {
      showToast('error', data.detail || `Lỗi khi giải phóng mô hình ${modelName}`);
    }
    fetchModelsStatus();
  } catch (e) {
    showToast('error', 'Lỗi giải phóng model: ' + e.message);
    fetchModelsStatus();
  }
}

async function deleteModelFromDisk(modelName) {
  const label = modelName === 'nano' ? 'Chatterbox Nano (110M)'
    : modelName === 'turbo' ? 'Chatterbox Turbo (350M)'
    : modelName === 'standard' ? 'Chatterbox Standard (500M)'
    : modelName === 'multilingual' ? 'Chatterbox Multilingual (500M)'
    : modelName;

  if (!confirm(`⚠️ XÁC NHẬN XÓA CHECKPOINT KHỎI Ổ ĐĨA:\n\nBạn có chắc chắn muốn xóa toàn bộ file checkpoint của "${label}" khỏi thư mục models/?\n\n• Thao tác này sẽ giải phóng dung lượng ổ đĩa.\n• Bạn có thể tải lại bất cứ lúc nào qua nút "Nạp" hoặc lệnh HF_HUB_OFFLINE=0.`)) {
    return;
  }

  const diskEl = document.getElementById(`modelDisk-${modelName}`);
  if (diskEl) diskEl.innerHTML = '<span class="text-amber-400 animate-pulse">⏳ Đang xóa file...</span>';

  try {
    const res = await fetch(`/api/v1/models/${modelName}/disk`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast('success', data.message || `Đã xóa checkpoint của ${label} khỏi ổ đĩa!`);
      fetchModelsStatus();
      if (typeof checkSystemHealth === 'function') checkSystemHealth();
    } else {
      showToast('error', data.detail || `Lỗi khi xóa checkpoint của ${label}`);
      fetchModelsStatus();
    }
  } catch (e) {
    showToast('error', 'Lỗi khi xóa checkpoint: ' + e.message);
    fetchModelsStatus();
  }
}

async function fetchModelsStatus() {
  try {
    const res = await fetch('/api/v1/models');
    if (!res.ok) return;
    const data = await res.json();
    if (!data.models) return;

    data.models.forEach(m => {
      const statusEl = document.getElementById(`modelStatus-${m.name}`);
      const diskEl = document.getElementById(`modelDisk-${m.name}`);
      const delBtn = document.getElementById(`btnDeleteDisk-${m.name}`);

      if (statusEl) {
        if (m.loaded_in_memory) {
          statusEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400 inline-block mr-1"></span> Đã nạp RAM';
          statusEl.className = 'text-[11px] text-emerald-400 flex items-center gap-1 font-semibold';
        } else {
          statusEl.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-slate-500 inline-block mr-1"></span> Chưa nạp RAM';
          statusEl.className = 'text-[11px] text-slate-400 flex items-center gap-1';
        }
      }

      if (diskEl) {
        if (m.cached_on_disk && m.size_mb > 0) {
          diskEl.innerHTML = `<span class="text-emerald-400 font-mono">💾 ${m.size_mb} MB</span> trên ổ đĩa`;
          if (delBtn) delBtn.disabled = false;
        } else if (m.cached_on_disk) {
          diskEl.innerHTML = `<span class="text-emerald-400 font-mono">💾 Đã có</span> trên ổ đĩa`;
          if (delBtn) delBtn.disabled = false;
        } else {
          diskEl.innerHTML = `<span class="text-amber-400 font-mono">❌ Chưa tải</span> về ổ đĩa`;
          if (delBtn) delBtn.disabled = true;
        }
      }
    });
  } catch (e) {
    console.warn('Lỗi lấy thông tin model:', e);
  }
}

function preloadCurrentModel() {
  const m = document.getElementById('ttsModelSelect')?.value;
  if (m) preloadModel(m);
}

function openModelCompareModal() { document.getElementById('modelCompareModal')?.classList.remove('hidden'); }
function closeModelCompareModal() { document.getElementById('modelCompareModal')?.classList.add('hidden'); }
