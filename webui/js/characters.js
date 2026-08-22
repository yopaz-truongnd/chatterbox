/**
 * Chatterbox TTS Studio - Character Voice Management Module
 */

const SAMPLE_TEST_TEXTS = {
  "vi": "Xin chào, đây là câu đọc thử nghiệm trước khi tạo Character.",
  "en": "Hello, this is a sample voice preview before creating the character.",
  "ja": "こんにちは、これはキャラクターを作成する前の音声サンプルです。",
  "zh": "你好，这是创建角色前的语音测试示例。",
  "ko": "안녕하세요, 캐릭터를 생성하기 전 음성 테스트 샘플입니다.",
  "fr": "Bonjour, ceci est un exemple de voix avant de créer le personnage.",
  "de": "Hallo, dies ist eine Sprachprobe vor der Erstellung des Charakters.",
  "es": "Hola, este es un fragmento de prueba antes de crear el personaje.",
  "ru": "Здравствуйте, это образец голоса перед созданием персонажа.",
  "it": "Ciao, questo è un esempio di voce prima di creare il personnage.",
  "hi": "नमस्ते, पात्र बनाने से पहले यह một ध्वनि परीक्षण नमूना है।",
  "ar": "مرحبا، هذا نموذج صوتی اختیاری قبل إنشاء الشخصية.",
  "pt": "Olá, esta é uma amostra de voz antes de criar o personagem.",
  "nl": "Hallo, dit is een spraakvoorbeeld voordat het personage wordt gemaakt.",
  "pl": "Cześć, to jest próbka głosu przed utworzeniem postaci.",
  "tr": "Merhaba, bu karakter oluşturulmadan önceki ses test örneğidir."
};

