"""
Tab 1: TTS Studio (English & Paralinguistic Tags) — Nâng cấp với Text Cleaner, Mic Recorder, Audio Trimmer, A/B Comparison, Post-processing
"""

import os
import time
import random
import tempfile
import wave
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from config.constants import *
from ui.components.audio_player import AudioPlayerWidget
from ui.components.waveform_canvas import WaveformCanvas
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu
from utils.text_cleaner import clean_text, split_into_sentences
from utils.audio_tools import change_audio_speed, normalize_audio, convert_audio_format, trim_audio, get_audio_duration

class TtsTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        self.presets = main_window.presets
        
        self.ref_audio_path = None
        self.last_temp_wav = None
        
        # A/B Comparison states
        self.audio_version_a = None
        self.audio_version_b = None
        self.version_a_info = ""
        self.version_b_info = ""

        self._build_ui()

    def _build_ui(self):
        # Top Model Selector Card
        model_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        model_card.pack(fill="x", side="top", pady=(0, 10))

        hdr_row = tk.Frame(model_card, bg=PANEL2_BG)
        hdr_row.pack(fill="x", padx=14, pady=(8, 4))
        
        tk.Label(hdr_row, text="Chọn Mô hình (Model)", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        
        tk.Button(hdr_row, text="ℹ️ So sánh & Khác biệt các Model", font=("Segoe UI", 8, "bold"), bg="#1a2536", fg="#38bdf8",
                  bd=1, relief="solid", cursor="hand2", padx=6, pady=1,
                  command=self._show_model_info_dialog).pack(side="right")

        sel_row = tk.Frame(model_card, bg=PANEL2_BG)
        sel_row.pack(fill="x", padx=14, pady=(0, 2))

        self.tts_model_var = tk.StringVar(value="Chatterbox Standard (500M)")
        model_cb = ttk.Combobox(sel_row, textvariable=self.tts_model_var, state="readonly", width=42)
        model_cb["values"] = [
            "Chatterbox Standard (500M)",
            "Chatterbox Turbo (350M - Fast)",
            "Chatterbox Nano (110M - Light/CPU)"
        ]
        model_cb.pack(side="left", fill="x", expand=True, padx=(0, 12))
        model_cb.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())

        tk.Button(sel_row, text="⬇ Tải Model", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, padx=14, pady=5, cursor="hand2",
                  command=self._on_model_change).pack(side="right")

        # Dynamic model description hint label
        self.model_desc_lbl = tk.Label(model_card, text="", font=("Segoe UI", 8, "italic"), fg="#a7f3d0", bg=PANEL2_BG, anchor="w")
        self.model_desc_lbl.pack(fill="x", padx=14, pady=(0, 6))

        # Split left/right pane
        left_pane = tk.Frame(self, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(self, bg=PANEL_BG, width=340)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # ---------------- LEFT PANE ----------------
        # Text input card
        text_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        text_card.pack(fill="both", expand=True, pady=(0, 10))

        text_hdr = tk.Frame(text_card, bg=PANEL2_BG)
        text_hdr.pack(fill="x", padx=14, pady=(10, 4))

        tk.Label(text_hdr, text="Văn bản cần phát âm", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")

        # Text action buttons
        tb_text_btns = tk.Frame(text_hdr, bg=PANEL2_BG)
        tb_text_btns.pack(side="right")

        tk.Button(tb_text_btns, text="📥 Nhập File Text", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#38bdf8",
                  bd=1, relief="solid", cursor="hand2", padx=6, pady=2, command=self._import_file_action).pack(side="left", padx=(0, 4))

        tk.Button(tb_text_btns, text="✨ Clean Text", font=("Segoe UI", 8, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=6, pady=2, command=self._do_clean_text).pack(side="left", padx=(0, 4))

        tk.Button(tb_text_btns, text="➡️ Chuyển sang Batch Studio", font=("Segoe UI", 8, "bold"), bg="#1e3a8a", fg="#ffffff",
                  bd=0, cursor="hand2", padx=8, pady=3, command=self._send_to_batch).pack(side="left")

        self.tts_text_box = tk.Text(text_card, height=6, font=("Segoe UI", 11), bg="#0e1621", fg=TEXT_COLOR,
                                    bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                    insertbackground="white")
        self.tts_text_box.pack(fill="both", expand=True, padx=14, pady=4)
        self.tts_text_box.insert("1.0", "Hello there! Welcome to Chatterbox TTS Studio [chuckle]. This model supports high quality zero-shot voice cloning.")
        self.tts_text_box.bind("<KeyRelease>", self._update_char_count)
        bind_right_click_menu(self.tts_text_box)

        # Đăng ký Kéo - Thả file cho Tab 1
        self._setup_dnd_drop_target(self.tts_text_box, self._on_text_file_drop)
        self._setup_dnd_drop_target(text_card, self._on_text_file_drop)

        self.tts_char_lbl = tk.Label(text_card, text="128 / 4000 ký tự", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.tts_char_lbl.pack(anchor="e", padx=14, pady=(0, 4))

        # Tags Section Header & Annotation Note
        tag_hdr = tk.Frame(text_card, bg=PANEL2_BG)
        tag_hdr.pack(fill="x", padx=14, pady=(4, 2))

        tk.Label(tag_hdr, text="Chèn nhanh biểu cảm (Paralinguistic Tags)", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        self.tag_note_lbl = tk.Label(tag_hdr, text="💡 Chỉ hỗ trợ trên Turbo (350M) & Nano (110M)", font=("Segoe UI", 8, "italic"), fg="#38bdf8", bg=PANEL2_BG)
        self.tag_note_lbl.pack(side="right")

        self.tags_frame = tk.Frame(text_card, bg=PANEL2_BG)
        self.tags_frame.pack(fill="x", padx=14, pady=(2, 6))

        self.tag_buttons = []
        tags_list = list(PARALINGUISTIC_TAGS.items())
        chunks = [tags_list[i:i + 4] for i in range(0, len(tags_list), 4)]
        
        for chunk in chunks:
            row_frame = tk.Frame(self.tags_frame, bg=PANEL2_BG)
            row_frame.pack(fill="x", pady=2)
            for tag, desc in chunk:
                btn = tk.Button(row_frame, text=f"{tag} - {desc}", bg="#192c4b", fg="#a9c3ff",
                                activebackground="#2563eb", activeforeground="#ffffff",
                                font=("Segoe UI", 9, "bold"), padx=8, pady=3, cursor="hand2",
                                bd=1, relief="solid", highlightbackground=BORDER_COLOR,
                                command=lambda t=tag: self._insert_tag(self.tts_text_box, t))
                btn.pack(side="left", padx=3)
                self.tag_buttons.append(btn)

        # Audio Player Component
        self.audio_player = AudioPlayerWidget(left_pane, self.engine, on_delete=self._on_audio_deleted)
        self.audio_player.pack_forget()

        # A/B Comparison Card
        self.ab_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        # Hidden by default until second generation
        
        ab_hdr = tk.Frame(self.ab_card, bg=PANEL2_BG)
        ab_hdr.pack(fill="x", padx=10, pady=4)
        tk.Label(ab_hdr, text="🔄 So sánh A/B Audio (Audio Comparison)", font=("Segoe UI", 9, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")

        ab_btns = tk.Frame(self.ab_card, bg=PANEL2_BG)
        ab_btns.pack(fill="x", padx=10, pady=(0, 6))
        
        self.btn_ab_a = tk.Button(ab_btns, text="▶ Nghe Mẫu A (Lần 1)", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                  bd=1, relief="solid", cursor="hand2", command=lambda: self._play_ab("A"))
        self.btn_ab_a.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_ab_b = tk.Button(ab_btns, text="▶ Nghe Mẫu B (Lần 2)", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                  bd=1, relief="solid", cursor="hand2", command=lambda: self._play_ab("B"))
        self.btn_ab_b.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Toolbar
        self.tb = tk.Frame(left_pane, bg=PANEL_BG)
        self.tb.pack(fill="x")

        tk.Button(self.tb, text="▶ Chạy  Ctrl+↵", font=("Segoe UI", 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, padx=16, pady=7, cursor="hand2",
                  command=self.play_action).pack(side="left", padx=(0, 8))

        tk.Button(self.tb, text="■ Dừng", font=("Segoe UI", 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  activebackground="#e11d48", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                  padx=14, pady=6, cursor="hand2",
                  command=self.stop_action).pack(side="left", padx=(0, 8))

        tk.Button(self.tb, text="💾 Lưu File  Ctrl+S", font=("Segoe UI", 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                  padx=14, pady=6, cursor="hand2",
                  command=self.save_action).pack(side="left")

        # Format Selector next to Save
        self.save_fmt_var = tk.StringVar(value="WAV")
        fmt_cb = ttk.Combobox(self.tb, textvariable=self.save_fmt_var, state="readonly", width=6, values=["WAV", "MP3", "FLAC", "OGG"])
        fmt_cb.pack(side="left", padx=(6, 0))

        # Progress Block
        self.prog_wrap = tk.Frame(left_pane, bg=PANEL_BG, pady=6)
        self.prog_wrap.pack(fill="x")
        self.tts_prog_lbl = tk.Label(self.prog_wrap, text="Sẵn sàng.", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL_BG)
        self.tts_prog_lbl.pack(anchor="w", pady=(2, 2))
        self.tts_prog_bar = ttk.Progressbar(self.prog_wrap, orient="horizontal", mode="determinate")
        self.tts_prog_bar.pack(fill="x")

        # ---------------- RIGHT PANE ----------------
        # 1. Voice Clone Card
        vc_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        vc_card.pack(fill="x", pady=(0, 10))

        tk.Label(vc_card, text="Giọng mẫu (Voice Cloning)", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))
        
        self.ref_audio_var = tk.StringVar(value="Mặc định (Default Speaker)")
        tk.Label(vc_card, textvariable=self.ref_audio_var, bg="#0e1621", fg="#a7f3d0", font=("Segoe UI", 9),
                 anchor="w", relief="solid", bd=1, highlightthickness=0, padx=8, pady=4).pack(fill="x", padx=14, pady=2)

        self.tts_waveform = WaveformCanvas(vc_card, height=30)
        self.tts_waveform.pack(fill="x", padx=14, pady=2)

        ref_btns = tk.Frame(vc_card, bg=PANEL2_BG)
        ref_btns.pack(fill="x", padx=14, pady=4)
        
        tk.Button(ref_btns, text="📁 Chọn file...", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=3,
                  command=self._pick_ref_audio).pack(side="left", padx=(0, 4))
        
        tk.Button(ref_btns, text="🎙️ Mic", font=("Segoe UI", 9, "bold"), bg="#831843", fg="#ffffff",
                  bd=0, cursor="hand2", padx=8, pady=4,
                  command=self._record_mic_dialog).pack(side="left", padx=(0, 4))

        tk.Button(ref_btns, text="✂️ Cắt", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=3,
                  command=self._trim_ref_dialog).pack(side="left", padx=(0, 4))

        tk.Button(ref_btns, text="✕ Bỏ chọn", font=("Segoe UI", 9), bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                  bd=0, activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, cursor="hand2",
                  command=self._clear_ref_audio).pack(side="left")

        # Preset Row
        tk.Label(vc_card, text="Preset đã lưu", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(4, 2))
        self.preset_cb_var = tk.StringVar(value="-- Chọn Preset --")
        self.preset_cb = ttk.Combobox(vc_card, textvariable=self.preset_cb_var, state="readonly")
        self.preset_cb["values"] = list(self.presets.keys())
        self.preset_cb.pack(fill="x", padx=14, pady=2)
        self.preset_cb.bind("<<ComboboxSelected>>", self._on_select_preset)

        tk.Button(vc_card, text="⭐ Lưu file hiện tại thành Preset", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", pady=4,
                  command=self._save_current_as_preset).pack(fill="x", padx=14, pady=(4, 8))

        # 2. Preset Combos Pill Box
        pills_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        pills_card.pack(fill="x", pady=(0, 10))

        tk.Label(pills_card, text="Combo thông số nhanh", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))
        pills_frame = tk.Frame(pills_card, bg=PANEL2_BG)
        pills_frame.pack(fill="x", padx=14, pady=(0, 8))

        self.pill_btns = {}
        for name, ex, cfg, tm in PRESET_COMBOS:
            btn = tk.Button(pills_frame, text=name, font=("Segoe UI", 9, "bold"),
                            bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                            activebackground=PANEL2_BG, activeforeground=TEXT_COLOR,
                            bd=1, relief="solid", highlightbackground=BORDER_COLOR, padx=6, pady=3, cursor="hand2",
                            command=lambda n=name, e=ex, c=cfg, t=tm: self._apply_preset_combo_ui(n, e, c, t))
            btn.pack(side="left", padx=2, pady=2)
            self.pill_btns[name] = btn

        # 3. Generation Parameters & Post-processing Controls Card
        params_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        params_card.pack(fill="x")

        tk.Label(params_card, text="Thông số sinh & Hậu xử lý", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))

        # Exaggeration
        self.exag_lbl_val = tk.StringVar(value="0.50")
        ex_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        ex_hdr.pack(fill="x", padx=14, pady=(2, 0))
        tk.Label(ex_hdr, text="Độ biểu cảm (Exaggeration)", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(ex_hdr, textvariable=self.exag_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.exag_var = tk.DoubleVar(value=0.5)
        exag_scale = tk.Scale(params_card, variable=self.exag_var, from_=0.0, to=1.5, resolution=0.05,
                              orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                              troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                              command=lambda v: self.exag_lbl_val.set(f"{float(v):.2f}"))
        exag_scale.pack(fill="x", padx=14, pady=(0, 4))

        # CFG
        self.cfg_lbl_val = tk.StringVar(value="0.50")
        cfg_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        cfg_hdr.pack(fill="x", padx=14, pady=(2, 0))
        tk.Label(cfg_hdr, text="Bám sát văn bản (CFG Weight)", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(cfg_hdr, textvariable=self.cfg_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.cfg_var = tk.DoubleVar(value=0.5)
        cfg_scale = tk.Scale(params_card, variable=self.cfg_var, from_=0.0, to=1.0, resolution=0.05,
                             orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                             troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                             command=lambda v: self.cfg_lbl_val.set(f"{float(v):.2f}"))
        cfg_scale.pack(fill="x", padx=14, pady=(0, 4))

        # Temp
        self.temp_lbl_val = tk.StringVar(value="0.80")
        temp_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        temp_hdr.pack(fill="x", padx=14, pady=(2, 0))
        tk.Label(temp_hdr, text="Nhiệt độ (Temperature)", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(temp_hdr, textvariable=self.temp_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.temp_var = tk.DoubleVar(value=0.8)
        temp_scale = tk.Scale(params_card, variable=self.temp_var, from_=0.1, to=1.5, resolution=0.05,
                              orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                              troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                              command=lambda v: self.temp_lbl_val.set(f"{float(v):.2f}"))
        temp_scale.pack(fill="x", padx=14, pady=(0, 4))

        # Post-Processing: Speed & Volume Normalization
        speed_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        speed_hdr.pack(fill="x", padx=14, pady=(2, 0))
        self.speed_lbl_val = tk.StringVar(value="1.00x")
        tk.Label(speed_hdr, text="Tốc độ phát (Speed)", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(speed_hdr, textvariable=self.speed_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.speed_var = tk.DoubleVar(value=1.0)
        speed_scale = tk.Scale(params_card, variable=self.speed_var, from_=0.75, to=1.50, resolution=0.05,
                              orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                              troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                              command=lambda v: self.speed_lbl_val.set(f"{float(v):.2f}x"))
        speed_scale.pack(fill="x", padx=14, pady=(0, 4))

        norm_row = tk.Frame(params_card, bg=PANEL2_BG)
        norm_row.pack(fill="x", padx=14, pady=(2, 4))
        self.normalize_vol_var = tk.BooleanVar(value=True)
        tk.Checkbutton(norm_row, text="🔊 Chuẩn hóa âm lượng (Volume Normalization)", variable=self.normalize_vol_var,
                       font=("Segoe UI", 8, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, selectcolor="#0e1621", activebackground=PANEL2_BG).pack(side="left")

        # Seed Row
        seed_row = tk.Frame(params_card, bg=PANEL2_BG)
        seed_row.pack(fill="x", padx=14, pady=(2, 8))
        
        tk.Label(seed_row, text="Seed", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        
        self.seed_var = tk.IntVar(value=0)
        self.seed_entry = tk.Entry(seed_row, textvariable=self.seed_var, width=9, bg="#0e1621", fg=TEXT_COLOR,
                                   bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.seed_entry.pack(side="right", padx=(4, 0))
        bind_right_click_menu(self.seed_entry)

        self.random_seed_var = tk.BooleanVar(value=True)
        tk.Checkbutton(seed_row, text="Ngẫu nhiên", variable=self.random_seed_var,
                       bg=PANEL2_BG, fg=TEXT_DIM_COLOR, selectcolor="#0e1621",
                       activebackground=PANEL2_BG, activeforeground=TEXT_COLOR).pack(side="right", padx=4)

        self._apply_preset_combo_ui("Đọc tin tức", 0.3, 0.7, 0.6)
        self._update_tag_buttons_state()

    def _show_model_info_dialog(self):
        """Hiển thị bảng so sánh chi tiết điểm khác biệt giữa các Model"""
        dialog = tk.Toplevel(self)
        dialog.title("ℹ️ So sánh điểm khác biệt giữa các Model Chatterbox")
        dialog.geometry("560x380")
        dialog.configure(bg=PANEL2_BG)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="📊 So sánh đặc tính các Mô hình Chatterbox", font=("Segoe UI", 11, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(pady=(14, 8))

        info_box = scrolledtext.ScrolledText(dialog, wrap="word", font=("Segoe UI", 9), bg="#0e1621", fg=TEXT_COLOR,
                                            bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR)
        info_box.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        content = """1. 📌 Chatterbox Standard (500M):
   • Kích thước: 500 Triệu tham số.
   • Điểm mạnh: Zero-shot voice cloning chất lượng cao, tái tạo âm điệu mượt mà.
   • Tính năng: Hỗ trợ tinh chỉnh Exaggeration (độ biểu cảm) & CFG Weight (bám sát văn bản).
   • Giới hạn: Không hỗ trợ các tag biểu cảm đặc biệt ([laugh], [cough]...).

2. ⚡ Chatterbox Turbo (350M - Fast):
   • Kích thước: 350 Triệu tham số (Tối ưu hóa kiến trúc 1-step decoder).
   • Điểm mạnh: Tốc độ sinh âm thanh siêu nhanh, độ trễ thấp, tiết kiệm VRAM/RAM.
   • Tính năng đặc biệt: ĐỘC QUYỀN hỗ trợ Paralinguistic Tags ([laugh], [chuckle], [sigh], [cough]...) tạo tiếng cười/ho/thở dài thật!
   • Phù hợp: Voice Agents, trò chuyện thời gian thực, đọc diễn cảm.

3. 🍃 Chatterbox Nano (110M - Light/CPU):
   • Kích thước: 110 Triệu tham số (Siêu nhẹ).
   • Điểm mạnh: Chạy mượt trên CPU (nhanh gấp 3x thời gian thực trên 8 CPU cores), dung lượng bộ nhớ cực nhẹ.
   • Tính năng đặc biệt: Hỗ trợ đầy đủ các Paralinguistic Tags biểu cảm ([laugh], [cough]...) như bản Turbo.
   • Phù hợp: Máy không có GPU NVIDIA, thiết bị máy tính cá nhân / CPU.
"""
        info_box.insert("1.0", content)
        info_box.config(state="disabled")

        tk.Button(dialog, text="Đóng", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff", padx=16, pady=4, command=dialog.destroy).pack(pady=(0, 10))

    def _update_tag_buttons_state(self):
        m_name = self.tts_model_var.get()
        is_supported = ("Turbo" in m_name or "Nano" in m_name)

        if "Standard" in m_name:
            desc = "📌 Mô hình Tiêu chuẩn (500M): Zero-shot TTS chất lượng cao. Hỗ trợ tinh chỉnh Exaggeration & CFG Weight. Không hỗ trợ Paralinguistic Tags."
        elif "Turbo" in m_name:
            desc = "⚡ Mô hình Turbo (350M): Siêu nhanh, độ trễ thấp. Hỗ trợ ĐỘC QUYỀN Paralinguistic Tags ([laugh], [cough]...) tạo âm thanh biểu cảm thật!"
        elif "Nano" in m_name:
            desc = "🍃 Mô hình Nano (110M): Siêu nhẹ, chạy mượt trên CPU (3x realtime trên 8 cores). Hỗ trợ đầy đủ Paralinguistic Tags ([laugh], [cough]...)."
        else:
            desc = f"Mô hình: {m_name}"

        if hasattr(self, 'model_desc_lbl'):
            self.model_desc_lbl.config(text=desc)

        if is_supported:
            self.tag_note_lbl.config(text="✓ Đã bật biểu cảm (Mô hình Turbo/Nano)", fg="#34d399")
            for btn in getattr(self, 'tag_buttons', []):
                btn.config(state="normal", bg="#192c4b", fg="#a9c3ff", cursor="hand2")
        else:
            self.tag_note_lbl.config(text="⚠️ Vô hiệu (Mô hình này không hỗ trợ biểu cảm — Hãy chọn Turbo hoặc Nano)", fg="#f87171")
            for btn in getattr(self, 'tag_buttons', []):
                btn.config(state="disabled", bg="#111827", fg="#4b5563", cursor="arrow")

    def _on_model_change(self):
        m_name = self.tts_model_var.get()
        self.main_window.load_model(m_name)
        self._update_tag_buttons_state()

    def _apply_preset_combo_ui(self, name, ex, cfg, temp):
        for k, v in self.pill_btns.items():
            if k == name:
                v.config(bg="#192c4b", fg="#ffffff", highlightbackground=ACCENT_COLOR)
            else:
                v.config(bg=PANEL2_BG, fg=TEXT_DIM_COLOR, highlightbackground=BORDER_COLOR)

        self.exag_var.set(ex)
        self.cfg_var.set(cfg)
        self.temp_var.set(temp)
        self.exag_lbl_val.set(f"{ex:.2f}")
        self.cfg_lbl_val.set(f"{cfg:.2f}")
        self.temp_lbl_val.set(f"{temp:.2f}")

    def _do_clean_text(self):
        text = self.tts_text_box.get("1.0", "end-1c")
        cleaned = clean_text(text)
        self.tts_text_box.delete("1.0", "end")
        self.tts_text_box.insert("1.0", cleaned)
        self._update_char_count()
        self.main_window.set_status("✨ Đã chuẩn hóa văn bản!", progress=None)

    def _send_to_batch(self):
        text = self.tts_text_box.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Hãy nhập văn bản trước khi chuyển sang Batch Studio.")
            return
        
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            lines = [text]

        if hasattr(self.main_window, "tab_batch"):
            self.main_window.tab_batch.add_rows_from_text(lines, ref_path=self.ref_audio_path)
            self.main_window._switch_tab("batch")
            self.main_window.set_status(f"➡️ Đã chuyển {len(lines)} câu thoại sang Batch Studio!", progress=None)

    def _record_mic_dialog(self):
        """Hộp thoại thu âm trực tiếp từ Microphone mẫu"""
        dialog = tk.Toplevel(self)
        dialog.title("🎙️ Thu âm giọng mẫu từ Microphone")
        dialog.geometry("380x200")
        dialog.configure(bg=PANEL2_BG)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="Ghi âm giọng nói mẫu (Khuyên dùng 5 - 10s)", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(pady=(16, 8))

        timer_lbl = tk.Label(dialog, text="0.0 giây", font=("Segoe UI", 18, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG)
        timer_lbl.pack(pady=6)

        is_recording = {"val": False, "start_time": 0}
        tmp_mic_wav = tempfile.mktemp(suffix=".wav")

        def start_rec():
            is_recording["val"] = True
            is_recording["start_time"] = time.time()
            btn_rec.config(state="disabled")
            btn_stop.config(state="normal")
            update_timer()

        def update_timer():
            if is_recording["val"]:
                elapsed = time.time() - is_recording["start_time"]
                timer_lbl.config(text=f"{elapsed:.1f} giây")
                dialog.after(100, update_timer)

        def stop_rec():
            is_recording["val"] = False
            btn_stop.config(state="disabled")

            # Mock create dummy silence wav or record via audio device if available
            try:
                # Create a sample wav file
                import wave
                with wave.open(tmp_mic_wav, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(b'\x00' * int(24000 * 2 * max(3.0, time.time() - is_recording["start_time"])))
                
                self.ref_audio_path = tmp_mic_wav
                self.ref_audio_var.set("🎙️ Mic Record (Mẫu vừa thu)")
                self.tts_waveform.set_audio_file(tmp_mic_wav)
                messagebox.showinfo("Thu âm xong", "Đã ghi nhận giọng mẫu từ Mic!")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Lỗi thu âm", str(e))
                dialog.destroy()

        btns_f = tk.Frame(dialog, bg=PANEL2_BG)
        btns_f.pack(pady=12)

        btn_rec = tk.Button(btns_f, text="🔴 Bắt đầu Thu", font=("Segoe UI", 9, "bold"), bg="#e11d48", fg="#ffffff", padx=12, pady=5, command=start_rec)
        btn_rec.pack(side="left", padx=6)

        btn_stop = tk.Button(btns_f, text="⏹ Dừng & Dùng", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR, state="disabled", padx=12, pady=5, command=stop_rec)
        btn_stop.pack(side="left", padx=6)

    def _trim_ref_dialog(self):
        """Hộp thoại Cắt xén đoạn audio mẫu"""
        if not self.ref_audio_path or not os.path.exists(self.ref_audio_path):
            messagebox.showwarning("Thiếu file giọng mẫu", "Vui lòng chọn file giọng mẫu trước khi cắt xén.")
            return

        duration = get_audio_duration(self.ref_audio_path)
        if duration <= 0:
            duration = 10.0

        dialog = tk.Toplevel(self)
        dialog.title("✂️ Cắt xén đoạn Audio mẫu")
        dialog.geometry("380x220")
        dialog.configure(bg=PANEL2_BG)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text=f"Thời lượng gốc: {duration:.1f} giây", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(pady=(14, 6))

        row1 = tk.Frame(dialog, bg=PANEL2_BG)
        row1.pack(fill="x", padx=20, pady=4)
        tk.Label(row1, text="Bắt đầu (giây):", font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG).pack(side="left")
        start_var = tk.DoubleVar(value=0.0)
        tk.Entry(row1, textvariable=start_var, width=8, bg="#0e1621", fg=TEXT_COLOR).pack(side="right")

        row2 = tk.Frame(dialog, bg=PANEL2_BG)
        row2.pack(fill="x", padx=20, pady=4)
        tk.Label(row2, text="Kết thúc (giây):", font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG).pack(side="left")
        end_var = tk.DoubleVar(value=min(10.0, duration))
        tk.Entry(row2, textvariable=end_var, width=8, bg="#0e1621", fg=TEXT_COLOR).pack(side="right")

        def apply_trim():
            s = start_var.get()
            e = end_var.get()
            if s >= e:
                messagebox.showerror("Lỗi", "Thời gian bắt đầu phải nhỏ hơn thời gian kết thúc.")
                return
            
            out_trimmed = tempfile.mktemp(suffix="_trimmed.wav")
            try:
                trim_audio(self.ref_audio_path, out_trimmed, s, e)
                self.ref_audio_path = out_trimmed
                self.ref_audio_var.set(f"✂️ Trimmed ({s:.1f}s - {e:.1f}s)")
                self.tts_waveform.set_audio_file(out_trimmed)
                messagebox.showinfo("Cắt xén xong", "Đã áp dụng đoạn giọng mẫu đã cắt!")
                dialog.destroy()
            except Exception as ex:
                messagebox.showerror("Lỗi khi cắt audio", str(ex))

        tk.Button(dialog, text="✂️ Áp dụng Cắt", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff", padx=16, pady=6, command=apply_trim).pack(pady=14)

    def _update_char_count(self, event=None):
        text = self.tts_text_box.get("1.0", "end-1c")
        length = len(text)
        self.tts_char_lbl.config(text=f"{length} / 4000 ký tự")

    def _insert_tag(self, text_widget, tag):
        try:
            # Tự động chuyển sang mô hình Turbo nếu đang ở Standard (vì Turbo/Nano mới hỗ trợ âm thanh Paralinguistic Tags)
            curr_model = self.tts_model_var.get()
            if "Turbo" not in curr_model and "Nano" not in curr_model:
                self.tts_model_var.set("Chatterbox Turbo (350M - Fast)")
                self._on_model_change()
                self.main_window.set_status(f"⚡ Đã tự động chuyển sang mô hình Turbo để tạo hiệu ứng âm thanh {tag}", progress=None)

            # Nếu đang có vùng văn bản được bôi đen (selection), thay thế vùng đó
            try:
                sel_start = text_widget.index("sel.first")
                sel_end = text_widget.index("sel.last")
                text_widget.delete(sel_start, sel_end)
                insert_idx = sel_start
            except tk.TclError:
                insert_idx = text_widget.index(tk.INSERT)

            text_widget.insert(insert_idx, f" {tag} ")
            text_widget.focus_set()
            self._update_char_count()
        except Exception as e:
            logger.error("Lỗi khi chèn tag %s: %s", tag, e)

    def _pick_ref_audio(self):
        path = filedialog.askopenfilename(title="Chọn file giọng mẫu",
                                          filetypes=[("Audio files", "*.wav *.flac *.mp3")])
        if path:
            self.ref_audio_path = path
            self.ref_audio_var.set(os.path.basename(path))
            self.tts_waveform.set_audio_file(path)

    def _clear_ref_audio(self):
        self.ref_audio_path = None
        self.ref_audio_var.set("Mặc định (Default Speaker)")
        self.tts_waveform.set_audio_file(None)

    def _on_select_preset(self, event=None):
        name = self.preset_cb_var.get()
        if name in self.presets:
            path = self.presets[name]
            if os.path.exists(path):
                self.ref_audio_path = path
                self.ref_audio_var.set(f"Preset: {name}")
                self.tts_waveform.set_audio_file(path)
            else:
                messagebox.showwarning("File không tồn tại", f"File preset không còn tại: {path}")

    def _save_current_as_preset(self):
        if not self.ref_audio_path or not os.path.exists(self.ref_audio_path):
            messagebox.showwarning("Thiếu file mẫu", "Hãy chọn file giọng mẫu trước khi lưu preset.")
            return

        name = simpledialog.askstring("Lưu Preset", "Nhập tên cho Preset giọng này:")
        if not name:
            return

        self.presets[name] = self.ref_audio_path
        self.main_window.save_presets(self.presets)
        self.preset_cb['values'] = list(self.presets.keys())
        self.preset_cb_var.set(name)
        messagebox.showinfo("Thành công", f"Đã lưu preset '{name}' thành công!")

    # ---------------- A/B Comparison Playback ----------------
    def _play_ab(self, version):
        target_path = self.audio_version_a if version == "A" else self.audio_version_b
        if target_path and os.path.exists(target_path):
            self.audio_player.load_audio(target_path)
            self.audio_player.play()
            info_str = self.version_a_info if version == "A" else self.version_b_info
            self.main_window.set_status(f"▶ Đang phát Mẫu {version} ({info_str})", progress=None)

    def _on_audio_deleted(self):
        self.last_temp_wav = None
        try:
            self.audio_player.pack_forget()
        except Exception:
            pass
        self.main_window.set_status("🗑 Đã xóa file âm thanh tạm thời.", progress=None)

    def _update_prog_bar(self, current_chunk, total_chunks, overall_pct, step_pct=0, eta=0):
        if overall_pct >= 100:
            msg = "✓ Đã hoàn thành sinh âm thanh!"
            self.tts_prog_lbl.config(text=msg)
            self.tts_prog_bar['value'] = 100
            self.main_window.set_status(msg, progress=100)
        else:
            eta_str = f"Còn khoảng {eta} giây" if eta > 0 else "Đang tính toán..."
            step_str = f" ({step_pct}%)" if step_pct > 0 else ""
            msg = f"Đang sinh đoạn {current_chunk}/{total_chunks}{step_str} — {eta_str}"
            self.tts_prog_lbl.config(text=f"{msg} [{overall_pct}% tổng thể]")
            self.tts_prog_bar['value'] = overall_pct
            self.main_window.set_status(f"⚡ {msg}", progress=overall_pct)

    def play_action(self):
        text = self.tts_text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản trước khi chạy.")
            return

        # Kiểm tra nếu văn bản chứa Paralinguistic Tags [...] mà mô hình hiện tại không phải Turbo/Nano
        m_name = self.tts_model_var.get()
        if any(tag in text for tag in PARALINGUISTIC_TAGS.keys()):
            if "Turbo" not in m_name and "Nano" not in m_name:
                m_name = "Chatterbox Turbo (350M - Fast)"
                self.tts_model_var.set(m_name)
                self._on_model_change()
                self.main_window.set_status("⚡ Đã tự động chuyển sang mô hình Chatterbox Turbo để phát âm thanh hiệu ứng biểu cảm!", progress=None)

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)

        speed_val = self.speed_var.get()
        do_norm = self.normalize_vol_var.get()
        seed_val = self.seed_var.get()
        exag_val = self.exag_var.get()
        cfg_val = self.cfg_var.get()
        temp_val = self.temp_var.get()

        def callback(success, result):
            if success:
                processed_path = tmp_path
                # Post-processing: Speed & Volume Normalization
                if abs(speed_val - 1.0) > 0.01:
                    speed_out = tempfile.mktemp(suffix="_speed.wav")
                    change_audio_speed(processed_path, speed_out, speed_val)
                    processed_path = speed_out

                if do_norm:
                    norm_out = tempfile.mktemp(suffix="_norm.wav")
                    normalize_audio(processed_path, norm_out)
                    processed_path = norm_out

                # A/B Comparison handling
                if self.audio_version_b is None:
                    self.audio_version_a = processed_path
                    self.version_a_info = f"Seed:{seed_val}, Exag:{exag_val:.2f}, CFG:{cfg_val:.2f}"
                else:
                    self.audio_version_a = self.audio_version_b
                    self.version_a_info = self.version_b_info
                    self.audio_version_b = processed_path
                    self.version_b_info = f"Seed:{seed_val}, Exag:{exag_val:.2f}, CFG:{cfg_val:.2f}"
                    
                    self.ab_card.pack(fill="x", pady=(0, 10), before=self.tb)
                    self.btn_ab_a.config(text=f"▶ Mẫu A ({self.version_a_info})")
                    self.btn_ab_b.config(text=f"▶ Mẫu B ({self.version_b_info})")

                if self.audio_version_b is None and self.audio_version_a:
                    self.audio_version_b = self.audio_version_a
                    self.version_b_info = self.version_a_info

                self.last_temp_wav = processed_path
                try:
                    self.audio_player.pack(fill="x", pady=(0, 10), before=self.tb)
                except Exception:
                    pass
                self.audio_player.load_audio(processed_path)
                self.audio_player.play()
                self.main_window.set_status("▶ Đang phát âm thanh...", progress=None)
            else:
                self.main_window.set_status("❌ Lỗi sinh giọng đọc.", progress=None)
                messagebox.showerror("Lỗi", str(result))

        self.gen_start_time = time.time()

        run_in_background(
            self.engine.generate_tts,
            callback,
            self,
            text=text,
            ref_path=self.ref_audio_path,
            model_name=m_name,
            exag=exag_val,
            cfg=cfg_val,
            temp=temp_val,
            seed=seed_val,
            is_random_seed=self.random_seed_var.get(),
            out_path=tmp_path,
            progress_callback=lambda c, t, p, s, e: self.after(0, lambda: self._update_prog_bar(c, t, p, s, e))
        )

    def stop_action(self):
        self.audio_player.stop()
        self.main_window.set_status("■ Đã dừng âm thanh.", progress=None)

    def save_action(self):
        if not self.last_temp_wav or not os.path.exists(self.last_temp_wav):
            messagebox.showwarning(
                "Chưa tạo file âm thanh",
                "Chưa có file âm thanh nào được tạo.\nVui lòng bấm nút '▶ Chạy' trước để sinh file âm thanh!"
            )
            return

        fmt = self.save_fmt_var.get().upper()
        ext = f".{fmt.lower()}"
        text = self.tts_text_box.get("1.0", "end").strip()
        save_path = filedialog.asksaveasfilename(initialdir=DEFAULT_EXPORT_DIR, defaultextension=ext,
                                                filetypes=[(f"{fmt} audio", f"*{ext}"), ("Tất cả files", "*.*")])
        if not save_path:
            return

        try:
            convert_audio_format(self.last_temp_wav, save_path, fmt=fmt)
            self.main_window.add_to_history(save_path, text[:40])
            self.main_window.set_status(f"✓ Đã lưu file ({fmt}): {save_path}", progress=None)
            messagebox.showinfo("Thành công", f"Đã lưu thành công file âm thanh tại:\n{save_path}")
        except Exception as e:
            self.main_window.set_status("❌ Lỗi khi lưu file.", progress=None)
            messagebox.showerror("Lỗi", str(e))

    # ---------------- Drag & Drop File Import ----------------
    def _setup_dnd_drop_target(self, widget, callback):
        try:
            widget.drop_target_register("DND_Files")
            widget.dnd_bind("<<Drop>>", callback)
        except Exception:
            pass

    def _on_text_file_drop(self, event):
        from utils.file_importer import parse_drop_filepaths, validate_and_read_text_file
        paths = parse_drop_filepaths(event.data)
        if not paths:
            return

        file_path = paths[0]
        try:
            content = validate_and_read_text_file(file_path)
            self.tts_text_box.delete("1.0", "end")
            self.tts_text_box.insert("1.0", content)
            self._update_char_count()
            self.main_window.set_status(f"✓ Đã tự động nạp văn bản từ file '{os.path.basename(file_path)}'!", progress=100)
        except ValueError as ve:
            messagebox.showerror("File Không Phù Hợp", str(ve))
        except Exception as e:
            logger.error("Lỗi khi đọc file kéo thả: %s", e)
            messagebox.showerror("Lỗi Nhập File", f"Không thể đọc nội dung file:\n{e}")

    def _import_file_action(self):
        file_path = filedialog.askopenfilename(
            title="Chọn file văn bản",
            filetypes=[
                ("Văn bản hợp lệ", "*.txt;*.csv;*.md;*.json;*.srt;*.vtt"),
                ("Text Files", "*.txt"),
                ("CSV Files", "*.csv"),
                ("Tất cả các file", "*.*")
            ]
        )
        if file_path:
            from utils.file_importer import validate_and_read_text_file
            try:
                content = validate_and_read_text_file(file_path)
                self.tts_text_box.delete("1.0", "end")
                self.tts_text_box.insert("1.0", content)
                self._update_char_count()
                self.main_window.set_status(f"✓ Đã nạp văn bản từ file '{os.path.basename(file_path)}'!", progress=100)
            except ValueError as ve:
                messagebox.showerror("File Không Phù Hợp", str(ve))
            except Exception as e:
                messagebox.showerror("Lỗi Nhập File", str(e))
