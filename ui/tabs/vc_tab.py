"""
Tab 3: Voice Conversion (VC) Tab
"""

import os
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from config.constants import *
from ui.components.waveform_canvas import WaveformCanvas
from utils.logger import logger
from utils.threading_helper import run_in_background
from ui.button_styles import set_button_busy

class VcTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        
        self.vc_src_path = None
        self.vc_tgt_path = None
        self.vc_last_result_path = None

        self._build_ui()

    def _build_ui(self):
        header_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        header_card.pack(fill="x", side="top", pady=(0, 14))

        tk.Label(header_card, text="Chatterbox Voice Conversion (Audio-to-Audio)", font=(UI_FONT, 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(header_card, text="Chuyển đổi giọng nói trong File Âm thanh Nguồn sang chất giọng của File Giọng Mẫu Đích.",
                 font=(UI_FONT, 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(0, 10))

        row = tk.Frame(self, bg=PANEL_BG)
        row.pack(fill="both", expand=True, pady=(0, 10))

        # 1. Source Audio Card
        src_card = tk.Frame(row, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        src_card.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(src_card, text="1. File Âm thanh Nguồn (Source Audio)", font=(UI_FONT, 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        
        self.vc_src_var = tk.StringVar(value="Chưa chọn file nguồn...")

        drop_src = tk.Button(src_card, text="🎵 Kéo-thả file hoặc bấm để chọn\n(WAV · MP3 · FLAC — tối đa 5 phút)",
                             font=(UI_FONT, 10), bg="#0e1621", fg=TEXT_DIM_COLOR,
                             activebackground="#0e1621", activeforeground=TEXT_COLOR,
                             bd=1, relief="groove", cursor="hand2", pady=24,
                             command=self._pick_vc_src)
        drop_src.pack(fill="x", padx=14, pady=6)

        tk.Label(src_card, textvariable=self.vc_src_var, bg="#0e1621", fg=TEXT_COLOR, font=(UI_FONT, 9),
                 anchor="w", relief="solid", bd=1, highlightthickness=0, padx=8, pady=5).pack(fill="x", padx=14, pady=4)

        self.vc_src_waveform = WaveformCanvas(src_card, height=34)
        self.vc_src_waveform.pack(fill="x", padx=14, pady=(4, 12))

        # 2. Target Voice Card
        tgt_card = tk.Frame(row, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        tgt_card.pack(side="right", fill="both", expand=True, padx=(8, 0))

        tk.Label(tgt_card, text="2. File Giọng Mẫu Đích (Target Voice)", font=(UI_FONT, 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        
        self.vc_tgt_var = tk.StringVar(value="Chưa chọn file giọng mẫu đích...")

        drop_tgt = tk.Button(tgt_card, text="🎯 Kéo-thả file hoặc bấm để chọn\n(WAV · MP3 · FLAC)",
                             font=(UI_FONT, 10), bg="#0e1621", fg=TEXT_DIM_COLOR,
                             activebackground="#0e1621", activeforeground=TEXT_COLOR,
                             bd=1, relief="groove", cursor="hand2", pady=24,
                             command=self._pick_vc_tgt)
        drop_tgt.pack(fill="x", padx=14, pady=6)

        tk.Label(tgt_card, textvariable=self.vc_tgt_var, bg="#0e1621", fg="#a7f3d0", font=(UI_FONT, 9),
                 anchor="w", relief="solid", bd=1, highlightthickness=0, padx=8, pady=5).pack(fill="x", padx=14, pady=4)

        self.vc_tgt_waveform = WaveformCanvas(tgt_card, height=34)
        self.vc_tgt_waveform.pack(fill="x", padx=14, pady=(4, 12))

        # Strength Control Card
        str_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        str_card.pack(fill="x", pady=(0, 14))

        self.vc_str_lbl = tk.Label(str_card, text="Conversion Strength: 0.70", font=(UI_FONT, 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.vc_str_lbl.pack(anchor="w", padx=14, pady=(8, 0))

        self.vc_str_var = tk.DoubleVar(value=0.7)
        tk.Scale(str_card, variable=self.vc_str_var, from_=0.1, to=1.0, resolution=0.05,
                 orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                 troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                 command=lambda v: self.vc_str_lbl.config(text=f"Conversion Strength: {float(v):.2f}")).pack(fill="x", padx=14, pady=(0, 10))

        # Toolbar
        tb = tk.Frame(self, bg=PANEL_BG)
        tb.pack(fill="x")

        self.vc_convert_btn = tk.Button(tb, text=f"🔁 Chuyển Đổi Giọng  {self.main_window.shortcut_label}+↵", font=(UI_FONT, 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                                        activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, padx=16, pady=7, cursor="hand2",
                                        command=self.convert_action)
        self.vc_convert_btn.pack(side="left", padx=(0, 8))

        self.vc_play_btn = tk.Button(tb, text="▶ Nghe Kết Quả", font=(UI_FONT, 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                     activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                                     padx=14, pady=6, cursor="hand2",
                                     command=self.play_action, state="disabled")
        self.vc_play_btn.pack(side="left", padx=(0, 8))

        self.vc_save_btn = tk.Button(tb, text="💾 Lưu File WAV", font=(UI_FONT, 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                     activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                                     padx=14, pady=6, cursor="hand2",
                                     command=self.save_action, state="disabled")
        self.vc_save_btn.pack(side="left")

    def _pick_vc_src(self):
        path = filedialog.askopenfilename(title="Chọn file âm thanh nguồn", filetypes=[("Audio files", "*.wav *.flac *.mp3")])
        if path:
            self.vc_src_path = path
            self.vc_src_var.set(os.path.basename(path))
            self.vc_src_waveform.set_audio_file(path)

    def _pick_vc_tgt(self):
        path = filedialog.askopenfilename(title="Chọn file giọng mẫu đích", filetypes=[("Audio files", "*.wav *.flac *.mp3")])
        if path:
            self.vc_tgt_path = path
            self.vc_tgt_var.set(os.path.basename(path))
            self.vc_tgt_waveform.set_audio_file(path)

    def convert_action(self):
        if not self.vc_src_path or not os.path.exists(self.vc_src_path):
            messagebox.showwarning("Thiếu file nguồn", "Vui lòng chọn File Âm thanh Nguồn (Source Audio).")
            return

        if not self.vc_tgt_path or not os.path.exists(self.vc_tgt_path):
            messagebox.showwarning("Thiếu file mẫu đích", "Vui lòng chọn File Giọng Mẫu Đích (Target Voice).")
            return

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=str(TMP_DIR))
        os.close(tmp_fd)

        def callback(success, result):
            set_button_busy(self.vc_convert_btn, False, f"🔁 Chuyển Đổi Giọng  {self.main_window.shortcut_label}+↵", "⏳ Đang chuyển đổi…")
            if success:
                self.vc_last_result_path = tmp_path
                self.main_window.add_to_history(tmp_path, f"VC: {os.path.basename(self.vc_src_path)}")
                self.main_window.set_status("✓ Chuyển đổi giọng hoàn tất!", progress=100)
                self.vc_play_btn.config(state="normal")
                self.vc_save_btn.config(state="normal")
                messagebox.showinfo("Thành công", "Đã chuyển đổi giọng nói hoàn tất! Bạn có thể nghe thử hoặc lưu file.")
            else:
                self.main_window.set_status("❌ Lỗi Voice Conversion.", progress=None)
                messagebox.showerror("Lỗi", str(result))

        self.main_window.set_status("⏳ Đang thực hiện chuyển đổi giọng nói (Voice Conversion)...", progress="indeterminate")
        set_button_busy(self.vc_convert_btn, True, f"🔁 Chuyển Đổi Giọng  {self.main_window.shortcut_label}+↵", "⏳ Đang chuyển đổi…")
        run_in_background(
            self.engine.convert_voice,
            callback,
            self,
            src_path=self.vc_src_path,
            tgt_path=self.vc_tgt_path,
            out_path=tmp_path
        )

    def play_action(self):
        if self.vc_last_result_path and os.path.exists(self.vc_last_result_path):
            self.engine.play_audio(self.vc_last_result_path)

    def save_action(self):
        if not self.vc_last_result_path or not os.path.exists(self.vc_last_result_path):
            return

        save_path = filedialog.asksaveasfilename(initialdir=DEFAULT_EXPORT_DIR, defaultextension=".wav", filetypes=[("WAV audio", "*.wav")])
        if save_path:
            import shutil
            try:
                shutil.copyfile(self.vc_last_result_path, save_path)
                self.main_window.add_to_history(save_path, "VC Result")
                messagebox.showinfo("Thành công", f"Đã lưu file kết quả tại:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Lỗi", str(e))