async function loadCharacters() {
  const grid = document.getElementById('charactersGrid');
  const ttsSelect = document.getElementById('ttsCharacterSelect');
  const defaultLabel = document.getElementById('useDefaultCharLabel');

  try {
    const res = await fetch('/api/v1/characters');
    if (res.ok) {
      const data = await res.json();
      allCharactersCache = data.characters || [];

      // Populate TTS Dropdown
      if (ttsSelect) {
        const currentVal = ttsSelect.value;
        let optionsHtml = `
          <option value="">-- Mặc định (Default Speaker) --</option>
          <optgroup label="🎭 Style Presets (Bộ chỉnh phong cách)">
            <option value="builtin:mc_male">🎙️ MC Nam Thời Sự (Trầm ấm)</option>
            <option value="builtin:editor_female">🎙️ Nữ Biên Tập Viên (Truyền cảm)</option>
            <option value="builtin:story_night">🎙️ Kể Chuyện Đêm (Trầm lắng)</option>
            <option value="builtin:review_fast">🎙️ Review & Recap (Nhanh)</option>
            <option value="builtin:anime_fun">🎙️ Hoạt Hình / Anime (Biểu cảm)</option>
            <option value="builtin:ai_assistant">🎙️ Trợ Lý Ảo AI (Tự nhiên)</option>
          </optgroup>
        `;
        if (allCharactersCache.length > 0) {
          optionsHtml += '<optgroup label="👤 Nhân vật đã lưu (Characters)">';
          allCharactersCache.forEach(c => {
            const star = c.is_default ? '⭐ ' : '';
            const hasAudio = c.has_reference_audio ? '🎵 ' : '⚠️ ';
            optionsHtml += `<option value="char:${c.id}">${hasAudio}${star}${c.name} (${c.language || 'vi'})</option>`;
          });
          optionsHtml += '</optgroup>';
        }
        ttsSelect.innerHTML = optionsHtml;
        if (currentVal) ttsSelect.value = currentVal;
      }

      // Populate Batch Global Dropdown
      const batchGlobalSelect = document.getElementById('batchGlobalVoiceSelect');
      if (batchGlobalSelect) {
        const currentGlobal = batchGlobalSelect.value;
        let batchOpts = `
          <option value="">-- Mặc định --</option>
          <optgroup label="🎭 Style Presets (Bộ chỉnh phong cách)">
            <option value="builtin:mc_male">🎙️ MC Nam Thời Sự</option>
            <option value="builtin:editor_female">🎙️ Nữ Biên Tập Viên</option>
            <option value="builtin:story_night">🎙️ Kể Chuyện Đêm</option>
            <option value="builtin:review_fast">🎙️ Review & Recap</option>
            <option value="builtin:anime_fun">🎙️ Hoạt Hình / Anime</option>
            <option value="builtin:ai_assistant">🎙️ Trợ Lý Ảo AI</option>
          </optgroup>
        `;
        if (allCharactersCache.length > 0) {
          batchOpts += '<optgroup label="👤 Nhân vật đã lưu (Characters)">';
          allCharactersCache.forEach(c => {
            const star = c.is_default ? '⭐ ' : '';
            const hasAudio = c.has_reference_audio ? '🎵 ' : '⚠️ ';
            batchOpts += `<option value="char:${c.id}">${hasAudio}${star}${c.name} (${c.language || 'vi'})</option>`;
          });
          batchOpts += '</optgroup>';
        }
        batchGlobalSelect.innerHTML = batchOpts;
        if (currentGlobal) batchGlobalSelect.value = currentGlobal;
      }

      // Populate Multilingual Character Dropdown
      const mtlCharSelect = document.getElementById('mtlCharacterSelect');
      if (mtlCharSelect) {
        const currentMtlChar = mtlCharSelect.value;
        let mtlCharOpts = '<option value="">-- Mặc định (Default Speaker) --</option>';
        if (allCharactersCache.length > 0) {
          mtlCharOpts += '<optgroup label="👤 Nhân vật đã lưu (Characters)">';
          allCharactersCache.forEach(c => {
            const star = c.is_default ? '⭐ ' : '';
            const hasAudio = c.has_reference_audio ? '🎵 ' : '⚠️ ';
            mtlCharOpts += `<option value="char:${c.id}">${hasAudio}${star}${c.name} (${c.language || 'en'})</option>`;
          });
          mtlCharOpts += '</optgroup>';
        }
        mtlCharSelect.innerHTML = mtlCharOpts;
        if (currentMtlChar) mtlCharSelect.value = currentMtlChar;
      }

      if (parsedBatchLines && parsedBatchLines.length > 0 && typeof renderBatchTable === 'function') {
        renderBatchTable();
      }

      // Check default character
      const defChar = allCharactersCache.find(c => c.is_default);
      if (defaultLabel) {
        defaultLabel.textContent = defChar ? `⭐ Sử dụng Character mặc định (${defChar.name})` : `⭐ Sử dụng Character mặc định (Chưa đặt)`;
      }

      // Populate Character Management Grid
      if (grid) {
        if (allCharactersCache.length === 0) {
          grid.innerHTML = '<div class="text-xs text-slate-500 py-8 text-center col-span-full">Chưa có nhân vật nào. Nhấn "Tạo Nhân vật mới" để thêm!</div>';
          return;
        }
        grid.innerHTML = allCharactersCache.map(c => `
          <div class="p-4 rounded-xl bg-[#0E0C12] border ${c.is_default ? 'border-amber-500/50 bg-[#14101A]' : 'border-[#3F3A46]'} hover:border-purple-500 transition-colors space-y-3 flex flex-col justify-between">
            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2.5">
                  <div class="w-9 h-9 rounded-full ${c.is_default ? 'bg-amber-600/30 text-amber-300' : 'bg-purple-600/30 text-purple-300'} flex items-center justify-center font-bold text-xs">
                    ${c.name.substring(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div class="font-bold text-sm text-white flex items-center gap-1.5">
                      <span>${c.name}</span>
                      ${c.is_default ? '<span class="material-symbols-outlined text-amber-400 text-[16px]" title="Nhân vật mặc định">star</span>' : ''}
                    </div>
                    <div class="text-[10px] text-slate-400 uppercase font-mono">${c.language || 'vi'} • ${c.has_reference_audio ? '🎙️ Giọng mẫu độc quyền' : '⚡ Mặc định'}</div>
                  </div>
                </div>
                ${c.is_default ? '<span class="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-700/50">Mặc định</span>' : ''}
              </div>
              <div class="text-xs text-slate-300 line-clamp-2">${c.description || 'Không có mô tả chi tiết'}</div>
              <div class="grid grid-cols-3 gap-1 py-1.5 px-2 rounded-lg bg-[#18151E] border border-[#3F3A46]/60 text-[10px] font-mono text-slate-300">
                <div>Exag: <span class="text-purple-300">${c.voice?.expressiveness ?? 0.5}</span></div>
                <div>Pace: <span class="text-purple-300">${c.voice?.pace ?? 0.5}</span></div>
                <div>Seed: <span class="text-purple-300">${c.voice?.seed ?? 0}</span></div>
              </div>
            </div>

            <div class="flex justify-between items-center pt-2.5 border-t border-[#3F3A46]/50 gap-2">
              <button onclick="useCharacterInTts('${c.id}')" class="px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-700 text-white font-bold text-[11px] flex items-center gap-1 cursor-pointer">
                <span class="material-symbols-outlined text-[14px]">record_voice_over</span>
                <span>Dùng trong TTS</span>
              </button>
              <div class="flex items-center gap-1">
                <button onclick="toggleDefaultCharacter('${c.id}', ${!c.is_default})" class="p-1 rounded text-slate-300 hover:text-amber-400 hover:bg-[#231F2A] cursor-pointer" title="${c.is_default ? 'Bỏ làm mặc định' : 'Đặt làm mặc định'}">
                  <span class="material-symbols-outlined text-[16px]">${c.is_default ? 'star' : 'star_border'}</span>
                </button>
                <button onclick="deleteCharacter('${c.id}')" class="p-1 rounded text-red-400 hover:bg-red-900/30 cursor-pointer" title="Xóa nhân vật">
                  <span class="material-symbols-outlined text-[16px]">delete</span>
                </button>
              </div>
            </div>
          </div>
        `).join('');
      }
    }
  } catch (e) {
    if (grid) grid.innerHTML = '<div class="text-xs text-slate-500 py-8 text-center col-span-full">Không tải được danh sách nhân vật.</div>';
  }
}

