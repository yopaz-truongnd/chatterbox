"""
Khung cửa sổ chính main_window.py lắp ráp toàn bộ giao diện và quản lý các Tabs
"""

import os
import json
import tkinter as tk
import torch
from tkinter import ttk, messagebox
from config.constants import *
from utils.logger import logger
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu, setup_global_keyboard_shortcuts
from ui.tabs.tts_tab import TtsTab
from ui.tabs.batch_tab import BatchTab
from ui.tabs.mtl_tab import MtlTab
from ui.tabs.vc_tab import VcTab
from ui.tabs.character_tab import CharacterTab
from ui.tabs.history_tab import HistoryTab
from ui.tabs.settings_tab import SettingsTab
from utils.platform_tools import primary_shortcut
from ui.button_styles import apply_button_theme

class MainWindow:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        self.model_loading = False
        self.shortcut_modifier, self.shortcut_label = primary_shortcut()

        # Đăng ký phím tắt chỉnh sửa văn bản theo hệ điều hành.
        setup_global_keyboard_shortcuts(self.root)

        # Load voice presets
        self.presets = self._load_presets()

        # Session history list
        self.history = []

        self._build_ui()
        apply_button_theme(self.root)
        self._switch_tab("tts", force=True)
        self._register_keyboard_shortcuts()
        self.set_status("Sẵn sàng · Model sẽ được tải khi bạn yêu cầu.")

    def _build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg=BG_COLOR, padx=22, pady=12)
        header.pack(fill="x")

        brand = tk.Frame(header, bg=BG_COLOR)
        brand.pack(side="left")

        logo = tk.Label(brand, text="🎙️", font=(UI_FONT, 15), bg=ACCENT_COLOR, fg="#ffffff",
                        width=2, height=1, bd=0, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))

        title_box = tk.Frame(brand, bg=BG_COLOR)
        title_box.pack(side="left")
        tk.Label(title_box, text="CHATTERBOX TTS STUDIO", font=(UI_FONT, 13, "bold"), fg=TEXT_COLOR, bg=BG_COLOR).pack(anchor="w")
        tk.Label(title_box, text="Studio tạo & chuyển đổi giọng nói AI", font=(UI_FONT, 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR).pack(anchor="w")

        # Active device status
        self.device_lbl = tk.Label(header, text="🟢 Device: CPU", font=(MONO_FONT, 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR)
        self.device_lbl.pack(side="right")
        self._update_device_lbl()

        self.model_lbl = tk.Label(header, text="Model: Chưa tải", font=(UI_FONT, 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR)
        self.model_lbl.pack(side="right", padx=(0, 16))

        # 3. Custom Tabs Bar (High-Contrast Material 3 Pill Tabs)
        self.tabs_bar = tk.Frame(self.root, bg=BG_COLOR, padx=22, pady=4)
        self.tabs_bar.pack(fill="x")

        self.tab_widgets = {}
        tabs_config = [
            ("tts", "🗣️ TTS Studio"),
            ("batch", "📦 Batch Studio"),
            ("mtl", "🌐 Multilingual TTS"),
            ("vc", "🔁 Voice Conversion"),
            ("characters", "🎭 Characters"),
            ("history", "📜 Lịch sử âm thanh"),
            ("settings", "⚙️ Cài đặt")
        ]

        self.active_tab = "tts"
        for code, label in tabs_config:
            is_active = (code == "tts")
            btn = tk.Button(self.tabs_bar, text=label, font=(UI_FONT, 10, "bold"),
                            bg=TAB_ACTIVE_BG if is_active else TAB_INACTIVE_BG,
                            fg=TAB_ACTIVE_FG if is_active else TAB_INACTIVE_FG,
                            activebackground=BUTTON_PRIMARY_ACTIVE if is_active else TAB_HOVER_BG,
                            activeforeground="#FFFFFF",
                            bd=1, relief="solid", highlightthickness=0,
                            highlightbackground=TAB_ACTIVE_BG if is_active else BORDER_COLOR,
                            padx=16, pady=7, cursor="hand2",
                            command=lambda c=code: self._switch_tab(c))
            btn.pack(side="left", padx=3)
            self.tab_widgets[code] = btn

        # Underline
        self.tab_line = tk.Frame(self.root, height=1, bg=BORDER_COLOR)
        self.tab_line.pack(fill="x", padx=22)

        # 4. Content Panel Frame
        self.panel_container = tk.Frame(self.root, bg=PANEL_BG)
        self.panel_container.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        # Instantiate Tabs
        self.tab_tts = TtsTab(self.panel_container, self.engine, self)
        self.tab_batch = BatchTab(self.panel_container, self.engine, self)
        self.tab_mtl = MtlTab(self.panel_container, self.engine, self)
        self.tab_vc = VcTab(self.panel_container, self.engine, self)
        self.tab_characters = CharacterTab(self.panel_container, self.engine, self)
        self.tab_history = HistoryTab(self.panel_container, self.engine, self)
        self.tab_settings = SettingsTab(self.panel_container, self.engine, self)

        self.panels = {
            "tts": self.tab_tts,
            "batch": self.tab_batch,
            "mtl": self.tab_mtl,
            "vc": self.tab_vc,
            "characters": self.tab_characters,
            "history": self.tab_history,
            "settings": self.tab_settings
        }

        # Show default active panel
        self.panels["tts"].pack(fill="both", expand=True)

        # 5. Footer status bar
        footer = tk.Frame(self.root, bg=BG_COLOR, padx=22, pady=8)
        footer.pack(fill="x", side="bottom")

        # Container bên trái chứa log và progress bar
        status_left = tk.Frame(footer, bg=BG_COLOR)
        status_left.pack(side="left", fill="x", expand=True)

        self.footer_status_lbl = tk.Label(status_left, text="Sẵn sàng.", font=(UI_FONT, 9), fg=TEXT_COLOR, bg=BG_COLOR, anchor="w")
        self.footer_status_lbl.pack(side="left", padx=(0, 10))

        # Progress bar container ở footer
        self.footer_prog_frame = tk.Frame(status_left, bg=BG_COLOR)
        
        # Style cho Progressbar ở footer
        style = ttk.Style()
        try:
            style.theme_use('default')
        except Exception:
            pass
        style.configure("Footer.Horizontal.TProgressbar", troughcolor=PANEL2_BG, background=ACCENT_COLOR, bordercolor=BG_COLOR, thickness=8)

        self.footer_prog_bar = ttk.Progressbar(
            self.footer_prog_frame,
            orient="horizontal",
            mode="indeterminate",
            length=180,
            style="Footer.Horizontal.TProgressbar"
        )
        self.footer_prog_bar.pack(side="left")

        self.footer_ver_lbl = tk.Label(footer, text=f"Chatterbox v1.2 · {self.engine.get_device().upper()} mode", font=(MONO_FONT, 9), fg=TEXT_DIM_COLOR, bg=BG_COLOR)
        self.footer_ver_lbl.pack(side="right")

    def _update_device_lbl(self):
        device = self.engine.get_device()
        device_text = f"🟢 Device: {device.upper()}"
        if device == "cuda":
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else ""
            device_text = f"🟢 Device: GPU ({gpu_name[:15]}...)"
        elif device == "mps":
            device_text = "🟢 Device: Apple Metal (MPS)"
        self.device_lbl.config(text=device_text)

    def _switch_tab(self, code, force=False):
        if code == self.active_tab and not force:
            return

        # Deactivate previous tab
        if not force:
            self.panels[self.active_tab].pack_forget()
            self.tab_widgets[self.active_tab].config(
                bg=TAB_INACTIVE_BG,
                fg=TAB_INACTIVE_FG,
                activebackground=TAB_HOVER_BG,
                activeforeground="#FFFFFF",
                highlightbackground=BORDER_COLOR
            )

        # Activate selected tab
        self.active_tab = code
        self.panels[self.active_tab].pack(fill="both", expand=True)
        self.tab_widgets[self.active_tab].config(
            bg=TAB_ACTIVE_BG,
            fg=TAB_ACTIVE_FG,
            activebackground=BUTTON_PRIMARY_ACTIVE,
            activeforeground="#FFFFFF",
            highlightbackground=TAB_ACTIVE_BG
        )

        if code == "characters":
            self.tab_characters.refresh_characters()

        logger.info("Chuyển sang Tab: %s", code.upper())

        # ---------------- Keyboard Shortcuts & Navigation ----------------
        self._register_keyboard_shortcuts()

    def _register_keyboard_shortcuts(self):
        """Đăng ký toàn bộ phím tắt bàn phím thông dụng"""
        modifier = self.shortcut_modifier
        for number, tab in enumerate(("tts", "batch", "mtl", "vc", "characters", "history", "settings"), 1):
            self.root.bind_all(f"<{modifier}-Key-{number}>", lambda e, code=tab: self._switch_tab(code))

        # Duyệt tab bằng phím bổ trợ chuẩn của hệ điều hành.
        self.root.bind_all(f"<{modifier}-Tab>", lambda e: self._cycle_tab(1))
        self.root.bind_all(f"<{modifier}-Shift-Tab>", lambda e: self._cycle_tab(-1))

        # 2. Phím tắt thực thi hành động
        self.root.bind_all(f"<{modifier}-Return>", lambda e: self.shortcut_ctrl_enter())
        self.root.bind_all(f"<{modifier}-s>", lambda e: self.shortcut_ctrl_s())
        self.root.bind_all(f"<{modifier}-S>", lambda e: self.shortcut_ctrl_s())
        self.root.bind_all("<Escape>", lambda e: self.shortcut_escape())

        # 3. Phím F1 tra cứu phím tắt
        self.root.bind_all("<F1>", lambda e: self.show_shortcuts_cheat_sheet())

    def _cycle_tab(self, direction):
        codes = ["tts", "batch", "mtl", "vc", "characters", "history", "settings"]
        if self.active_tab in codes:
            idx = codes.index(self.active_tab)
            new_idx = (idx + direction) % len(codes)
            self._switch_tab(codes[new_idx])

    def shortcut_ctrl_enter(self):
        if self.active_tab == "tts":
            self.tab_tts.play_action()
        elif self.active_tab == "batch":
            self.tab_batch.run_batch_action()
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
        elif self.active_tab == "settings":
            self.tab_settings.save_settings_action()

    def shortcut_escape(self):
        if self.active_tab == "tts":
            self.tab_tts.stop_action()
        elif self.active_tab == "batch":
            self.tab_batch.audio_player.stop()
        elif self.active_tab == "mtl":
            self.tab_mtl.stop_action()
        elif self.active_tab == "vc":
            self.tab_vc.audio_player.stop()
        elif self.active_tab == "history":
            self.tab_history.audio_player.stop()

    def show_shortcuts_cheat_sheet(self):
        """Hiển thị cửa sổ Hướng dẫn / Tra cứu phím tắt bàn phím"""
        win = tk.Toplevel(self.root)
        win.title("⌨️ Bảng tra cứu phím tắt Chatterbox Studio")
        win.geometry("520x460")
        win.configure(bg=PANEL2_BG)
        win.resizable(False, False)

        tk.Label(win, text="⌨️ Danh sách phím tắt bàn phím thông dụng", font=(UI_FONT, 11, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG).pack(pady=12)

        table_frame = tk.Frame(win, bg=PANEL_BG, bd=1, relief="solid", highlightbackground=BORDER_COLOR)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        key = self.shortcut_label
        shortcuts = [
            (f"{key} + Enter", "Khởi chạy sinh giọng đọc / Batch Run"),
            (f"{key} + S", "Lưu file âm thanh hoặc Cài đặt hệ thống"),
            (f"{key} + A", "Chọn tất cả văn bản (Select All)"),
            (f"{key} + L", "Xóa sạch nội dung ô văn bản (Clear Text)"),
            (f"{key} + Backspace", "Xóa từ phía trước con trỏ"),
            (f"{key} + 1 .. 7", "Chuyển nhanh tới Tab tương ứng (5:Characters, 6:History, 7:Settings)"),
            (f"{key} + Tab", "Chuyển sang Tab tiếp theo"),
            (f"{key} + Shift + Tab", "Chuyển về Tab trước đó"),
            ("Escape (Esc)", "Dừng âm thanh đang phát ngay lập tức"),
            ("Chuột phải (Right Click)", "Mở Menu sao chép/dán/cắt (Tự đóng khi click ngoài)"),
            ("F1", "Mở bảng tra cứu phím tắt này")
        ]

        for k, d in shortcuts:
            r = tk.Frame(table_frame, bg=PANEL_BG)
            r.pack(fill="x", padx=12, pady=4)
            tk.Label(r, text=k, font=(MONO_FONT, 9, "bold"), fg=ACCENT_COLOR, bg=PANEL_BG, width=18, anchor="w").pack(side="left")
            tk.Label(r, text=d, font=(UI_FONT, 9), fg=TEXT_COLOR, bg=PANEL_BG, anchor="w").pack(side="left", fill="x", expand=True)

        tk.Button(win, text="Đóng (Close)", font=(UI_FONT, 9, "bold"), bg=BUTTON_PRIMARY_BG, fg="#ffffff",
                  activebackground=BUTTON_PRIMARY_ACTIVE, activeforeground="#ffffff",
                  bd=0, padx=16, pady=5, cursor="hand2", command=win.destroy).pack(pady=(0, 12))

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
        if self.model_loading:
            self.set_status("⏳ Một model đang được tải, vui lòng chờ...", progress="indeterminate")
            return
        self.model_loading = True
        self.set_status(f"⏳ Đang tải model '{model_name}'...", progress="indeterminate")

        def on_done(success, result):
            self.model_loading = False
            if success:
                self._update_model_lbl()
                self.set_status(f"✓ Tải model hoàn tất! ({model_name})", progress=100)
            else:
                self.set_status("❌ Lỗi tải model.", progress=None)
                messagebox.showerror("Lỗi Tải Model", str(result))

        # Tải mô hình thông qua bộ trợ giúp đa luồng bất đồng bộ
        run_in_background(self.engine.load_model, on_done, self.root, model_name=model_name, extra_args=extra_args)

    def set_status(self, msg, progress=None):
        """
        Cập nhật log trạng thái xử lý cuối cùng và thanh tiến trình ở Footer.
        - msg: Chuỗi văn bản trạng thái hiển thị
        - progress:
            + None hoặc False: Ẩn thanh tiến trình.
            + 'indeterminate' hoặc True: Chạy thanh tiến trình dạng marquee (đang tải).
            + int / float (0..100): Hiển thị phần trăm tiến độ cụ thể.
        """
        import threading
        def _update():
            self._update_model_lbl()
            self.footer_status_lbl.config(text=msg)

            if progress is None or progress is False:
                self.footer_prog_bar.stop()
                self.footer_prog_frame.pack_forget()
            elif progress == 'indeterminate' or progress is True:
                if not self.footer_prog_frame.winfo_ismapped():
                    self.footer_prog_frame.pack(side="left", padx=(0, 10))
                self.footer_prog_bar.config(mode="indeterminate")
                self.footer_prog_bar.start(10)
            elif isinstance(progress, (int, float)):
                if not self.footer_prog_frame.winfo_ismapped():
                    self.footer_prog_frame.pack(side="left", padx=(0, 10))
                self.footer_prog_bar.stop()
                self.footer_prog_bar.config(mode="determinate")
                self.footer_prog_bar['value'] = progress
                if progress >= 100:
                    self.root.after(1500, self._auto_hide_progress)

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)

    def _update_model_lbl(self):
        if hasattr(self, "model_lbl"):
            name = self.engine.active_model_name or "Chưa tải"
            self.model_lbl.config(text=f"Model: {name}")

    def _auto_hide_progress(self):
        try:
            if hasattr(self, 'footer_prog_bar') and self.footer_prog_bar['value'] >= 100:
                self.footer_prog_frame.pack_forget()
        except Exception:
            pass

    # ---------------- History Helpers ----------------
    def add_to_history(self, file_path, text_preview=""):
        item = f"{text_preview} | {os.path.basename(file_path)}"
        if file_path not in [h['path'] for h in self.history]:
            import time
            curr_time = time.strftime("%H:%M:%S %d/%m/%Y")
            self.history.append({'path': file_path, 'label': item, 'text': text_preview, 'time': curr_time})
            if hasattr(self, 'tab_history'):
                self.tab_history.refresh_history_ui()

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
