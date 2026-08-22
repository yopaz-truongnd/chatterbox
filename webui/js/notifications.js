/**
 * Chatterbox Studio - Real-time Event Log & Notifications Controller (Long Polling)
 */

let lastNotificationEventId = 0;
let eventNotifications = [];
let isEventPollingActive = false;
let unreadNotificationCount = 0;

function getEventIconAndColor(type) {
  switch (type) {
    case 'questions_required':
      return { icon: 'help_outline', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30' };
    case 'requirements_ready':
      return { icon: 'rule', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30' };
    case 'script_ready':
      return { icon: 'description', color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/30' };
    case 'approved':
      return { icon: 'verified', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' };
    case 'render_started':
      return { icon: 'play_circle', color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/30' };
    case 'render_progress':
      return { icon: 'hourglass_top', color: 'text-purple-300', bg: 'bg-purple-500/10 border-purple-500/30' };
    case 'evaluating':
      return { icon: 'equalizer', color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/30' };
    case 'auto_fixing':
      return { icon: 'auto_fix_high', color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/30' };
    case 'completed':
      return { icon: 'task_alt', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' };
    case 'failed':
      return { icon: 'error_outline', color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/30' };
    default:
      return { icon: 'notifications', color: 'text-slate-300', bg: 'bg-slate-800 border-slate-700' };
  }
}

function getEventTitle(ev) {
  const type = ev.type || 'unknown';
  switch (type) {
    case 'questions_required':
      return 'Cần bổ sung thông tin dự án';
    case 'requirements_ready':
      return 'Yêu cầu dự án đã sẵn sàng';
    case 'script_ready':
      return 'Kịch bản tiếng Anh đã soạn xong';
    case 'approved':
      return 'Dự án đã được duyệt';
    case 'render_started':
      return 'Bắt đầu tổng hợp âm thanh';
    case 'render_progress':
      return `Tiến trình Render: ${ev.progress || 0}%`;
    case 'evaluating':
      return 'Đang phân tích tín hiệu âm thanh';
    case 'auto_fixing':
      return 'Tự động tối ưu WAV (Trim & Normalize)';
    case 'completed':
      return 'Sản xuất âm thanh hoàn tất!';
    case 'failed':
      return 'Tác vụ gặp lỗi';
    default:
      return `Sự kiện: ${type}`;
  }
}

function updateNotificationBadge() {
  const badge = document.getElementById('notificationsBadge');
  const countBadge = document.getElementById('notificationsCount');
  const totalBadge = document.getElementById('notifTotalBadge');

  if (totalBadge) totalBadge.textContent = eventNotifications.length;

  if (unreadNotificationCount > 0) {
    if (badge) badge.classList.remove('hidden');
    if (countBadge) {
      countBadge.classList.remove('hidden');
      countBadge.textContent = unreadNotificationCount > 99 ? '99+' : unreadNotificationCount;
    }
  } else {
    if (badge) badge.classList.add('hidden');
    if (countBadge) countBadge.classList.add('hidden');
  }
}

function toggleNotificationsPanel() {
  const panel = document.getElementById('notificationsPanel');
  if (!panel) return;

  const isHidden = panel.classList.contains('hidden');
  if (isHidden) {
    panel.classList.remove('hidden');
    unreadNotificationCount = 0;
    updateNotificationBadge();
  } else {
    panel.classList.add('hidden');
  }
}

function clearAllNotifications() {
  eventNotifications = [];
  unreadNotificationCount = 0;
  updateNotificationBadge();
  renderNotificationsList();
}

function renderNotificationsList() {
  const container = document.getElementById('notificationsList');
  if (!container) return;

  if (eventNotifications.length === 0) {
    container.innerHTML = `
      <div id="notificationsEmpty" class="py-8 text-center text-slate-500 space-y-1">
        <span class="material-symbols-outlined text-[28px] text-slate-600">notifications_paused</span>
        <p class="text-xs">Chưa có thông báo sự kiện nào</p>
      </div>
    `;
    return;
  }

  container.innerHTML = eventNotifications.map((ev, idx) => {
    const meta = getEventIconAndColor(ev.type);
    const title = getEventTitle(ev);
    const timeStr = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '';
    const projId = ev.project_id ? `<span class="font-mono text-[10px] text-purple-300 bg-purple-950/60 px-1 rounded">${ev.project_id}</span>` : '';
    const audioUrl = ev.data && ev.data.audio_url ? ev.data.audio_url : null;

    return `
      <div class="p-2.5 hover:bg-[#231F2A] transition-colors rounded-lg flex items-start gap-2.5">
        <div class="w-7 h-7 rounded-lg ${meta.bg} border flex items-center justify-center shrink-0 mt-0.5">
          <span class="material-symbols-outlined text-[16px] ${meta.color}">${meta.icon}</span>
        </div>
        <div class="flex-1 min-w-0 space-y-0.5">
          <div class="flex items-center justify-between gap-1">
            <span class="font-bold text-white text-xs truncate">${title}</span>
            <span class="text-[10px] text-slate-400 shrink-0 font-mono">${timeStr}</span>
          </div>
          <div class="flex items-center gap-1.5 text-[11px] text-slate-400">
            ${projId}
            ${ev.status ? `<span class="capitalize text-slate-300">Trạng thái: <b>${ev.status}</b></span>` : ''}
          </div>
          ${ev.data && ev.data.error ? `<p class="text-xs text-rose-400">${ev.data.error}</p>` : ''}
          ${audioUrl ? `
            <div class="pt-1 flex items-center gap-2">
              <button onclick="playNotificationAudio('${audioUrl}')" class="px-2 py-0.5 rounded bg-purple-600 hover:bg-purple-700 text-white font-bold text-[10px] flex items-center gap-1">
                <span class="material-symbols-outlined text-[13px]">play_arrow</span>
                <span>Nghe Audio</span>
              </button>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function playNotificationAudio(url) {
  if (typeof playAudioDirectly === 'function') {
    playAudioDirectly(url);
  } else {
    const audio = new Audio(url);
    audio.play();
  }
}

async function startEventLongPolling() {
  if (isEventPollingActive) return;
  isEventPollingActive = true;

  while (isEventPollingActive) {
    try {
      const res = await fetch(`/api/v1/events?after_id=${lastNotificationEventId}&wait=20`);
      if (res.ok) {
        const data = await res.json();
        const events = data.events || [];
        if (events.length > 0) {
          lastNotificationEventId = data.last_event_id || lastNotificationEventId;

          for (const ev of events) {
            eventNotifications.unshift(ev);
            unreadNotificationCount++;

            // Trigger notification toast for critical events
            if (['completed', 'script_ready', 'approved', 'failed'].includes(ev.type)) {
              if (typeof showToast === 'function') {
                const title = getEventTitle(ev);
                showToast(title, ev.type === 'failed' ? 'error' : 'success');
              }
            }

            // If project tab is active and project completed, refresh projects
            if (ev.project_id && typeof loadProjectsList === 'function') {
              loadProjectsList();
            }
          }

          // Keep max 50 notifications in memory
          if (eventNotifications.length > 50) {
            eventNotifications = eventNotifications.slice(0, 50);
          }

          updateNotificationBadge();
          renderNotificationsList();
        }
      } else {
        await new Promise(r => setTimeout(r, 3000));
      }
    } catch (err) {
      await new Promise(r => setTimeout(r, 4000));
    }
  }
}

// Close notifications dropdown when clicking outside
document.addEventListener('click', (e) => {
  const panel = document.getElementById('notificationsPanel');
  const toggleBtn = document.getElementById('notificationsToggle');
  if (panel && !panel.classList.contains('hidden')) {
    if (!panel.contains(e.target) && !toggleBtn.contains(e.target)) {
      panel.classList.add('hidden');
    }
  }
});

// Initialize on DOM Ready
window.addEventListener('DOMContentLoaded', () => {
  renderNotificationsList();
  startEventLongPolling();
});