function openCreateCharacterModal(prefillFromTts = false) {
  if (prefillFromTts) {
    const exagVal = document.getElementById('sliderExaggeration')?.value || '0.5';
    const paceVal = document.getElementById('sliderPace')?.value || '0.5';
    const seedVal = document.getElementById('seedInput')?.value || '0';

    const charExag = document.getElementById('charExagInput');
    const valCharExag = document.getElementById('valCharExag');
    const charPace = document.getElementById('charPaceInput');
    const valCharPace = document.getElementById('valCharPace');
    const charSeed = document.getElementById('charSeedInput');

    if (charExag) charExag.value = exagVal;
    if (valCharExag) valCharExag.textContent = parseFloat(exagVal).toFixed(2);
    if (charPace) charPace.value = paceVal;
    if (valCharPace) valCharPace.textContent = parseFloat(paceVal).toFixed(2);
    if (charSeed) charSeed.value = seedVal;
  }
  document.getElementById('characterModal')?.classList.remove('hidden');
}

function closeCreateCharacterModal() {
  document.getElementById('characterModal')?.classList.add('hidden');
}

function handleCharLangChange(lang) {
  const txt = SAMPLE_TEST_TEXTS[lang] || SAMPLE_TEST_TEXTS['vi'];
  const testInput = document.getElementById('charTestTextInput');
  if (testInput) testInput.value = txt;
}

function handleCharAudioFileSelected(input) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    const nameEl = document.getElementById('charAudioFileName');
    const labelEl = document.getElementById('charAudioBtnLabel');
    const clearBtn = document.getElementById('charAudioClearBtn');

    if (nameEl) nameEl.textContent = file.name;
    if (labelEl) labelEl.textContent = 'Đổi file mẫu...';
    if (clearBtn) clearBtn.classList.remove('hidden');
    showToast('info', `Đã chọn file mẫu "${file.name}"`);
  }
}

