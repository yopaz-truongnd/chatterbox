"""GUI manager for Characters shared with the local API."""
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import character_api
from config.constants import *
from ui.components.audio_player import AudioPlayerWidget
from utils.threading_helper import run_in_background

LANGUAGE_OPTIONS = [
    ("en", "🇬🇧 en - English"),
    ("vi", "🇻🇳 vi - Tiếng Việt"),
    ("es", "🇪🇸 es - Spanish"),
    ("fr", "🇫🇷 fr - French"),
    ("de", "🇩🇪 de - German"),
    ("it", "🇮🇹 it - Italian"),
    ("ja", "🇯🇵 ja - Japanese"),
    ("zh", "🇨🇳 zh - Chinese"),
    ("ko", "🇰🇷 ko - Korean"),
    ("ru", "🇷🇺 ru - Russian"),
    ("ar", "🇸🇦 ar - Arabic"),
    ("hi", "🇮🇳 hi - Hindi"),
    ("pt", "🇵🇹 pt - Portuguese"),
    ("nl", "🇳🇱 nl - Dutch"),
    ("pl", "🇵🇱 pl - Polish"),
    ("tr", "🇹🇷 tr - Turkish"),
]

SAMPLE_TEST_TEXTS = {
    "en": "Hello, this is a sample voice preview before creating the character.",
    "vi": "Xin chào, đây là câu đọc thử nghiệm trước khi tạo Character.",
    "es": "Hola, este es un fragmento de prueba antes de crear el personaje.",
    "fr": "Bonjour, ceci est un exemple de voix avant de créer le personnage.",
    "de": "Hallo, dies ist eine Sprachprobe vor der Erstellung des Charakters.",
    "it": "Ciao, questo è un esempio di voce prima di creare il personaggio.",
    "ja": "こんにちは、これはキャラクターを作成する前の音声サンプルです。",
    "zh": "你好，这是创建角色前的语音测试示例。",
    "ko": "안녕하세요, 캐릭터를 생성하기 전 음성 테스트 샘플입니다.",
    "ru": "Здравствуйте, это образец голоса перед созданием персонажа.",
    "ar": "مرحبا، هذا نموذج صوتي اختباري قبل إنشاء الشخصية.",
    "hi": "नमस्ते, पात्र बनाने से पहले यह एक ध्वनि परीक्षण नमूना है।",
    "pt": "Olá, esta é uma amostra de voz antes de criar o personagem.",
    "nl": "Hallo, dit is een spraakvoorbeeld voordat het personage wordt gemaakt.",
    "pl": "Cześć, to jest próbka głosu przed utworzeniem postaci.",
    "tr": "Merhaba, bu karakter oluşturulmadan önceki ses test örneğidir.",
}


class CharacterTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        self.rows = []
        self.audio_path = None
        self._test_temp_wav = None
        self._build_ui()
        self.refresh_characters()

    def _build_ui(self):
        header = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(header, text="🎭 Quản lý Characters", font=(UI_FONT, 11, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left", padx=16, pady=10)
        self.count_label = tk.Label(header, text="0 Characters", font=(UI_FONT, 9, "bold"), bg="#192c4b", fg="#a9c3ff", padx=10, pady=3)
        self.count_label.pack(side="right", padx=16)

        content = tk.Frame(self, bg=PANEL_BG)
        content.pack(fill="both", expand=True)
        left = tk.Frame(content, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = tk.Frame(content, bg=PANEL2_BG, width=410, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        right.pack(side="right", fill="both", padx=(8, 0))

        # Left: Character list tree
        self.tree = ttk.Treeview(left, columns=("name", "language", "audio", "id"), show="headings", selectmode="browse")
        for key, title, width in (("name", "Tên", 150), ("language", "Ngôn ngữ", 80), ("audio", "Reference", 80), ("id", "Character ID", 250)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="center" if key in ("language", "audio") else "w")
        self.tree.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-1>", lambda e: self._hide_context_menu(), add="+")
        self.bind("<Button-1>", lambda e: self._hide_context_menu(), add="+")

        # Right-click Context Menu for Treeview
        self.context_menu = tk.Menu(self.tree, tearoff=0, bg="#121b28", fg="#dbe4f0", activebackground="#4f8cff", activeforeground="#ffffff", bd=1)
        self.context_menu.add_command(label="🗣️ Dùng trong TTS", command=lambda: (self._hide_context_menu(), self.use_in_tts()))
        self.context_menu.add_command(label="⭐ Đặt / Bỏ Mặc định", command=lambda: (self._hide_context_menu(), self.set_as_default()))
        self.context_menu.add_command(label="📋 Sao chép Character ID", command=lambda: (self._hide_context_menu(), self.copy_character_id()))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="↻ Làm mới danh sách", command=lambda: (self._hide_context_menu(), self.refresh_characters()))
        self.context_menu.add_command(label="🗑 Xóa Character", command=lambda: (self._hide_context_menu(), self.delete_selected()))

        toolbar = tk.Frame(left, bg=PANEL2_BG)
        toolbar.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(toolbar, text="↻ Làm mới", bg="#1a2536", fg=TEXT_COLOR, command=self.refresh_characters).pack(side="left")
        tk.Button(toolbar, text="🗣️ Dùng trong TTS", bg=ACCENT_COLOR, fg="white", bd=0, padx=12, pady=5, command=self.use_in_tts).pack(side="left", padx=6)
        tk.Button(toolbar, text="⭐ Đặt Mặc định", bg="#1a2536", fg="#f59e0b", bd=1, relief="solid", padx=10, pady=4, command=self.set_as_default).pack(side="left", padx=4)
        tk.Button(toolbar, text="🗑 Xóa", bg=PANEL2_BG, fg="#f87171", bd=0, command=self.delete_selected).pack(side="right")

        # Right: Create Character Form & Player & Detail
        tk.Label(right, text="Tạo Character mới", font=(UI_FONT, 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        form = tk.Frame(right, bg=PANEL2_BG)
        form.pack(fill="x", padx=14)

        self.name_var = tk.StringVar()
        self.language_var = tk.StringVar(value="🇬🇧 en - English")
        self.audio_var = tk.StringVar(value="Không có (Optional)")
        self.expressiveness_var = tk.DoubleVar(value=0.5)
        self.pace_var = tk.DoubleVar(value=0.5)
        self.stability_var = tk.DoubleVar(value=0.7)
        self.seed_var = tk.IntVar(value=0)
        self.test_text_var = tk.StringVar(value=SAMPLE_TEST_TEXTS["en"])

        # Name
        self._entry(form, "Tên Character", self.name_var)

        # Language Dropdown (Combobox)
        tk.Label(form, text="Ngôn ngữ (Language)", fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", pady=(6, 2))
        lang_values = [label for _, label in LANGUAGE_OPTIONS]
        self.lang_cb = ttk.Combobox(form, textvariable=self.language_var, values=lang_values, state="readonly")
        self.lang_cb.pack(fill="x")
        self.lang_cb.bind("<<ComboboxSelected>>", self._on_language_changed)

        # Reference Audio (Optional)
        tk.Label(form, text="Reference audio (Optional)", fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", pady=(6, 2))
        ref_box = tk.Frame(form, bg="#0e1621", bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        ref_box.pack(fill="x")
        tk.Label(ref_box, textvariable=self.audio_var, bg="#0e1621", fg="#a7f3d0", anchor="w", padx=8, pady=4, font=(UI_FONT, 8)).pack(side="left", fill="x", expand=True)
        
        btn_frame = tk.Frame(form, bg=PANEL2_BG)
        btn_frame.pack(fill="x", pady=4)
        tk.Button(btn_frame, text="📁 Chọn file audio...", bg="#1a2536", fg=TEXT_COLOR, font=(UI_FONT, 8), command=self.pick_audio).pack(side="left")
        tk.Button(btn_frame, text="❌ Bỏ chọn mẫu", bg="#1a2536", fg="#f87171", font=(UI_FONT, 8), command=self.clear_audio).pack(side="left", padx=6)

        # Sliders & Seed
        self._scale(form, "Độ biểu cảm", self.expressiveness_var)
        self._scale(form, "Nhịp đọc", self.pace_var)
        self._scale(form, "Độ ổn định", self.stability_var)
        self._entry(form, "Seed", self.seed_var)

        # Test Text Input
        self._entry(form, "Văn bản đọc thử", self.test_text_var)

        # Action Buttons: Test Voice & Create Character
        act_row = tk.Frame(form, bg=PANEL2_BG)
        act_row.pack(fill="x", pady=(10, 6))
        self.test_btn = tk.Button(act_row, text="🔊 Nghe thử giọng", font=(UI_FONT, 9, "bold"), bg="#1e293b", fg="#a9c3ff", bd=1, relief="solid", cursor="hand2", pady=5, command=self.test_voice)
        self.test_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.create_btn = tk.Button(act_row, text="＋ Tạo Character", font=(UI_FONT, 9, "bold"), bg=ACCENT_COLOR, fg="white", bd=0, cursor="hand2", pady=5, command=self.create_character)
        self.create_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Detail Box Header Label (used as reference for audio_player packing)
        self.detail_label = tk.Label(right, text="Chi tiết Character chọn trong bảng", font=(UI_FONT, 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.detail_label.pack(anchor="w", padx=14, pady=(6, 0))

        # Audio Player Widget for Preview
        self.audio_player = AudioPlayerWidget(right, self.engine)

        self.detail = tk.Text(right, height=5, bg="#0e1621", fg=TEXT_COLOR, bd=0, padx=8, pady=6, font=(MONO_FONT, 8), state="disabled")
        self.detail.pack(fill="both", expand=True, padx=14, pady=(2, 10))

    def _entry(self, parent, label, variable):
        tk.Label(parent, text=label, fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", pady=(5, 1))
        tk.Entry(parent, textvariable=variable, bg="#0e1621", fg=TEXT_COLOR, insertbackground="white", bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR).pack(fill="x", ipady=3)

    def _scale(self, parent, label, variable):
        row = tk.Frame(parent, bg=PANEL2_BG)
        row.pack(fill="x", pady=(5, 0))
        tk.Label(row, text=label, fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        value = tk.Label(row, text=f"{variable.get():.2f}", fg=ACCENT_COLOR, bg=PANEL2_BG)
        value.pack(side="right")
        tk.Scale(parent, variable=variable, from_=0.0, to=1.0, resolution=0.05, orient="horizontal", bg=PANEL2_BG, fg=TEXT_COLOR, troughcolor="#0e1621", highlightthickness=0, command=lambda current, target=value: target.config(text=f"{float(current):.2f}")).pack(fill="x")

    def _on_language_changed(self, event=None):
        code = self._get_selected_lang_code()
        sample_text = SAMPLE_TEST_TEXTS.get(code, SAMPLE_TEST_TEXTS["en"])
        self.test_text_var.set(sample_text)

    def _hide_context_menu(self, event=None):
        try:
            self.context_menu.unpost()
        except Exception:
            pass

    def _on_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self._on_select()
            try:
                self.context_menu.post(event.x_root, event.y_root)
            except Exception:
                pass

    def copy_character_id(self):
        character = self._selected()
        if character:
            self.clipboard_clear()
            self.clipboard_append(character["id"])
            self.main_window.set_status(f"📋 Đã sao chép ID: {character['id']}")

    def set_as_default(self):
        character = self._selected()
        if not character:
            messagebox.showwarning("Chưa chọn Character", "Vui lòng chọn Character cần đặt làm mặc định.")
            return
        if character.get("is_default"):
            character_api.set_default_character(None)
            self.main_window.set_status(f"❌ Đã bỏ Mặc định cho Character '{character['name']}'")
        else:
            character_api.set_default_character(character["id"])
            self.main_window.set_status(f"⭐ Đã đặt '{character['name']}' làm Character Mặc định!")
        self.refresh_characters(character["id"])
        self.main_window.tab_tts._refresh_character_choices()

    def pick_audio(self):
        path = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.flac *.mp3 *.ogg *.m4a"), ("Tất cả", "*.*")])
        if path:
            self.audio_path = path
            self.audio_var.set(Path(path).name)

    def clear_audio(self):
        self.audio_path = None
        self.audio_var.set("Không có (Optional)")

    def test_voice(self):
        text = self.test_text_var.get().strip()
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản đọc thử.")
            return

        self.test_btn.config(state="disabled", text="⏳ Đang tạo...")
        self.main_window.set_status("⏳ Đang sinh âm thanh thử nghiệm...")

        exag_val = self.expressiveness_var.get()
        cfg_val = self.pace_var.get()
        temp_val = max(0.1, min(1.0, 1.2 - 0.7 * self.stability_var.get()))
        seed_val = max(0, self.seed_var.get())

        tmp_out = tempfile.mktemp(suffix="_test_voice.wav", dir=str(TMP_DIR))

        def callback(success, result):
            self.test_btn.config(state="normal", text="🔊 Nghe thử giọng")
            out_file = result[0] if isinstance(result, (tuple, list)) else result
            if success and out_file and isinstance(out_file, (str, Path)) and os.path.exists(out_file):
                self._test_temp_wav = str(out_file)
                try:
                    self.audio_player.pack(fill="x", padx=14, pady=(2, 6), before=self.detail_label)
                except Exception:
                    pass
                self.audio_player.load_audio(str(out_file))
                self.audio_player.play()
                self.main_window.set_status("▶ Đang phát âm thanh thử nghiệm...", progress=None)
            else:
                self.main_window.set_status("❌ Lỗi sinh âm thanh thử nghiệm.", progress=None)
                messagebox.showerror("Lỗi thử giọng", str(result))

        model_name = getattr(self.engine, "active_model_name", None) or "Chatterbox Standard (500M)"

        run_in_background(
            self.engine.generate_tts,
            callback,
            self,
            text=text,
            ref_path=self.audio_path,
            model_name=model_name,
            exag=exag_val,
            cfg=cfg_val,
            temp=temp_val,
            seed=seed_val,
            is_random_seed=False,
            out_path=tmp_out,
        )

    def _get_selected_lang_code(self):
        val = self.language_var.get().strip()
        if " - " in val:
            parts = val.split(" - ")
            code_part = parts[0].split()[-1]
            return code_part
        return val or "en"

    def create_character(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập tên Character.")
            return

        lang_code = self._get_selected_lang_code()
        try:
            voice = character_api.VoiceProfile(
                expressiveness=self.expressiveness_var.get(),
                pace=self.pace_var.get(),
                stability=self.stability_var.get(),
                seed=max(0, self.seed_var.get()),
            )
            character = character_api.create_character_from_audio(name, self.audio_path, voice, lang_code)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Không thể tạo Character", str(exc))
            return

        self.name_var.set("")
        self.clear_audio()
        self.refresh_characters(character["id"])
        self.main_window.tab_tts._refresh_character_choices()
        messagebox.showinfo("Đã tạo Character", f"Tạo Character '{character['name']}' thành công!\n\nCharacter ID:\n{character['id']}")

    def refresh_characters(self, select_id=None):
        character_api.load_characters()
        with character_api.characters_lock:
            self.rows = sorted((dict(item) for item in character_api.characters.values()), key=lambda item: item["created_at"], reverse=True)
        self.tree.delete(*self.tree.get_children())
        selected = None
        for character in self.rows:
            is_def = character.get("is_default", False)
            display_name = f"⭐ {character['name']}" if is_def else character["name"]
            item = self.tree.insert("", "end", values=(display_name, character["language"], "Có" if character.get("reference_audio_path") else "Không", character["id"]))
            if character["id"] == select_id:
                selected = item
        self.count_label.config(text=f"{len(self.rows)} Characters")
        if selected:
            self.tree.selection_set(selected)
            self._on_select()

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            return None
        character_id = self.tree.item(selection[0], "values")[3]
        return next((item for item in self.rows if item["id"] == character_id), None)

    def _on_select(self, event=None):
        character = self._selected()
        if not character:
            return
        voice = character["voice"]
        is_def_str = "Có (Default)" if character.get("is_default") else "Không"
        text = f"Tên: {character['name']}\nID: {character['id']}\nMặc định: {is_def_str}\nNgôn ngữ: {character['language']}\nReference: {character.get('reference_audio_path') or 'Không có'}\nBiểu cảm: {voice['expressiveness']} | Nhịp: {voice['pace']} | Ổn định: {voice['stability']} | Seed: {voice['seed']}"
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def use_in_tts(self):
        character = self._selected()
        if not character:
            messagebox.showwarning("Chưa chọn Character", "Vui lòng chọn một Character.")
            return
        tab = self.main_window.tab_tts
        tab._refresh_character_choices()
        label_match = next((k for k in tab.character_choices if character['id'] in k), None)
        if label_match:
            tab.preset_cb_var.set(label_match)
            tab._on_select_preset()
            self.main_window._switch_tab("tts")
        else:
            messagebox.showinfo("Thông báo", "Character này không có reference audio nên không dùng trực tiếp làm Voice Clone trong TTS Tab.")

    def delete_selected(self):
        character = self._selected()
        if not character:
            messagebox.showwarning("Chưa chọn Character", "Vui lòng chọn Character cần xóa.")
            return
        if messagebox.askyesno("Xác nhận xóa", f"Xóa Character '{character['name']}'?"):
            character_api.delete_character(character["id"])
            self.refresh_characters()
            self.main_window.tab_tts._refresh_character_choices()
            self.detail.config(state="normal")
            self.detail.delete("1.0", "end")
            self.detail.config(state="disabled")
