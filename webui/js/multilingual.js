/**
 * Chatterbox TTS Studio - Multilingual TTS Engine Module
 */

const MTL_SAMPLE_TEXTS = {
  'en': 'Last month, we reached a new milestone with two billion views on our YouTube channel.',
  'es': 'El mes pasado alcanzamos un nuevo hito: dos mil millones de visualizaciones en nuestro canal de YouTube.',
  'fr': 'Le mois dernier, nous avons atteint un nouveau jalon avec deux milliards de vues sur notre chaîne YouTube.',
  'de': 'Letzten Monat haben wir einen neuen Meilenstein erreicht: zwei Milliarden Aufrufe auf unserem YouTube-Kanal.',
  'it': 'Il mese scorso abbiamo raggiunto un nuovo traguardo: due miliardi di visualizzazioni sul nostro canale YouTube.',
  'ja': '先月、私たちのYouTubeチャンネルで二十億回の再生回数という新たなマイルストーンに到達しました。',
  'zh': '上个月，我们达到了一个新的里程碑。我们的YouTube频道观看次数达到了二十亿次。',
  'ko': '지난달 우리는 유튜브 채널에서 이십억 조회수라는 새로운 이정표에 도달했습니다.',
  'ru': 'В прошлом месяце мы достигли нового рубежа: два миллиарда просмотров на нашем YouTube-канале.',
  'ar': 'في الشهر الماضي، وصلنا إلى معلم جديد بمليارين من المشاهدات على قناتنا على يوتيوب.',
  'hi': 'पिछले महीने हमने एक नया मील का पत्थर छुआ: हमारे YouTube चैनल पर दो अरब व्यूज़।',
  'pt': 'No mês passado, alcançámos um novo marco: dois mil milhões de visualizações no nosso canal do YouTube.',
  'nl': 'Vorige maand bereikten we một nieuwe mijlpaal met twee miljard weergaven op ons YouTube-kanaal.',
  'pl': 'W zeszłym miesiącu osiągnęliśmy nowy kamień milowy z dwoma miliardami wyświetleń na naszym kanale YouTube.',
  'tr': 'Geçen ay YouTube kanalımızda iki milyar görüntüleme ile yeni bir dönüm noktasına ulaştık.',
  'sw': 'Mwezi uliopita, tulifika hatua mpya ya maoni ya bilioni mbili kweny kituo chetu cha YouTube.',
  'sv': 'Förra månaden nådde vi en ny milstolpe med två miljarder visningar på vår YouTube-kanal.',
  'da': 'Sidste måned nåede vi en ny milepæl med to milliarder visninger på vores YouTube-kanal.',
  'fi': 'Viime kuussa saavutimme uuden virstanpylvään kahden miljardin katselukerran kanssa YouTube-kanavallamme.',
  'el': 'Τον περασμένο μήνα, φτάσαμε σε ένα νέο ορόσημο με δύο δισεκατομμύρια προβολές στο κανάλι μας στο YouTube.',
  'he': 'בחודש שעבר הגענו לאבן דרך חדשה עם שני מיליארד צפיות בערוץ היוטיוב שלנו.',
  'ms': 'Bulan lepas, kami mencapai pencapaian baru dengan dua bilion tontonan di saluran YouTube kami.',
  'no': 'Forrige måned nådde vi en ny milepæl med to milliarder visninger på YouTube-kanalen vår.'
};

function selectMtlLang(code, btnEl, updateSample = false) {
  selectedMtlLanguage = code;
  document.querySelectorAll('.mtl-lang-btn').forEach(b => {
    b.className = 'mtl-lang-btn p-2 rounded-lg bg-[#231F2A] hover:bg-[#2D2836] text-slate-300 border border-[#3F3A46] text-xs font-medium flex items-center gap-1.5 cursor-pointer';
  });
  if (btnEl) {
    btnEl.className = 'mtl-lang-btn active p-2 rounded-lg bg-purple-600 text-white border border-purple-500 text-xs font-medium flex items-center gap-1.5 cursor-pointer';
  }
  if (updateSample) {
    loadMtlSampleText();
  }
}

