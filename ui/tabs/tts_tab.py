"""
Tab 1: TTS Studio (English & Paralinguistic Tags)
"""

import os
import time
import random
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from config.constants import *
import shutil
from ui.components.audio_player import AudioPlayerWidget
from ui.components.waveform_canvas import WaveformCanvas
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu

class TtsTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        self.presets = main_window.presets
        
        self.ref_audio_path = None
        self.last_temp_wav = None

        self._build_ui()

    def _build_ui(self):
        # Top Model Selector Card
        model_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        model_card.pack(fill="x", side="top", pady=(0, 14))

        tk.Label(model_card, text="Chọn Mô hình (Model)", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))
        
        sel_row = tk.Frame(model_card, bg=PANEL2_BG)
        sel_row.pack(fill="x", padx=14, pady=(0, 10))

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

        # Split left/right pane
        left_pane = tk.Frame(self, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(self, bg=PANEL_BG, width=320)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # LEFT PANE
        # Text input card
        text_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        text_card.pack(fill="both", expand=True, pady=(0, 10))

        title_lbl = tk.Label(text_card, text="Văn bản cần phát âm", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG)
        title_lbl.pack(anchor="w", padx=14, pady=(10, 4))

        self.tts_text_box = tk.Text(text_card, height=7, font=("Segoe UI", 11), bg="#0e1621", fg=TEXT_COLOR,
                                    bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                    insertbackground="white")
        self.tts_text_box.pack(fill="both", expand=True, padx=14, pady=4)
        self.tts_text_box.insert("1.0", "Hello there! Welcome to Chatterbox TTS Studio [chuckle]. This model supports high quality zero-shot voice cloning.")
        self.tts_text_box.bind("<KeyRelease>", self._update_char_count)
        bind_right_click_menu(self.tts_text_box)

        self.tts_char_lbl = tk.Label(text_card, text="128 / 1000 ký tự", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.tts_char_lbl.pack(anchor="e", padx=14, pady=(0, 6))

        # Tags Section
        tag_lbl = tk.Label(text_card, text="Chèn nhanh biểu cảm (Paralinguistic Tags)", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        tag_lbl.pack(anchor="w", padx=14, pady=(2, 2))

        self.tags_frame = tk.Frame(text_card, bg=PANEL2_BG)
        self.tags_frame.pack(fill="x", padx=14, pady=(2, 8))

        # Phân chia 11 tag thành các hàng
        tags_list = list(PARALINGUISTIC_TAGS.items())
        chunks = [tags_list[i:i + 4] for i in range(0, len(tags_list), 4)]
        
        for chunk in chunks:
            row_frame = tk.Frame(self.tags_frame, bg=PANEL2_BG)
            row_frame.pack(fill="x", pady=2)
            for tag, desc in chunk:
                lbl = tk.Label(row_frame, text=f"{tag} - {desc}", bg="#192c4b", fg="#a9c3ff",
                               font=("Segoe UI", 9), padx=8, pady=4, cursor="hand2",
                               bd=1, relief="solid", highlightbackground=BORDER_COLOR)
                lbl.pack(side="left", padx=3)
                lbl.bind("<Button-1>", lambda e, t=tag: self._insert_tag(self.tts_text_box, t))

        # Khối Audio Player kiểu HTML5 (Ẩn mặc định khi chưa render voice)
        self.audio_player = AudioPlayerWidget(left_pane, self.engine, on_delete=self._on_audio_deleted)
        self.audio_player.pack_forget()

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

        tk.Button(self.tb, text="💾 Lưu File WAV  Ctrl+S", font=("Segoe UI", 10, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  activebackground="#2563eb", activeforeground="#ffffff", bd=1, relief="solid", highlightcolor=BORDER_COLOR,
                  padx=14, pady=6, cursor="hand2",
                  command=self.save_action).pack(side="left")

        # Progress Block
        self.prog_wrap = tk.Frame(left_pane, bg=PANEL_BG, pady=6)
        self.prog_wrap.pack(fill="x")
        self.tts_prog_lbl = tk.Label(self.prog_wrap, text="Sẵn sàng.", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL_BG)
        self.tts_prog_lbl.pack(anchor="w", pady=(2, 2))
        self.tts_prog_bar = ttk.Progressbar(self.prog_wrap, orient="horizontal", mode="determinate")
        self.tts_prog_bar.pack(fill="x")

        # RIGHT PANE
        # 1. Voice Clone Card
        vc_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        vc_card.pack(fill="x", pady=(0, 10))

        tk.Label(vc_card, text="Giọng mẫu (Voice Cloning)", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        
        self.ref_audio_var = tk.StringVar(value="Mặc định (Default Speaker)")
        tk.Label(vc_card, textvariable=self.ref_audio_var, bg="#0e1621", fg="#a7f3d0", font=("Segoe UI", 9),
                 anchor="w", relief="solid", bd=1, highlightthickness=0, padx=8, pady=5).pack(fill="x", padx=14, pady=4)

        self.tts_waveform = WaveformCanvas(vc_card, height=34)
        self.tts_waveform.pack(fill="x", padx=14, pady=4)

        ref_btns = tk.Frame(vc_card, bg=PANEL2_BG)
        ref_btns.pack(fill="x", padx=14, pady=4)
        tk.Button(ref_btns, text="📁 Chọn file...", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=10, pady=4,
                  command=self._pick_ref_audio).pack(side="left", padx=(0, 6))
        tk.Button(ref_btns, text="✕ Bỏ chọn", font=("Segoe UI", 9), bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                  bd=0, activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, cursor="hand2",
                  command=self._clear_ref_audio).pack(side="left")

        # Preset Row
        tk.Label(vc_card, text="Preset đã lưu", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(6, 2))
        self.preset_cb_var = tk.StringVar(value="-- Chọn Preset --")
        self.preset_cb = ttk.Combobox(vc_card, textvariable=self.preset_cb_var, state="readonly")
        self.preset_cb["values"] = list(self.presets.keys())
        self.preset_cb.pack(fill="x", padx=14, pady=4)
        self.preset_cb.bind("<<ComboboxSelected>>", self._on_select_preset)

        tk.Button(vc_card, text="⭐ Lưu file hiện tại thành Preset", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", pady=5,
                  command=self._save_current_as_preset).pack(fill="x", padx=14, pady=(4, 12))

        # 2. Preset Combos Pill Box
        pills_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        pills_card.pack(fill="x", pady=(0, 10))

        tk.Label(pills_card, text="Combo thông số nhanh", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))
        pills_frame = tk.Frame(pills_card, bg=PANEL2_BG)
        pills_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.pill_btns = {}
        for name, ex, cfg, tm in PRESET_COMBOS:
            btn = tk.Button(pills_frame, text=name, font=("Segoe UI", 9, "bold"),
                            bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                            activebackground=PANEL2_BG, activeforeground=TEXT_COLOR,
                            bd=1, relief="solid", highlightbackground=BORDER_COLOR, padx=8, pady=4, cursor="hand2",
                            command=lambda n=name, e=ex, c=cfg, t=tm: self._apply_preset_combo_ui(n, e, c, t))
            btn.pack(side="left", padx=2, pady=2)
            self.pill_btns[name] = btn

        # 3. Parameters
        params_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        params_card.pack(fill="x")

        tk.Label(params_card, text="Thông số sinh âm thanh", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))

        # Exaggeration
        self.exag_lbl_val = tk.StringVar(value="0.50")
        ex_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        ex_hdr.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(ex_hdr, text="Độ biểu cảm (Exaggeration) i", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(ex_hdr, textvariable=self.exag_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.exag_var = tk.DoubleVar(value=0.5)
        exag_scale = tk.Scale(params_card, variable=self.exag_var, from_=0.0, to=1.5, resolution=0.05,
                              orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                              troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                              command=lambda v: self.exag_lbl_val.set(f"{float(v):.2f}"))
        exag_scale.pack(fill="x", padx=14, pady=(0, 8))

        # CFG
        self.cfg_lbl_val = tk.StringVar(value="0.50")
        cfg_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        cfg_hdr.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(cfg_hdr, text="Bám sát văn bản (CFG Weight) i", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(cfg_hdr, textvariable=self.cfg_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.cfg_var = tk.DoubleVar(value=0.5)
        cfg_scale = tk.Scale(params_card, variable=self.cfg_var, from_=0.0, to=1.0, resolution=0.05,
                             orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                             troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                             command=lambda v: self.cfg_lbl_val.set(f"{float(v):.2f}"))
        cfg_scale.pack(fill="x", padx=14, pady=(0, 8))

        # Temp
        self.temp_lbl_val = tk.StringVar(value="0.80")
        temp_hdr = tk.Frame(params_card, bg=PANEL2_BG)
        temp_hdr.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(temp_hdr, text="Nhiệt độ (Temperature) i", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        tk.Label(temp_hdr, textvariable=self.temp_lbl_val, font=("Segoe UI", 9, "bold"), fg=ACCENT_COLOR, bg=PANEL2_BG).pack(side="right")

        self.temp_var = tk.DoubleVar(value=0.8)
        temp_scale = tk.Scale(params_card, variable=self.temp_var, from_=0.1, to=1.5, resolution=0.05,
                              orient="horizontal", bg=PANEL2_BG, fg=ACCENT_COLOR, highlightthickness=0, bd=0,
                              troughcolor="#0e1621", activebackground=ACCENT_COLOR,
                              command=lambda v: self.temp_lbl_val.set(f"{float(v):.2f}"))
        temp_scale.pack(fill="x", padx=14, pady=(0, 8))

        # Seed Row
        seed_row = tk.Frame(params_card, bg=PANEL2_BG)
        seed_row.pack(fill="x", padx=14, pady=(4, 12))
        
        tk.Label(seed_row, text="Seed", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        
        self.seed_var = tk.IntVar(value=0)
        self.seed_entry = tk.Entry(seed_row, textvariable=self.seed_var, width=10, bg="#0e1621", fg=TEXT_COLOR,
                                   bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.seed_entry.pack(side="right", padx=(6, 0))
        bind_right_click_menu(self.seed_entry)

        self.random_seed_var = tk.BooleanVar(value=True)
        tk.Checkbutton(seed_row, text="Ngẫu nhiên", variable=self.random_seed_var,
                       bg=PANEL2_BG, fg=TEXT_DIM_COLOR, selectcolor="#0e1621",
                       activebackground=PANEL2_BG, activeforeground=TEXT_COLOR).pack(side="right", padx=6)

        # Apply default combo parameters
        self._apply_preset_combo_ui("Đọc tin tức", 0.3, 0.7, 0.6)

    def _on_model_change(self):
        m_name = self.tts_model_var.get()
        self.main_window.load_model(m_name)

    def _apply_preset_combo_ui(self, name, ex, cfg, temp):
        # Update pills visual active state
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



    def _update_char_count(self, event=None):
        text = self.tts_text_box.get("1.0", "end-1c")
        length = len(text)
        self.tts_char_lbl.config(text=f"{length} / 1000 ký tự")

    def _insert_tag(self, text_widget, tag):
        try:
            text_widget.insert(tk.INSERT, f" {tag} ")
            text_widget.focus_set()
            self._update_char_count()
        except Exception:
            pass

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

    # ---------------- Async Actions ----------------
    def _on_audio_deleted(self):
        self.last_temp_wav = None
        try:
            self.audio_player.pack_forget()
        except Exception:
            pass
        self.main_window.set_status("🗑 Đã xóa file âm thanh tạm thời và reset trình phát.", progress=None)

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

        m_name = self.tts_model_var.get()
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)

        def callback(success, result):
            if success:
                self.last_temp_wav = tmp_path
                try:
                    self.audio_player.pack(fill="x", pady=(0, 10), before=self.tb)
                except Exception:
                    pass
                self.audio_player.load_audio(tmp_path)
                self.audio_player.play()
                self.main_window.set_status("▶ Đang phát âm thanh...", progress=None)
            else:
                self.main_window.set_status("❌ Lỗi sinh giọng đọc.", progress=None)
                messagebox.showerror("Lỗi", str(result))

        self.gen_start_time = time.time()

        # Gọi Engine chạy trên luồng nền
        run_in_background(
            self.engine.generate_tts,
            callback,
            self,
            text=text,
            ref_path=self.ref_audio_path,
            model_name=m_name,
            exag=self.exag_var.get(),
            cfg=self.cfg_var.get(),
            temp=self.temp_var.get(),
            seed=self.seed_var.get(),
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

        text = self.tts_text_box.get("1.0", "end").strip()
        save_path = filedialog.asksaveasfilename(initialdir=DEFAULT_EXPORT_DIR, defaultextension=".wav", filetypes=[("WAV audio", "*.wav")])
        if not save_path:
            return

        try:
            shutil.copyfile(self.last_temp_wav, save_path)
            self.main_window.add_to_history(save_path, text[:40])
            self.main_window.set_status(f"✓ Đã lưu file: {save_path}", progress=None)
            messagebox.showinfo("Thành công", f"Đã lưu thành công file âm thanh tại:\n{save_path}")
        except Exception as e:
            self.main_window.set_status("❌ Lỗi khi lưu file.", progress=None)
            messagebox.showerror("Lỗi", str(e))
