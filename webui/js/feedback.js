/**
 * Chatterbox TTS Studio - Feedback / Known Issues Tab
 */

const FEEDBACK_STATUS_STYLE = {
  open: { label: 'Open', cls: 'bg-red-600/20 text-red-300 border-red-500/30' },
  in_progress: { label: 'In Progress', cls: 'bg-amber-600/20 text-amber-300 border-amber-500/30' },
  fixed: { label: 'Fixed', cls: 'bg-emerald-600/20 text-emerald-300 border-emerald-500/30' },
  wontfix: { label: "Won't Fix", cls: 'bg-slate-600/20 text-slate-300 border-slate-500/30' },
};

const FEEDBACK_SEVERITY_STYLE = {
  high: 'text-red-300',
  medium: 'text-amber-300',
  low: 'text-slate-400',
};

function renderFeedbackIssue(issue) {
  const statusInfo = FEEDBACK_STATUS_STYLE[issue.status] || FEEDBACK_STATUS_STYLE.open;
  const severityCls = FEEDBACK_SEVERITY_STYLE[issue.severity] || 'text-slate-400';

  const filesHtml = (issue.files || [])
    .map((f) => `<code class="bg-[#1C1A22] px-1.5 py-0.5 rounded text-purple-300 text-[10px]">${escapeHtml(f)}</code>`)
    .join(' ');

  const updatesHtml = (issue.updates || [])
    .map((u) => `
      <li class="text-[10px] text-slate-400">
        <span class="text-slate-500">${escapeHtml(u.date || '')}</span>
        ${u.by ? `· <span class="text-slate-300">${escapeHtml(u.by)}</span>` : ''}
        — ${escapeHtml(u.note || '')}
      </li>`)
    .join('');

  return `
    <div class="p-3.5 rounded-lg bg-[#0E0C12] border border-[#3F3A46] space-y-2">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="font-mono text-[10px] text-slate-500">${escapeHtml(issue.id || '')}</span>
          <span class="px-2 py-0.5 rounded-full border text-[9px] font-bold ${statusInfo.cls}">${statusInfo.label}</span>
          ${issue.severity ? `<span class="text-[9px] font-bold uppercase ${severityCls}">${escapeHtml(issue.severity)}</span>` : ''}
          ${issue.area ? `<span class="text-[9px] text-slate-500">${escapeHtml(issue.area)}</span>` : ''}
        </div>
        <span class="text-[9px] text-slate-500">${escapeHtml(issue.reported_by || '')} · ${escapeHtml(issue.reported_at || '')}</span>
      </div>

      <h3 class="text-xs font-bold text-white">${escapeHtml(issue.title || '')}</h3>
      <p class="text-[11px] text-slate-300 leading-relaxed">${escapeHtml(issue.summary || '')}</p>

      ${issue.workaround ? `
        <p class="text-[11px] text-slate-400"><span class="font-bold text-slate-300">Workaround:</span> ${escapeHtml(issue.workaround)}</p>
      ` : ''}

      ${filesHtml ? `<div class="flex flex-wrap gap-1.5 pt-1">${filesHtml}</div>` : ''}

      ${updatesHtml ? `
        <div class="pt-1.5 mt-1.5 border-t border-[#3F3A46]/60">
          <p class="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">Tiến trình xử lý</p>
          <ul class="space-y-0.5">${updatesHtml}</ul>
        </div>
      ` : ''}
    </div>`;
}

async function loadFeedback() {
  const container = document.getElementById('feedbackList');
  if (!container) return;
  container.innerHTML = '<p class="text-xs text-slate-500">Đang tải danh sách lỗi...</p>';

  try {
    const res = await fetch('/api/v1/feedback');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const issues = data.issues || [];

    if (issues.length === 0) {
      container.innerHTML = '<p class="text-xs text-slate-500">Chưa có lỗi nào được ghi nhận. 🎉</p>';
      return;
    }

    const statusOrder = { open: 0, in_progress: 1, fixed: 2, wontfix: 3 };
    issues.sort((a, b) => (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9));

    container.innerHTML = issues.map(renderFeedbackIssue).join('');
  } catch (err) {
    container.innerHTML = `<p class="text-xs text-red-400">Không tải được danh sách lỗi: ${escapeHtml(err.message)}</p>`;
  }
}