function loadMtlSampleText() {
  const input = document.getElementById('mtlPromptInput');
  if (input && MTL_SAMPLE_TEXTS[selectedMtlLanguage]) {
    input.value = MTL_SAMPLE_TEXTS[selectedMtlLanguage];
    updateMtlCharCount();
    showToast('info', `Đã nạp văn bản mẫu cho tiếng ${selectedMtlLanguage.toUpperCase()}`);
  }
}

function updateMtlCharCount() {
  const input = document.getElementById('mtlPromptInput');
  const countEl = document.getElementById('mtlCharCount');
  if (input && countEl) {
    countEl.textContent = `${input.value.length} / 4000 ký tự`;
  }
}

function updateMtlPromptFileLabel(input) {
  const label = document.getElementById('mtlAudioPromptLabel');
  if (input.files && input.files[0]) {
    if (label) label.textContent = `✓ ${input.files[0].name}`;
    showToast('success', `Đã chọn file mẫu "${input.files[0].name}"`);
  }
}

function clearMtlPromptFile() {
  const input = document.getElementById('mtlAudioPromptInput');
  const label = document.getElementById('mtlAudioPromptLabel');
  if (input) input.value = '';
  if (label) label.textContent = 'Chọn file WAV/MP3...';
  showToast('info', 'Đã xóa file mẫu âm thanh.');
}

async function triggerMtlSynthesis() {
  const btn = document.getElementById('mtlGenerateBtn');
  const text = document.getElementById('mtlPromptInput')?.value.trim();
  if (!text) return showToast('warning', 'Vui lòng nhập văn bản.');

  if (btn) {
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[22px]">progress_activity</span><span>Đang sinh âm thanh...</span>';
    btn.classList.add('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
    btn.disabled = true;
  }

  const formData = new FormData();
  formData.append('text', text);
  formData.append('language_id', selectedMtlLanguage || 'en');

  // Character selection
  const charSelect = document.getElementById('mtlCharacterSelect');
  if (charSelect && charSelect.value) {
    const val = charSelect.value;
    if (val.startsWith('char:')) {
      formData.append('character_id', val.replace('char:', ''));
    }
  }

  // Audio prompt file upload
  const refInput = document.getElementById('mtlAudioPromptInput');
  if (refInput && refInput.files && refInput.files[0]) {
    formData.append('audio_prompt', refInput.files[0]);
  }

  // Parameters
  const exag = document.getElementById('mtlExaggeration');
  if (exag) formData.append('exaggeration', exag.value);

  const temp = document.getElementById('mtlTemperature');
  if (temp) formData.append('temperature', temp.value);

  const cfg = document.getElementById('mtlCfgWeight');
  if (cfg) formData.append('cfg_weight', cfg.value);

  try {
    const res = await fetch('/api/v1/tts/multilingual', { method: 'POST', body: formData });
    if (res.ok) {
      const job = await res.json();
      showToast('info', 'Đã gửi tác vụ đa ngôn ngữ vào hàng đợi!');
      if (typeof pollJob === 'function') {
        await pollJob(job.id, btn, 'Sinh giọng nói Đa ngôn ngữ', '<span class="material-symbols-outlined text-[22px]">record_voice_over</span>');
      }
    } else {
      let errDetail = 'Lỗi khi gửi tác vụ đa ngôn ngữ.';
      try {
        const errData = await res.json();
        if (errData && errData.detail) {
          if (Array.isArray(errData.detail)) {
            errDetail = errData.detail.map(d => d.msg || d.detail || JSON.stringify(d)).join('; ');
          } else if (typeof errData.detail === 'string') {
            errDetail = errData.detail;
          } else {
            errDetail = JSON.stringify(errData.detail);
          }
        }
      } catch (_) {}
      showToast('error', errDetail);
      if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[22px]">record_voice_over</span><span>Sinh giọng nói Đa ngôn ngữ</span>';
        btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
        btn.disabled = false;
      }
    }
  } catch (e) {
    showToast('error', 'Lỗi kết nối: ' + e.message);
    if (btn) {
      btn.innerHTML = '<span class="material-symbols-outlined text-[22px]">record_voice_over</span><span>Sinh giọng nói Đa ngôn ngữ</span>';
      btn.classList.remove('opacity-60', 'cursor-not-allowed', 'pointer-events-none');
      btn.disabled = false;
    }
  }
}
