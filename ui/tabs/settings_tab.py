"""
Tab 6: Cài đặt hệ thống (Project & System Settings Tab)
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config.constants import *
from config.settings import settings_manager
from utils.logger import logger
from utils.context_menu import bind_right_click_menu

class SettingsTab(tk.Frame):
    """Tab quản lý các thiết lập toàn dự án Chatterbox TTS Studio"""
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window

        self._build_ui()
        self.load_settings_to_ui()

    def _build_ui(self):
        # Header / Title Card
        hdr_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        hdr_card.pack(fill="x", pady=(0, 10))

        hdr_row = tk.Frame(hdr_card, bg=PANEL2_BG)
        hdr_row.pack(fill="x", padx=16, pady=10)

        tk.Label(hdr_row, text="⚙️ Cài đặt hệ thống (System & Project Settings)", font=("Segoe UI", 11, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")
        tk.Label(hdr_row, text="Tùy chỉnh cấu hình lưu trữ, mô hình và trải nghiệm", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="right")

        # Scrollable container or main container
        main_container = tk.Frame(self, bg=PANEL_BG)
        main_container.pack(fill="both", expand=True)

        # Content Card containing all setting sections
        content_card = tk.Frame(main_container, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        content_card.pack(fill="both", expand=True, padx=0, pady=0)

        # Canvas for scrolling if window is small
        canvas = tk.Canvas(content_card, bg=PANEL2_BG, bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_card, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=PANEL2_BG)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=16, pady=12)
        scrollbar.pack(side="right", fill="y")

        # SECTION 1: 📁 Cấu hình Đường dẫn & Lưu trữ (Storage & Paths)
        sec1 = self._create_section(scrollable_frame, "📁 Cấu hình Đường dẫn & Lưu trữ")

        # 1.1 Export Directory
        r1 = tk.Frame(sec1, bg=PANEL2_BG)
        r1.pack(fill="x", pady=6)
        tk.Label(r1, text="Thư mục xuất âm thanh mặc định:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.export_dir_var = tk.StringVar()
        self.export_dir_entry = tk.Entry(r1, textvariable=self.export_dir_var, font=("Segoe UI", 9), bg="#0e1621", fg=TEXT_COLOR,
                                         bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.export_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        bind_right_click_menu(self.export_dir_entry)
        tk.Button(r1, text="📁 Chọn...", font=("Segoe UI", 9), bg="#1d2b3e", fg=TEXT_COLOR, bd=1, relief="solid",
                  cursor="hand2", command=self._browse_export_dir).pack(side="right")

        # 1.2 Model Cache Directory
        r2 = tk.Frame(sec1, bg=PANEL2_BG)
        r2.pack(fill="x", pady=6)
        tk.Label(r2, text="Thư mục lưu Cache Model:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.model_cache_var = tk.StringVar()
        self.model_cache_entry = tk.Entry(r2, textvariable=self.model_cache_var, font=("Segoe UI", 9), bg="#0e1621", fg=TEXT_COLOR,
                                          bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.model_cache_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        bind_right_click_menu(self.model_cache_entry)
        tk.Button(r2, text="📁 Chọn...", font=("Segoe UI", 9), bg="#1d2b3e", fg=TEXT_COLOR, bd=1, relief="solid",
                  cursor="hand2", command=self._browse_model_cache_dir).pack(side="right")

        # 1.3 Auto-open Export Directory Checkbox
        self.auto_open_var = tk.BooleanVar()
        chk_auto_open = tk.Checkbutton(sec1, text="Tự động mở thư mục chứa file sau khi sinh âm thanh hoàn tất",
                                       variable=self.auto_open_var, font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG,
                                       activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, selectcolor="#0e1621")
        chk_auto_open.pack(anchor="w", pady=4)

        # SECTION 2: ⚡ Cấu hình Mô hình & Hiệu năng (Model & Inference)
        sec2 = self._create_section(scrollable_frame, "⚡ Mô hình & Hiệu năng")

        # 2.1 Device
        r3 = tk.Frame(sec2, bg=PANEL2_BG)
        r3.pack(fill="x", pady=6)
        tk.Label(r3, text="Thiết bị tính toán (Device):", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.device_var = tk.StringVar(value="auto")
        device_cb = ttk.Combobox(r3, textvariable=self.device_var, state="readonly", width=25,
                                 values=["auto (Tự động phát hiện)", "cuda (GPU Nvidia)", "mps (Apple Silicon)", "cpu (Vi xử lý CPU)"])
        device_cb.pack(side="left")

        # 2.2 Default Startup Model
        r4 = tk.Frame(sec2, bg=PANEL2_BG)
        r4.pack(fill="x", pady=6)
        tk.Label(r4, text="Mô hình mặc định khi nạp:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.startup_model_var = tk.StringVar()
        models_cb = ttk.Combobox(r4, textvariable=self.startup_model_var, state="readonly", width=35,
                                 values=[
                                     "Chatterbox Standard (500M)",
                                     "Chatterbox Turbo (350M - Fast)",
                                     "Chatterbox Nano (110M - Light/CPU)",
                                     "Multilingual V3 (500M)"
                                 ])
        models_cb.pack(side="left")

        # 2.3 Max Chunk Characters
        r5 = tk.Frame(sec2, bg=PANEL2_BG)
        r5.pack(fill="x", pady=6)
        tk.Label(r5, text="Số ký tự cắt đoạn tối đa (Max Chunk):", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.max_chunk_var = tk.IntVar(value=4000)
        chunk_spin = tk.Spinbox(r5, from_=100, to=10000, increment=100, textvariable=self.max_chunk_var, font=("Segoe UI", 9),
                                bg="#0e1621", fg=TEXT_COLOR, width=10, bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR)
        chunk_spin.pack(side="left")
        tk.Label(r5, text="ký tự (Mặc định: 4000 - Cắt nhỏ văn bản dài tránh tràn GPU VRAM)", font=("Segoe UI", 8), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=10)

        # 2.4 Auto Unload Models Checkbox
        self.auto_unload_var = tk.BooleanVar()
        chk_unload = tk.Checkbutton(sec2, text="Tự động giải phóng các mô hình cũ khỏi GPU VRAM khi đổi tab/mô hình",
                                    variable=self.auto_unload_var, font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG,
                                    activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, selectcolor="#0e1621")
        chk_unload.pack(anchor="w", pady=4)

        # SECTION 3: 🧠 Cấu hình Phần cứng & Khống chế Tài nguyên (Hardware Limits & Anti-Freeze)
        sec3 = self._create_section(scrollable_frame, "🧠 Cấu hình Phần cứng & Chống treo máy")

        # 3.1 CPU Threads Limit
        r6 = tk.Frame(sec3, bg=PANEL2_BG)
        r6.pack(fill="x", pady=6)
        tk.Label(r6, text="Giới hạn số Lõi/Luồng CPU sử dụng:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        max_cpus = os.cpu_count() or 8
        self.cpu_threads_var = tk.IntVar(value=min(4, max_cpus))
        threads_spin = tk.Spinbox(r6, from_=1, to=max_cpus, increment=1, textvariable=self.cpu_threads_var, font=("Segoe UI", 9),
                                  bg="#0e1621", fg=TEXT_COLOR, width=8, bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR)
        threads_spin.pack(side="left")
        tk.Label(r6, text=f"lõi (Tổng số lõi hệ thống: {max_cpus} - Giúp tránh 100% CPU gây đơ máy)", font=("Segoe UI", 8), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=10)

        # 3.2 Process Priority
        r7 = tk.Frame(sec3, bg=PANEL2_BG)
        r7.pack(fill="x", pady=6)
        tk.Label(r7, text="Mức ưu tiên tiến trình (OS Priority):", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.prio_var = tk.StringVar(value="low")
        prio_cb = ttk.Combobox(r7, textvariable=self.prio_var, state="readonly", width=35,
                               values=["low (Thấp hơn - Tránh đơ OS/UI khi CPU full tải)", "normal (Bình thường)"])
        prio_cb.pack(side="left")

        # 3.3 GPU VRAM Fraction Limit
        r8 = tk.Frame(sec3, bg=PANEL2_BG)
        r8.pack(fill="x", pady=6)
        tk.Label(r8, text="Giới hạn % VRAM GPU tối đa:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.max_vram_var = tk.IntVar(value=80)
        vram_spin = tk.Spinbox(r8, from_=20, to=100, increment=5, textvariable=self.max_vram_var, font=("Segoe UI", 9),
                               bg="#0e1621", fg=TEXT_COLOR, width=8, bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR)
        vram_spin.pack(side="left")
        tk.Label(r8, text="% (Chừa VRAM cho Card màn hình vẽ giao diện OS, tránh đơ màn hình)", font=("Segoe UI", 8), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=10)

        # 3.4 Forced Garbage Collection Checkbox
        self.force_gc_var = tk.BooleanVar(value=True)
        chk_gc = tk.Checkbutton(sec3, text="Tự động thu gom bộ nhớ RAM / VRAM (Garbage Collection) ngay sau mỗi lần tạo audio xong",
                                variable=self.force_gc_var, font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG,
                                activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, selectcolor="#0e1621")
        chk_gc.pack(anchor="w", pady=4)

        # 3.5 Max Batch Workers
        r9 = tk.Frame(sec3, bg=PANEL2_BG)
        r9.pack(fill="x", pady=6)
        tk.Label(r9, text="Số luồng chạy Batch đồng thời:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.batch_workers_var = tk.IntVar(value=2)
        workers_spin = tk.Spinbox(r9, from_=1, to=4, increment=1, textvariable=self.batch_workers_var, font=("Segoe UI", 9),
                                   bg="#0e1621", fg=TEXT_COLOR, width=8, bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR)
        workers_spin.pack(side="left")
        tk.Label(r9, text="file đồng thời (Mặc định: 2 file đồng thời để tối ưu hiệu năng Batch)", font=("Segoe UI", 8), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=10)

        # SECTION 4: 🎨 Cấu hình Giao diện & Trải nghiệm (UI & UX)
        sec4 = self._create_section(scrollable_frame, "🎨 Giao diện & Trải nghiệm")

        # 4.1 Desktop Notifications Checkbox
        self.desktop_notif_var = tk.BooleanVar()
        chk_notif = tk.Checkbutton(sec4, text="Hiển thị thông báo khi sinh audio hoàn tất",
                                   variable=self.desktop_notif_var, font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG,
                                   activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, selectcolor="#0e1621")
        chk_notif.pack(anchor="w", pady=4)

        # 4.2 Confirm Delete History Checkbox
        self.confirm_delete_var = tk.BooleanVar()
        chk_confirm = tk.Checkbutton(sec4, text="Hiển thị hộp thoại cảnh báo xác nhận trước khi xóa mục trong Lịch sử",
                                     variable=self.confirm_delete_var, font=("Segoe UI", 9), fg=TEXT_COLOR, bg=PANEL2_BG,
                                     activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, selectcolor="#0e1621")
        chk_confirm.pack(anchor="w", pady=4)

        # 4.3 Language Dropdown Option
        r_lang = tk.Frame(sec4, bg=PANEL2_BG)
        r_lang.pack(fill="x", pady=6)
        tk.Label(r_lang, text="Ngôn ngữ mặc định (Language):", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG, width=28, anchor="w").pack(side="left")
        self.language_var = tk.StringVar(value="🇻🇳 Tiếng Việt")
        lang_cb = ttk.Combobox(r_lang, textvariable=self.language_var, state="readonly", width=25,
                               values=list(UI_LANGUAGES.values()))
        lang_cb.pack(side="left")

        # ACTION BUTTONS FOOTER
        btn_bar = tk.Frame(self, bg=PANEL_BG)
        btn_bar.pack(fill="x", pady=(10, 0))

        tk.Button(btn_bar, text="💾 Lưu cài đặt", font=("Segoe UI", 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  bd=0, cursor="hand2", padx=20, pady=8, command=self.save_settings_action).pack(side="left", padx=(0, 10))

        tk.Button(btn_bar, text="🔄 Khôi phục mặc định", font=("Segoe UI", 9), bg="#1f2d40", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=14, pady=7, command=self.reset_defaults_action).pack(side="left")

    def _create_section(self, parent, title):
        sec_frame = tk.Frame(parent, bg=PANEL2_BG)
        sec_frame.pack(fill="x", pady=(0, 16))

        title_lbl = tk.Label(sec_frame, text=title, font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg=PANEL2_BG, anchor="w")
        title_lbl.pack(fill="x", pady=(0, 6))

        line = tk.Frame(sec_frame, height=1, bg=BORDER_COLOR)
        line.pack(fill="x", pady=(0, 8))

        return sec_frame

    def _browse_export_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục xuất âm thanh mặc định", initialdir=self.export_dir_var.get())
        if d:
            self.export_dir_var.set(d)

    def _browse_model_cache_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục lưu Cache Model", initialdir=self.model_cache_var.get())
        if d:
            self.model_cache_var.set(d)

    def load_settings_to_ui(self):
        """Nạp các giá trị từ settings_manager lên giao diện"""
        settings_manager.load()
        self.export_dir_var.set(settings_manager.get("export_dir"))
        self.model_cache_var.set(settings_manager.get("model_cache_dir"))
        self.auto_open_var.set(settings_manager.get("auto_open_export_dir"))

        dev = settings_manager.get("device")
        if dev == "auto":
            self.device_var.set("auto (Tự động phát hiện)")
        elif dev == "cuda":
            self.device_var.set("cuda (GPU Nvidia)")
        elif dev == "mps":
            self.device_var.set("mps (Apple Silicon)")
        else:
            self.device_var.set("cpu (Vi xử lý CPU)")

        self.startup_model_var.set(settings_manager.get("default_startup_model"))
        self.max_chunk_var.set(settings_manager.get("max_chunk_chars"))
        self.auto_unload_var.set(settings_manager.get("auto_unload_models"))

        # Hardware limits
        self.cpu_threads_var.set(settings_manager.get("cpu_threads_limit"))
        prio = settings_manager.get("process_priority", "low")
        self.prio_var.set("low (Thấp hơn - Tránh đơ OS/UI khi CPU full tải)" if prio == "low" else "normal (Bình thường)")
        self.max_vram_var.set(settings_manager.get("max_vram_fraction"))
        self.force_gc_var.set(settings_manager.get("force_gc_after_gen"))
        self.batch_workers_var.set(settings_manager.get("max_batch_workers"))

        self.desktop_notif_var.set(settings_manager.get("desktop_notifications"))
        self.confirm_delete_var.set(settings_manager.get("confirm_delete_history"))
        self.language_var.set(settings_manager.get("language", "🇻🇳 Tiếng Việt"))

    def save_settings_action(self):
        """Lưu cài đặt người dùng điều chỉnh"""
        try:
            # Save values
            settings_manager.set("export_dir", self.export_dir_var.get())
            settings_manager.set("model_cache_dir", self.model_cache_var.get())
            settings_manager.set("auto_open_export_dir", self.auto_open_var.get())

            dev_raw = self.device_var.get()
            if "auto" in dev_raw:
                dev_code = "auto"
            elif "cuda" in dev_raw:
                dev_code = "cuda"
            elif "mps" in dev_raw:
                dev_code = "mps"
            else:
                dev_code = "cpu"
            settings_manager.set("device", dev_code)

            settings_manager.set("default_startup_model", self.startup_model_var.get())
            settings_manager.set("max_chunk_chars", self.max_chunk_var.get())
            settings_manager.set("auto_unload_models", self.auto_unload_var.get())

            # Hardware limits
            settings_manager.set("cpu_threads_limit", self.cpu_threads_var.get())
            settings_manager.set("process_priority", "low" if "low" in self.prio_var.get() else "normal")
            settings_manager.set("max_vram_fraction", self.max_vram_var.get())
            settings_manager.set("force_gc_after_gen", self.force_gc_var.get())
            settings_manager.set("max_batch_workers", self.batch_workers_var.get())

            settings_manager.set("desktop_notifications", self.desktop_notif_var.get())
            settings_manager.set("confirm_delete_history", self.confirm_delete_var.get())
            settings_manager.set("language", self.language_var.get())

            settings_manager.save()

            # Áp dụng ngay giới hạn phần cứng mới vào Engine nếu engine có sẵn
            from core.chatterbox_engine import apply_hardware_limits
            apply_hardware_limits()

            self.main_window.set_status("✓ Đã lưu cài đặt dự án thành công!", progress=100)
            messagebox.showinfo("Lưu Cài Đặt", "Các cài đặt đã được lưu thành công vào config/settings.json!")
        except Exception as e:
            logger.error("Lỗi lưu cài đặt: %s", e)
            messagebox.showerror("Lỗi Lưu Cài Đặt", str(e))

    def reset_defaults_action(self):
        """Khôi phục cài đặt mặc định"""
        if messagebox.askyesno("Khôi phục mặc định", "Bạn có chắc chắn muốn đặt lại tất cả cấu hình về mặc định ban đầu?"):
            settings_manager.reset_defaults()
            self.load_settings_to_ui()
            from core.chatterbox_engine import apply_hardware_limits
            apply_hardware_limits()
            self.main_window.set_status("✓ Đã khôi phục cài đặt mặc định.", progress=100)
            messagebox.showinfo("Khôi Phục Mặc Định", "Đã đặt lại cấu hình về mặc định nhà sản xuất.")
