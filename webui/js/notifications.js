/**
 * Chatterbox Studio - Real-time Event Log & Notifications Controller (Long Polling & Persistent State)
 */

const NOTIF_STORAGE_KEYS = {
  NOTIFS: 'chatterbox_event_notifications',
  LAST_ID: 'chatterbox_last_event_id',
  CLEARED_ID: 'chatterbox_cleared_event_id',
  DISMISSED_IDS: 'chatterbox_dismissed_event_ids',
  BOOT_ID: 'chatterbox_server_boot_id',
};

let lastNotificationEventId = 0;
let eventNotifications = [];
let isEventPollingActive = false;
let unreadNotificationCount = 0;

function getDismissedIds() {
  try {
    const raw = localStorage.getItem(NOTIF_STORAGE_KEYS.DISMISSED_IDS);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveNotificationsState() {
  try {
    localStorage.setItem(NOTIF_STORAGE_KEYS.NOTIFS, JSON.stringify(eventNotifications.slice(0, 50)));
    localStorage.setItem(NOTIF_STORAGE_KEYS.LAST_ID, String(lastNotificationEventId));
  } catch (e) {
    console.warn('Failed to save notifications state:', e);
  }
}

function loadNotificationsState() {
  try {
    const savedClearedId = parseInt(localStorage.getItem(NOTIF_STORAGE_KEYS.CLEARED_ID) || '0', 10);
    const savedLastId = parseInt(localStorage.getItem(NOTIF_STORAGE_KEYS.LAST_ID) || '0', 10);
    lastNotificationEventId = Math.max(savedLastId, savedClearedId);

    const savedNotifs = localStorage.getItem(NOTIF_STORAGE_KEYS.NOTIFS);
    if (savedNotifs) {
      const parsed = JSON.parse(savedNotifs);
      const dismissed = getDismissedIds();
      eventNotifications = (Array.isArray(parsed) ? parsed : []).filter(ev => {
        if (!ev) return false;
        if (savedClearedId && ev.id && ev.id <= savedClearedId) return false;
        if (ev.id && dismissed.includes(ev.id)) return false;
        return true;
      });
    } else {
      eventNotifications = [];
    }
  } catch (e) {
    console.warn('Failed to load notifications state:', e);
    eventNotifications = [];
    lastNotificationEventId = 0;
  }
  // On page load, existing notifications from history are not marked as unread
  unreadNotificationCount = 0;
}

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
  const bellIcon = document.getElementById('notificationsBellIcon');
  const headerIcon = document.getElementById('notifHeaderIcon');

  if (totalBadge) totalBadge.textContent = eventNotifications.length;

  if (unreadNotificationCount > 0) {
    if (badge) badge.classList.remove('hidden');
    if (countBadge) {
      countBadge.classList.remove('hidden');
      countBadge.textContent = unreadNotificationCount > 99 ? '99+' : unreadNotificationCount;
    }
    if (bellIcon) {
      bellIcon.textContent = 'notifications_active';
      bellIcon.className = 'material-symbols-outlined text-[18px] text-purple-400';
    }
  } else {
    if (badge) badge.classList.add('hidden');
    if (countBadge) countBadge.classList.add('hidden');
    if (bellIcon) {
      bellIcon.textContent = 'notifications';
      bellIcon.className = 'material-symbols-outlined text-[18px] text-slate-300';
    }
  }

  if (headerIcon) {
    if (eventNotifications.length > 0) {
      headerIcon.textContent = 'notifications_active';
      headerIcon.className = 'material-symbols-outlined text-purple-400 text-[18px]';
    } else {
      headerIcon.textContent = 'notifications_none';
      headerIcon.className = 'material-symbols-outlined text-slate-400 text-[18px]';
    }
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

async function clearAllNotifications() {
  // 1. Record cleared event ID to prevent old events reappearing
  const clearedId = lastNotificationEventId;
  localStorage.setItem(NOTIF_STORAGE_KEYS.CLEARED_ID, String(clearedId));
  localStorage.setItem(NOTIF_STORAGE_KEYS.LAST_ID, String(clearedId));
  localStorage.setItem(NOTIF_STORAGE_KEYS.NOTIFS, '[]');
  localStorage.removeItem(NOTIF_STORAGE_KEYS.DISMISSED_IDS);

  // 2. Clear UI state immediately
  eventNotifications = [];
  unreadNotificationCount = 0;
  updateNotificationBadge();
  renderNotificationsList();

  // 3. Clear server-side event buffer
  try {
    const res = await fetch('/api/v1/events', { method: 'DELETE' });
    if (res.ok) {
      const data = await res.json();
      if (data.server_boot_id) {
        localStorage.setItem(NOTIF_STORAGE_KEYS.BOOT_ID, data.server_boot_id);
      }
      lastNotificationEventId = 0;
      localStorage.setItem(NOTIF_STORAGE_KEYS.LAST_ID, '0');
      localStorage.setItem(NOTIF_STORAGE_KEYS.CLEARED_ID, '0');
    }
  } catch (err) {
    console.warn('Failed to clear backend events via DELETE:', err);
  }
}

function dismissNotification(evId, event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }

  // Remove from current notification list
  eventNotifications = eventNotifications.filter(e => (e.id !== evId && e._tempId !== evId));

  // Record in dismissed IDs
  if (evId !== undefined && evId !== null) {
    try {
      const dismissed = getDismissedIds();
      if (!dismissed.includes(evId)) {
        dismissed.push(evId);
        if (dismissed.length > 200) dismissed.splice(0, dismissed.length - 200);
        localStorage.setItem(NOTIF_STORAGE_KEYS.DISMISSED_IDS, JSON.stringify(dismissed));
      }
    } catch (e) {}
  }

  saveNotificationsState();
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
    const itemId = ev.id !== undefined ? ev.id : (ev._tempId || idx);

    return `
      <div class="p-2.5 hover:bg-[#231F2A] transition-colors rounded-lg flex items-start gap-2.5 group">
        <div class="w-7 h-7 rounded-lg ${meta.bg} border flex items-center justify-center shrink-0 mt-0.5">
          <span class="material-symbols-outlined text-[16px] ${meta.color}">${meta.icon}</span>
        </div>
        <div class="flex-1 min-w-0 space-y-0.5">
          <div class="flex items-center justify-between gap-1">
            <span class="font-bold text-white text-xs truncate">${title}</span>
            <div class="flex items-center gap-1.5 shrink-0">
              <span class="text-[10px] text-slate-400 font-mono">${timeStr}</span>
              <button onclick="dismissNotification(${itemId}, event)" class="p-0.5 text-slate-500 hover:text-rose-400 rounded hover:bg-[#18151E] transition-colors cursor-pointer" title="Xóa thông báo này">
                <span class="material-symbols-outlined text-[14px]">close</span>
              </button>
            </div>
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

        // Handle server reboot or buffer sequence reset
        if (data.server_boot_id) {
          const currentBootId = localStorage.getItem(NOTIF_STORAGE_KEYS.BOOT_ID);
          if (currentBootId && currentBootId !== data.server_boot_id) {
            localStorage.setItem(NOTIF_STORAGE_KEYS.BOOT_ID, data.server_boot_id);
            if (lastNotificationEventId > (data.last_event_id || 0)) {
              lastNotificationEventId = data.last_event_id || 0;
            }
          } else if (!currentBootId) {
            localStorage.setItem(NOTIF_STORAGE_KEYS.BOOT_ID, data.server_boot_id);
          }
        }

        const events = data.events || [];
        if (events.length > 0) {
          const savedClearedId = parseInt(localStorage.getItem(NOTIF_STORAGE_KEYS.CLEARED_ID) || '0', 10);
          const dismissed = getDismissedIds();

          let hasNew = false;
          for (const ev of events) {
            // Skip events that were already cleared or dismissed
            if (savedClearedId && ev.id && ev.id <= savedClearedId) continue;
            if (ev.id && dismissed.includes(ev.id)) continue;
            if (eventNotifications.some(e => e.id && e.id === ev.id)) continue;

            eventNotifications.unshift(ev);
            unreadNotificationCount++;
            hasNew = true;

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

          lastNotificationEventId = data.last_event_id || lastNotificationEventId;

          // Keep max 50 notifications in memory
          if (eventNotifications.length > 50) {
            eventNotifications = eventNotifications.slice(0, 50);
          }

          if (hasNew) {
            saveNotificationsState();
            updateNotificationBadge();
            renderNotificationsList();
          }
        } else {
          if (typeof data.last_event_id === 'number') {
            lastNotificationEventId = data.last_event_id;
          }
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
  loadNotificationsState();
  updateNotificationBadge();
  renderNotificationsList();
  startEventLongPolling();
});