function clearCharAudioFile() {
  const fileInput = document.getElementById('charAudioFileInput');
  const nameEl = document.getElementById('charAudioFileName');
  const labelEl = document.getElementById('charAudioBtnLabel');
  const clearBtn = document.getElementById('charAudioClearBtn');

  if (fileInput) fileInput.value = '';
  if (nameEl) nameEl.textContent = 'Chưa chọn file mẫu (sử dụng âm sắc mặc định)';
  if (labelEl) labelEl.textContent = 'Chọn file audio mẫu...';
  if (clearBtn) clearBtn.classList.add('hidden');
}

async function testCharacterVoice() {
  const btn = document.getElementById('charTestVoiceBtn');
  const text = document.getElementById('charTestTextInput')?.value.trim();
  if (!text) return showToast('warning', 'Vui lòng nhập văn bản đọc thử.');

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang tạo...</span>';
  }

  try {
    const formData = new FormData();
    formData.append('text', text);
    formData.append('model', 'turbo');
    formData.append('temperature', '0.8');
    formData.append('repetition_penalty', '1.2');

    const audioInput = document.getElementById('charAudioFileInput');
    if (audioInput && audioInput.files && audioInput.files[0]) {
      formData.append('audio_prompt', audioInput.files[0]);
    }

    const res = await fetch('/api/v1/tts/turbo', { method: 'POST', body: formData });
    if (res.ok) {
      const job = await res.json();
      if (typeof pollJob === 'function') {
        await pollJob(job.id, btn, 'Nghe thử', '<span class="material-symbols-outlined text-[16px]">volume_up</span>');
      }
    } else {
      showToast('error', 'Lỗi khi sinh giọng thử nghiệm.');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">volume_up</span><span>Nghe thử</span>';
      }
    }
  } catch (err) {
    showToast('error', 'Lỗi đọc thử: ' + err.message);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">volume_up</span><span>Nghe thử</span>';
    }
  }
}

async function saveNewCharacter() {
  const btn = document.getElementById('charSaveBtn');
  const name = document.getElementById('charNameInput')?.value.trim();
  const desc = document.getElementById('charDescInput')?.value.trim() || '';
  const lang = document.getElementById('charLangSelect')?.value || 'vi';
  const exag = parseFloat(document.getElementById('charExagInput')?.value) || 0.5;
  const pace = parseFloat(document.getElementById('charPaceInput')?.value) || 0.5;
  const stab = parseFloat(document.getElementById('charStabInput')?.value) || 0.7;
  const seed = parseInt(document.getElementById('charSeedInput')?.value) || 0;
  const isDefault = document.getElementById('charIsDefaultInput')?.checked ?? false;

  if (!name) return showToast('warning', 'Vui lòng nhập tên nhân vật.');

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span><span>Đang lưu...</span>';
  }

  try {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('description', desc);
    formData.append('language', lang);
    formData.append('is_default', isDefault ? 'true' : 'false');
    formData.append('expressiveness', exag.toString());
    formData.append('pace', pace.toString());
    formData.append('stability', stab.toString());
    formData.append('seed', seed.toString());

    const audioInput = document.getElementById('charAudioFileInput');
    if (audioInput && audioInput.files && audioInput.files[0]) {
      formData.append('reference_audio', audioInput.files[0]);
    }

    const res = await fetch('/api/v1/characters', {
      method: 'POST',
      body: formData
    });

    if (res.ok) {
      closeCreateCharacterModal();
      const nameInp = document.getElementById('charNameInput');
      const descInp = document.getElementById('charDescInput');
      if (nameInp) nameInp.value = '';
      if (descInp) descInp.value = '';
      clearCharAudioFile();
      loadCharacters();
      showToast('success', `Đã lưu thành công nhân vật "${name}"!`);
    } else {
      const err = await res.json();
      showToast('error', 'Lỗi lưu nhân vật: ' + (err.detail || 'Không thể tạo'));
    }
  } catch (e) {
    showToast('error', 'Lỗi khi lưu nhân vật: ' + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = 'Lưu Nhân vật';
    }
  }
}

