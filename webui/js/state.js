/**
 * Chatterbox TTS Studio - Global State & Router Module
 */

const audioElement = new Audio();
let currentAudioUrl = null;
let isPlaying = false;
let selectedMtlLanguage = 'en';
let uploadedRefFile = null;
let currentTab = 'tts';
let systemRecommendedModel = 'nano';
let userManuallyChangedModel = false;
let currentActiveJobId = null;

// Batch studio state
let parsedBatchLines = [];
let parsedBatchVoiceOverrides = {};
let parsedBatchPauseOverrides = {}; // { [idx]: pause_seconds }
let batchRowData = {}; // { [idx]: { jobId, audioUrl, status, error, duration, start_s, end_s } }
let isBatchRunning = false;
let cancelBatchRequested = false;
let currentBatchJobId = null;
let batchCurrentFilter = 'all';
let batchUndoBuffer = null;
let batchSearchIndex = -1;

// Characters cache
let allCharactersCache = [];

// A/B Comparison Slots
let slotA = null;
let slotB = null;

// MediaRecorder for live microphone recording
let mediaRecorder = null;
let audioChunks = [];
let isRecordingMic = false;

// URL Mapping for tabs
const TAB_URL_MAP = {
  'tts': 'tts-studio',
  'batch': 'batch-studio',
  'multilingual': 'multilingual-tts',
  'vc': 'voice-clone',
  'projects': 'projects-studio',
  'characters': 'characters',
  'history': 'history',
  'settings': 'settings',
  'mcp': 'connect-mcp'
};

const URL_TAB_MAP = {
  'tts-studio': 'tts',
  'tts': 'tts',
  'batch-studio': 'batch',
  'batch': 'batch',
  'multilingual-tts': 'multilingual',
  'multilingual': 'multilingual',
  'voice-clone': 'vc',
  'vc': 'vc',
  'projects-studio': 'projects',
  'projects': 'projects',
  'characters': 'characters',
  'characters-studio': 'characters',
  'history': 'history',
  'history-studio': 'history',
  'settings': 'settings',
  'settings-studio': 'settings',
  'connect-mcp': 'mcp',
  'mcp': 'mcp'
};

// ==================== HELPER UTILS ====================
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function setSlider(sliderId, valId, val) {
  const el = document.getElementById(sliderId);
  const valEl = document.getElementById(valId);
  if (el && valEl) {
    el.value = val;
    valEl.textContent = parseFloat(val).toFixed(2);
  }
}

// ==================== MATERIAL 3 TOAST POPUP SYSTEM ====================
function showToast(type, message, title = '') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast-enter p-3 rounded-xl shadow-m3-3 text-xs flex items-center justify-between gap-3 border pointer-events-auto transition-all max-w-sm';

  let icon = 'info';
  let borderClass = 'border-purple-500/50 bg-[#18151E] text-white';
  let iconColor = 'text-purple-400';

  if (type === 'error') {
    icon = 'error';
    borderClass = 'border-red-500/50 bg-[#1F1215] text-white';
    iconColor = 'text-red-400';
    title = title || 'Lỗi xử lý';
  } else if (type === 'success') {
    icon = 'check_circle';
    borderClass = 'border-emerald-500/50 bg-[#0F1B16] text-white';
    iconColor = 'text-emerald-400';
    title = title || 'Thành công';
  } else if (type === 'warning') {
    icon = 'warning';
    borderClass = 'border-amber-500/50 bg-[#1F1912] text-white';
    iconColor = 'text-amber-400';
    title = title || 'Cảnh báo';
  } else {
    title = title || 'Thông báo';
  }

  toast.className += ` ${borderClass}`;
  toast.innerHTML = `
    <span class="material-symbols-outlined text-[20px] ${iconColor} flex-shrink-0 mt-0.5">${icon}</span>
    <div class="flex-1">
      <div class="font-bold text-sm mb-0.5">${title}</div>
      <div class="text-slate-300 leading-relaxed">${message}</div>
    </div>
    <button onclick="this.parentElement.remove()" class="p-1 text-slate-400 hover:text-white cursor-pointer flex-shrink-0">
      <span class="material-symbols-outlined text-[16px]">close</span>
    </button>
  `;

  container.appendChild(toast);

  // Auto dismiss after 4 seconds
  setTimeout(() => {
    if (toast && toast.parentElement) {
      toast.classList.remove('toast-enter');
      toast.classList.add('toast-leave');
      setTimeout(() => toast.remove(), 250);
    }
  }, 4000);
}

