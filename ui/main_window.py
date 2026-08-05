"""
Khung cửa sổ chính main_window.py lắp ráp toàn bộ giao diện và quản lý các Tabs
"""

import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
from config.constants import *
from utils.logger import logger
from utils.threading_helper import run_in_background
from ui.tabs.tts_tab import TtsTab
from ui.tabs.mtl_tab import MtlTab
from ui.tabs.vc_tab import VcTab
from ui.tabs.batch_tab import BatchTab

class MainWindow:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine

        # Load voice presets
        self.presets = self._load_presets()

        # Session history list
        self.history = []

        self._build_ui()

        # Tự động tải model mặc định khi khởi chạy
        self.load_model("Chatterbox Standard (500M)")

    def _build_ui(self):
        # 1. Simulated Custom Title bar
        titlebar = tk.Frame(self.root, bg=BG_COLOR, height=32)
        titlebar.pack(fill="x", side="top")
        
        tb_left = tk.Frame(titlebar, bg=BG_COLOR)
        tb_left.pack(side="left", padx=16)
        dot = tk.Label(tb_left, text="●", fg=ACCENT_COLOR, bg=BG_COLOR, font=("Segoe UI", 10))
        dot.pack(side="left", padx=(0, 6))
        tk.Label(tb_left, text="Chatterbox TTS Studio — Professional Voice AI", fg=TEXT_DIM_COLOR, bg=BG_COLOR, font=("Segoe UI", 9)).pack(side="left")

        # Window controls placeholder
        win_ctrls = tk.Frame(titlebar, bg=BG_COLOR)
        win_ctrls.pack(side="right", padx=16)
        for i in range(3):
            tk.Label(win_ctrls, text="●", fg="#243149", bg=BG_COLOR, font=("Segoe UI", 8)).pack(side="left", padx=2)

        # 2. Header
        header = tk.Frame(self.root, bg=BG_COLOR, padx=22, pady=12)
        header.pack(fill="x")

        brand = tk.Frame(header, bg=BG_COLOR)
        brand.pack(side="left")

        logo = tk.Label(brand, text="🎙️", font=("Segoe UI", 16), bg="#1c3a73", fg="#ffffff",
                        width=2, height=1, bd=0, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))

        title_box = tk.Frame(brand, bg=BG_COLOR)
        title_box.pack(side="left")
        tk.Label(title_box, text="CHATTERBOX TTS STUDIO", font=("Segoe UI", 13, "bold"), fg="#eef3fb", bg=BG_COLOR).pack(anchor="w")
        tk.Label(title_box, text="Mockup giao diện cải tiến — bản đề xuất", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR).pack(anchor="w")

        # Active device status
        self.device_lbl = tk.Label(header, text="🟢 Device: CPU", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR)
        self.device_lbl.pack(side="right")
        self._update_device_lbl()

        # 3. Custom Tabs Bar
        self.tabs_bar = tk.Frame(self.root, bg=BG_COLOR, padx=22)
        self.tabs_bar.pack(fill="x")

        self.tab_widgets = {}
        tabs_config = [
            ("tts", "🗣️ TTS Studio"),
            ("mtl", "🌐 Multilingual TTS"),
            ("vc", "🔁 Voice Conversion"),
            ("batch", "📦 Batch & History")
        ]

        self.active_tab = "tts"
        for code, label in tabs_config:
            btn = tk.Button(self.tabs_bar, text=label, font=("Segoe UI", 10, "bold"),
                            bg=PANEL_BG if code == "tts" else BG_COLOR,
                            fg="#ffffff" if code == "tts" else TEXT_DIM_COLOR,
                            activebackground=PANEL_BG, activeforeground="#ffffff",
                            bd=0, padx=16, pady=8, cursor="hand2",
                            command=lambda c=code: self._switch_tab(c))
            btn.pack(side="left", padx=2)
            self.tab_widgets[code] = btn

        # Underline
        self.tab_line = tk.Frame(self.root, height=1, bg="#1a2534")
        self.tab_line.pack(fill="x", padx=22)

        # 4. Content Panel Frame
        self.panel_container = tk.Frame(self.root, bg=PANEL_BG)
        self.panel_container.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        # Instantiate Tabs
        self.tab_tts = TtsTab(self.panel_container, self.engine, self)
        self.tab_mtl = MtlTab(self.panel_container, self.engine, self)
        self.tab_vc = VcTab(self.panel_container, self.engine, self)
        self.tab_batch = BatchTab(self.panel_container, self.engine, self)

        self.panels = {
            "tts": self.tab_tts,
            "mtl": self.tab_mtl,
            "vc": self.tab_vc,
            "batch": self.tab_batch
        }

        # Show default active panel
        self.panels["tts"].pack(fill="both", expand=True)

        # 5. Footer status bar
        footer = tk.Frame(self.root, bg="#0a0f17", padx=22, pady=8)
        footer.pack(fill="x", side="bottom")

        self.footer_status_lbl = tk.Label(footer, text="Sẵn sàng.", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg="#0a0f17")
        self.footer_status_lbl.pack(side="left")

        self.footer_ver_lbl = tk.Label(footer, text=f"Chatterbox v1.2 · {self.engine.get_device().upper()} mode", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg="#0a0f17")
        self.footer_ver_lbl.pack(side="right")

    def _update_device_lbl(self):
        device = self.engine.get_device()
        device_text = f"🟢 Device: {device.upper()}"
        if device == "cuda":
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else ""
            device_text = f"🟢 Device: GPU ({gpu_name[:15]}...)"
        self.device_lbl.config(text=device_text)

    def _switch_tab(self, code):
        if code == self.active_tab:
            return

        self.panels[self.active_tab].pack_forget()
        self.tab_widgets[self.active_tab].config(bg=BG_COLOR, fg=TEXT_DIM_COLOR)

        self.active_tab = code
        self.panels[self.active_tab].pack(fill="both", expand=True)
        self.tab_widgets[self.active_tab].config(bg=PANEL_BG, fg="#ffffff")

        logger.info("Chuyển sang Tab: %s", code.upper())

    # ---------------- Shortcuts ----------------
    def shortcut_ctrl_enter(self):
        if self.active_tab == "tts":
            self.tab_tts.play_action()
        elif self.active_tab == "mtl":
            self.tab_mtl.play_action()
        elif self.active_tab == "vc":
            self.tab_vc.convert_action()

    def shortcut_ctrl_s(self):
        if self.active_tab == "tts":
            self.tab_tts.save_action()
        elif self.active_tab == "mtl":
            self.tab_mtl.save_action()
        elif self.active_tab == "vc":
            self.tab_vc.save_action()

    # ---------------- Presets ----------------
    def _load_presets(self):
        if PRESETS_FILE.exists():
            try:
                with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_presets(self, presets):
        self.presets = presets
        try:
            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, ensure_ascii=False, indent=2)
            # Đồng bộ presets sang Combobox của Tab TTS
            self.tab_tts.preset_cb['values'] = list(self.presets.keys())
        except Exception as e:
            logger.error("Lỗi khi lưu voice presets: %s", e)

    # ---------------- Model loader helper ----------------
    def load_model(self, model_name, extra_args=None):
        def on_done(success, result):
            if success:
                self.set_status(f"Sẵn sàng! Model hiện tại: {model_name} ({self.engine.get_device().upper()})")
            else:
                self.set_status("Lỗi tải model.")
                messagebox.showerror("Lỗi Tải Model", str(result))

        # Tải mô hình thông qua bộ trợ giúp đa luồng bất đồng bộ
        run_in_background(self.engine.load_model, on_done, self.root, model_name=model_name, extra_args=extra_args)

    def set_status(self, msg):
        self.footer_status_lbl.config(text=msg)

    # ---------------- History Helpers ----------------
    def add_to_history(self, file_path, text_preview=""):
        item = f"{text_preview} | {os.path.basename(file_path)}"
        if file_path not in [h['path'] for h in self.history]:
            self.history.append({'path': file_path, 'label': item})
            self.tab_batch.refresh_history_ui()

    def remove_from_history(self, label):
        self.history = [h for h in self.history if h['label'] != label]

    # ---------------- Parameters Getter (for Batch tab) ----------------
    def get_active_model_name(self):
        return self.tab_tts.tts_model_var.get()

    def get_ref_audio_path(self):
        return self.tab_tts.ref_audio_path

    def get_exag_val(self):
        return self.tab_tts.exag_var.get()

    def get_cfg_val(self):
        return self.tab_tts.cfg_var.get()

    def get_temp_val(self):
        return self.tab_tts.temp_var.get()

    def get_seed_val(self):
        return self.tab_tts.seed_var.get()

    def get_random_seed_val(self):
        return self.tab_tts.random_seed_var.get()