function handleTtsCharacterSelect(val) {
  if (!val) {
    uploadedRefFile = null;
    document.getElementById('refAudioCard')?.classList.add('hidden');
    showToast('info', 'Đã chuyển về giọng mặc định AI');
    return;
  }
  if (val.startsWith('builtin:')) {
    const key = val.replace('builtin:', '');
    if (typeof applyBuiltinVoice === 'function') applyBuiltinVoice(key);
    return;
  }
  const charId = val.replace('char:', '');
  const char = allCharactersCache.find(c => c.id === charId);
  if (char) {
    if (char.voice) {
      if (char.voice.expressiveness !== undefined) {
        setSlider('sliderExaggeration', 'valExaggeration', char.voice.expressiveness);
      }
      if (char.voice.pace !== undefined) {
        setSlider('sliderPace', 'valPace', char.voice.pace);
      }
      if (char.voice.seed !== undefined) {
        const seedInput = document.getElementById('seedInput');
        if (seedInput) seedInput.value = char.voice.seed;
      }
      if (typeof updateParamsSummaryBadge === 'function') updateParamsSummaryBadge();
    }
    if (char.has_reference_audio) {
      fetch(`/api/v1/characters/${char.id}/reference-audio`)
        .then(res => res.blob())
        .then(blob => {
          uploadedRefFile = new File([blob], `${char.name}_voice.wav`, { type: 'audio/wav' });
          const nameEl = document.getElementById('refAudioName');
          if (nameEl) nameEl.textContent = `Giọng Nhân vật: ${char.name}`;
          document.getElementById('refAudioCard')?.classList.remove('hidden');
        }).catch(() => {});
    } else {
      uploadedRefFile = null;
      document.getElementById('refAudioCard')?.classList.add('hidden');
    }
    showToast('success', `Đã áp dụng hồ sơ nhân vật "${char.name}" vào TTS Studio!`);
  }
}

function useCharacterInTts(charId) {
  switchTab('tts');
  const ttsSelect = document.getElementById('ttsCharacterSelect');
  if (ttsSelect) {
    const val = `char:${charId}`;
    ttsSelect.value = val;
    handleTtsCharacterSelect(val);
  }
}

async function toggleDefaultCharacter(id, isDefault) {
  try {
    const res = await fetch(`/api/v1/characters/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_default: isDefault })
    });
    if (res.ok) {
      loadCharacters();
      showToast('success', isDefault ? 'Đã đặt làm nhân vật mặc định!' : 'Đã bỏ mặc định.');
    }
  } catch (e) {
    showToast('error', 'Lỗi cập nhật mặc định: ' + e.message);
  }
}

function toggleUseDefaultChar(checked) {
  if (checked) {
    const def = allCharactersCache.find(c => c.is_default);
    if (def) {
      const val = `char:${def.id}`;
      const ttsSelect = document.getElementById('ttsCharacterSelect');
      if (ttsSelect) ttsSelect.value = val;
      handleTtsCharacterSelect(val);
    } else {
      showToast('warning', 'Chưa có nhân vật nào được đặt làm mặc định.');
      const chk = document.getElementById('useDefaultCharChk');
      if (chk) chk.checked = false;
    }
  } else {
    const ttsSelect = document.getElementById('ttsCharacterSelect');
    if (ttsSelect) ttsSelect.value = '';
    handleTtsCharacterSelect('');
  }
}

async function deleteCharacter(id) {
  if (!confirm("Bạn có chắc muốn xóa nhân vật này?")) return;
  try {
    await fetch(`/api/v1/characters/${id}`, { method: 'DELETE' });
    loadCharacters();
    showToast('info', 'Đã xóa nhân vật.');
  } catch (e) {
    showToast('error', 'Lỗi xóa nhân vật: ' + e.message);
  }
}