// ==================== TAB SWITCHING & URL ROUTING ====================
function switchTab(tabId, updateUrl = true) {
  if (!tabId) return;
  currentTab = tabId;

  // Update Active Navigation Button Styling
  document.querySelectorAll('.nav-btn').forEach(btn => {
    if (btn.getAttribute('data-tab') === tabId) {
      btn.classList.add('active', 'bg-purple-600', 'text-white', 'font-bold', 'shadow-m3-1');
      btn.classList.remove('text-slate-400', 'hover:bg-[#231F2A]');
    } else {
      btn.classList.remove('active', 'bg-purple-600', 'text-white', 'font-bold', 'shadow-m3-1');
      btn.classList.add('text-slate-400', 'hover:bg-[#231F2A]');
    }
  });

  // Switch Active Section Panel
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.remove('active');
  });
  const targetPanel = document.getElementById(`panel-${tabId}`);
  if (targetPanel) targetPanel.classList.add('active');

  // Update URL Hash / Path
  if (updateUrl) {
    const slug = TAB_URL_MAP[tabId] || tabId;
    window.history.pushState({ tab: tabId }, '', `#${slug}`);
  }

  // Close Mobile Nav if open
  const navRail = document.getElementById('navRail');
  const overlay = document.getElementById('mobileOverlay');
  if (navRail && overlay) {
    navRail.classList.add('-translate-x-full');
    overlay.classList.add('hidden');
  }

  // Tab specific initializers
  if (tabId === 'projects' && typeof loadProjects === 'function') loadProjects();
  if (tabId === 'characters' && typeof loadCharacters === 'function') loadCharacters();
  if (tabId === 'history' && typeof refreshHistory === 'function') refreshHistory();
  if (tabId === 'settings' && typeof loadSettings === 'function') loadSettings();
}

function initUrlRoute() {
  let raw = window.location.hash.replace(/^#\/?/, '').trim();
  if (!raw) {
    const pathname = window.location.pathname.replace(/^\//, '').trim();
    if (pathname && pathname !== 'gui') raw = pathname;
  }
  if (raw && URL_TAB_MAP[raw]) {
    switchTab(URL_TAB_MAP[raw], false);
  } else {
    switchTab('tts', false);
  }
}

window.addEventListener('hashchange', () => {
  const raw = window.location.hash.replace(/^#\/?/, '').trim();
  if (raw && URL_TAB_MAP[raw]) {
    switchTab(URL_TAB_MAP[raw], false);
  }
});

window.addEventListener('popstate', (e) => {
  if (e.state && e.state.tab) {
    switchTab(e.state.tab, false);
  } else {
    initUrlRoute();
  }
});

function toggleMobileNav() {
  const navRail = document.getElementById('navRail');
  const overlay = document.getElementById('mobileOverlay');
  if (!navRail || !overlay) return;
  const isOpen = !navRail.classList.contains('-translate-x-full');
  if (isOpen) {
    navRail.classList.add('-translate-x-full');
    overlay.classList.add('hidden');
  } else {
    navRail.classList.remove('-translate-x-full');
    overlay.classList.remove('hidden');
  }
}

// ==================== THEME & SHORTCUTS ====================
function updateThemeUI(isDark) {
  const icon = document.getElementById('themeIcon');
  const toggleBtn = document.getElementById('themeToggle');
  if (isDark) {
    document.documentElement.classList.add('dark');
    if (icon) icon.textContent = 'light_mode';
    if (toggleBtn) toggleBtn.title = 'Chuyển sang chế độ Sáng';
  } else {
    document.documentElement.classList.remove('dark');
    if (icon) icon.textContent = 'dark_mode';
    if (toggleBtn) toggleBtn.title = 'Chuyển sang chế độ Tối';
  }
}

function toggleTheme() {
  const html = document.documentElement;
  const willBeDark = !html.classList.contains('dark');
  try {
    localStorage.setItem('chatterbox_theme', willBeDark ? 'dark' : 'light');
  } catch (e) {}
  updateThemeUI(willBeDark);
  showToast('info', willBeDark ? 'Đã chuyển sang chế độ Tối (Dark Mode)' : 'Đã chuyển sang chế độ Sáng (Light Mode)');
}

function initTheme() {
  let isDark = true;
  try {
    const saved = localStorage.getItem('chatterbox_theme');
    if (saved === 'light') {
      isDark = false;
    } else if (saved === 'dark') {
      isDark = true;
    } else {
      isDark = true;
    }
  } catch (e) {}
  updateThemeUI(isDark);
}

function openShortcutsModal() { document.getElementById('shortcutsModal')?.classList.remove('hidden'); }
function closeShortcutsModal() { document.getElementById('shortcutsModal')?.classList.add('hidden'); }
