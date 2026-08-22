/**
 * Chatterbox TTS Studio - Audio History & Logs Module
 */

async function refreshHistory() {
  const miniList = document.getElementById('miniHistoryList');
  const fullTbody = document.getElementById('fullHistoryTableBody');

  try {
    const res = await fetch('/api/v1/jobs');
    if (res.ok) {
      const data = await res.json();
      const jobs = data.jobs || [];

      if (jobs.length === 0) {
        if (miniList) miniList.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Chưa có bản ghi âm nào</div>';
        if (fullTbody) fullTbody.innerHTML = '<tr><td colspan="6" class="p-6 text-center text-slate-500">Chưa có bản ghi âm nào trong lịch sử</td></tr>';
        return;
      }

      if (miniList) {
        miniList.innerHTML = jobs.slice(0, 6).map(j => `
          <div class="flex items-center justify-between p-2.5 rounded-xl bg-[#0E0C12] hover:bg-[#231F2A] border border-[#3F3A46]/50 transition-colors group">
            <div class="flex items-center gap-3 overflow-hidden">
              <button onclick="playAudioUrl('${j.audio_url}', '${escapeHtml(j.params?.text || 'Audio')}')" class="w-8 h-8 rounded-full bg-[#231F2A] group-hover:bg-purple-600 group-hover:text-white text-purple-400 flex items-center justify-center transition-colors flex-shrink-0 cursor-pointer" ${!j.audio_url ? 'disabled' : ''}>
                <span class="material-symbols-outlined text-[18px]">play_arrow</span>
              </button>
              <div class="truncate">
                <div class="text-xs font-medium text-white truncate">${escapeHtml(j.params?.text || j.type)}</div>
                <div class="text-[10px] font-mono text-slate-400">${j.status === 'completed' ? '✓ Đã tạo' : j.status}</div>
              </div>
            </div>
            ${j.audio_url ? `
              <a href="${j.audio_url}" download="audio-${j.id}.wav" class="p-1 rounded-full text-slate-400 hover:text-purple-400 opacity-0 group-hover:opacity-100 transition-opacity">
                <span class="material-symbols-outlined text-[18px]">download</span>
              </a>
            ` : ''}
          </div>
        `).join('');
      }

      if (fullTbody) {
        fullTbody.innerHTML = jobs.map(j => `
          <tr class="hover:bg-[#18151E] transition-colors">
            <td class="p-3.5">
              <button onclick="playAudioUrl('${j.audio_url}', '${escapeHtml(j.params?.text || 'Audio')}')" class="w-8 h-8 rounded-full bg-[#231F2A] hover:bg-purple-600 text-purple-400 hover:text-white flex items-center justify-center cursor-pointer" ${!j.audio_url ? 'disabled' : ''}>
                <span class="material-symbols-outlined text-[18px]">play_arrow</span>
              </button>
            </td>
            <td class="p-3.5 font-medium text-white max-w-md truncate">${escapeHtml(j.params?.text || j.type)}</td>
            <td class="p-3.5 font-mono text-purple-400 uppercase">${j.type}</td>
            <td class="p-3.5 font-mono text-slate-400">${j.created_at ? j.created_at.substring(11, 19) : ''}</td>
            <td class="p-3.5">
              <span class="px-2.5 py-1 rounded-full text-[10px] font-bold ${j.status === 'completed' ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/50' : 'bg-yellow-900/40 text-yellow-300'}">
                ${j.status === 'completed' ? 'Hoàn tất' : j.status}
              </span>
            </td>
            <td class="p-3.5 text-right">
              ${j.audio_url ? `
                <a href="${j.audio_url}" download="chatterbox-${j.id}.wav" class="p-1.5 rounded-lg bg-[#231F2A] hover:bg-purple-600 text-white inline-flex items-center gap-1">
                  <span class="material-symbols-outlined text-[16px]">download</span>
                </a>
              ` : ''}
            </td>
          </tr>
        `).join('');
      }
    }
  } catch (e) {}
}
