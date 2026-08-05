"""
Tab 2: Multilingual TTS Tab
"""

import os
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from config.constants import *
from ui.components.waveform_canvas import WaveformCanvas
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu

class MtlTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        
        self.mtl_ref_path = None

        self._build_ui()

    def _build_ui(self):
        # Selector Row Card
        top_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        top_card.pack(fill="x", side="top", pady=(0, 14))

        sel_row = tk.Frame(top_card, bg=PANEL2_BG, padx=14, pady=10)
        sel_row.pack(fill="x")

        # Version
        v_frame = tk.Frame(sel_row, bg=PANEL2_BG)
        v_frame.pack(side="left", padx=(0, 14))
        tk.Label(v_frame, text="Phiên bản MTL", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w")
        self.mtl_ver_var = tk.StringVar(value="v3")
        ttk.Combobox(v_frame, textvariable=self.mtl_ver_var, state="readonly", width=8, values=["v3", "v2"]).pack(anchor="w")

        # Language
        l_frame = tk.Frame(sel_row, bg=PANEL2_BG)
        l_frame.pack(side="left", fill="x", expand=True, padx=(0, 14))
        tk.Label(l_frame, text="Ngôn ngữ đọc (Language)", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w")
        
        lang_options = [f"{v}" for k, v in LANGUAGES_WITH_FLAGS.items()]
        self.mtl_lang_var = tk.StringVar(value="🇬🇧 English")
        ttk.Combobox(l_frame, textvariable=self.mtl_lang_var, state="readonly", values=lang_options).pack(fill="x")

        # Load button
        tk.Button(sel_row, text="⬇ Tải Multilingual Model", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, padx=14, pady=5, cursor="hand2",
                  command=self._on_mtl_load_model).pack(side="right", pady=(14, 0))

        # Split left/right pane
        left_pane = tk.Frame(self, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(self, bg=PANEL_BG, width=320)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # LEFT PANE
        # Text input card
        text_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        text_card.pack(fill="both", expand=True, pady=(0, 12))

        title_lbl = tk.Label(text_card, text="Văn bản đa ngôn ngữ", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG)
        title_lbl.pack(anchor="w", padx=14, pady=(10, 4))

        self.mtl_text_box = tk.Text(text_card, height=12, font=("Segoe UI", 11), bg="#0e1621", fg=TEXT_COLOR,
                                    bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                    insertbackground="white")
        self.mtl_text_box.pack(fill="both", expand=True, padx=14, pady=4)
        self.mtl_text_box.insert("1.0", "Bonjour tout le monde, bienvenue trên Chatterbox Multilingual TTS!")
        bind_right_click_menu(self.mtl_text_box)

        self.mtl_char_lbl = tk.Label(text_card, text="64 / 1000 ký tự", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.mtl_char_lbl.pack(anchor="e", padx=14, pady=(0, 8))

        # Toolbar
        tb = tk.Frame(left_pane, bg=PANEL_BG)
        tb.pack(fill="x")

        tk.Button(tb, text="▶ Đọc thử", font=("Segoe UI", 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, padx=16, pady=7, cursor="hand2",
                  command=self.play_action).pack(side="left", padx=(0, 8))

        tk.Button(tb, text="■ Dừng", font=("Segoe UI", 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                  padx=14, pady=6, cursor="hand2",
                  command=self.stop_action).pack(side="left", padx=(0, 8))

        tk.Button(tb, text="💾 Lưu File WAV", font=("Segoe UI", 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                  padx=14, pady=6, cursor="hand2",
                  command=self.save_action).pack(side="left")

        # RIGHT PANE
        # Voice clone
        vc_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        vc_card.pack(fill="x", pady=(0, 10))

        tk.Label(vc_card, text="Giọng mẫu (Multilingual Voice Clone)", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        
        self.mtl_ref_var = tk.StringVar(value="Mặc định")
        tk.Label(vc_card, textvariable=self.mtl_ref_var, bg="#0e1621", fg="#a7f3d0", font=("Segoe UI", 9),
                 anchor="w", relief="solid", bd=1, highlightthickness=0, padx=8, pady=5).pack(fill="x", padx=14, pady=4)

        self.mtl_waveform = WaveformCanvas(vc_card, height=34)
        self.mtl_waveform.pack(fill="x", padx=14, pady=4)

        ref_btns = tk.Frame(vc_card, bg=PANEL2_BG)
        ref_btns.pack(fill="x", padx=14, pady=(4, 12))
        tk.Button(ref_btns, text="📁 Chọn file...", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=10, pady=4,
                  command=self._pick_mtl_ref).pack(side="left", padx=(0, 6))
        tk.Button(ref_btns, text="✕ Bỏ chọn", font=("Segoe UI", 9), bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                  bd=0, activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, cursor="hand2",
                  command=self._clear_mtl_ref).pack(side="left")

        # Params
        param_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        param_card.pack(fill="x")

        tk.Label(param_card, text="Thông số Multilingual", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))

        self.mtl_exag_var = tk.DoubleVar(value=0.5)
        tk.Label(param_card, text="Exaggeration", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(4, 0))
        tk.Scale(param_card, variable=self.mtl_exag_var, from_=0.0, to=1.5, resolution=0.05,
                 orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                 troughcolor="#0e1621", activebackground=ACCENT_COLOR).pack(fill="x", padx=14, pady=(0, 8))

        self.mtl_cfg_var = tk.DoubleVar(value=0.5)
        tk.Label(param_card, text="CFG Weight", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(4, 0))
        tk.Scale(param_card, variable=self.mtl_cfg_var, from_=0.0, to=1.0, resolution=0.05,
                 orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                 troughcolor="#0e1621", activebackground=ACCENT_COLOR).pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(param_card, text="Lưu ý: model MTL hiện chưa hỗ trợ Paralinguistic Tags và Temperature — sẽ đồng bộ khi bản model mới hỗ trợ.",
                 font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG, wraplength=280, justify="left").pack(fill="x", padx=14, pady=(8, 14))

    def _on_mtl_load_model(self):
        ver = self.mtl_ver_var.get()
        m_name = f"Multilingual ({ver})"
        self.main_window.load_model(m_name, extra_args={"ver": ver})

    def _pick_mtl_ref(self):
        path = filedialog.askopenfilename(title="Chọn file giọng mẫu", filetypes=[("Audio files", "*.wav *.flac *.mp3")])
        if path:
            self.mtl_ref_path = path
            self.mtl_ref_var.set(os.path.basename(path))
            self.mtl_waveform.set_audio_file(path)

    def _clear_mtl_ref(self):
        self.mtl_ref_path = None
        self.mtl_ref_var.set("Mặc định")
        self.mtl_waveform.set_audio_file(None)

    def play_action(self):
        text = self.mtl_text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản.")
            return

        ver = self.mtl_ver_var.get()
        lang_str = self.mtl_lang_var.get()
        lang_code = "en"
        for k, v in LANGUAGES_WITH_FLAGS.items():
            if v == lang_str:
                lang_code = k
                break

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)

        def callback(success, result):
            if success:
                self.engine.play_audio(tmp_path)
                self.main_window.set_status("Đang phát Multilingual...")
            else:
                self.main_window.set_status("Lỗi sinh Multilingual.")
                messagebox.showerror("Lỗi", str(result))

        run_in_background(
            self.engine.generate_multilingual,
            callback,
            self,
            text=text,
            lang_code=lang_code,
            ref_path=self.mtl_ref_path,
            exag=self.mtl_exag_var.get(),
            cfg=self.mtl_cfg_var.get(),
            model_ver=ver,
            out_path=tmp_path
        )

    def stop_action(self):
        self.engine.stop_audio()
        self.main_window.set_status("Đã dừng âm thanh.")

    def save_action(self):
        text = self.mtl_text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản.")
            return

        save_path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV audio", "*.wav")])
        if not save_path:
            return

        ver = self.mtl_ver_var.get()
        lang_str = self.mtl_lang_var.get()
        lang_code = "en"
        for k, v in LANGUAGES_WITH_FLAGS.items():
            if v == lang_str:
                lang_code = k
                break

        def callback(success, result):
            if success:
                self.main_window.set_status(f"Đã lưu: {save_path}")
                self.main_window.add_to_history(save_path, f"MTL [{lang_code}]: {text[:30]}")
                messagebox.showinfo("Thành công", f"Đã lưu file:\n{save_path}")
            else:
                self.main_window.set_status("Lỗi khi lưu file.")
                messagebox.showerror("Lỗi", str(result))

        run_in_background(
            self.engine.generate_multilingual,
            callback,
            self,
            text=text,
            lang_code=lang_code,
            ref_path=self.mtl_ref_path,
            exag=self.mtl_exag_var.get(),
            cfg=self.mtl_cfg_var.get(),
            model_ver=ver,
            out_path=save_path
        )
