"""
Tab 5: Lịch sử âm thanh đã tạo (Session & Global History Tab)
"""

import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config.constants import *
from ui.components.audio_player import AudioPlayerWidget
from utils.context_menu import bind_right_click_menu
from utils.logger import logger
from utils.platform_tools import open_folder

class HistoryTab(tk.Frame):
    """Tab quản lý và nghe lại toàn bộ Lịch sử các file âm thanh đã sinh"""
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        self.history = main_window.history
        self.filtered_history = []

        self._build_ui()

    def _build_ui(self):
        # Header / Title Card
        hdr_card = tk.Frame(self, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        hdr_card.pack(fill="x", pady=(0, 10))

        hdr_row = tk.Frame(hdr_card, bg=PANEL2_BG)
        hdr_row.pack(fill="x", padx=16, pady=10)

        tk.Label(hdr_row, text="📜 Lịch sử âm thanh đã tạo", font=("Segoe UI", 11, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")
        self.hist_badge = tk.Label(hdr_row, text="0 mục", font=("Segoe UI", 9, "bold"), bg="#192c4b", fg="#a9c3ff", padx=10, pady=3)
        self.hist_badge.pack(side="right")

        # Split left (List & Filter) / right (Audio Player & Info)
        content_frame = tk.Frame(self, bg=PANEL_BG)
        content_frame.pack(fill="both", expand=True)

        left_pane = tk.Frame(content_frame, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(content_frame, bg=PANEL_BG, width=360)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # LEFT PANE: Search & History List
        list_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        list_card.pack(fill="both", expand=True)

        # Search Bar
        sf_row = tk.Frame(list_card, bg=PANEL2_BG)
        sf_row.pack(fill="x", padx=14, pady=10)

        self.hist_search_var = tk.StringVar()
        self.search_entry = tk.Entry(sf_row, textvariable=self.hist_search_var, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 10),
                                     bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.insert(0, "🔍 Tìm kiếm theo tên file hoặc nội dung...")
        self.search_entry.bind("<FocusIn>", lambda e: self.search_entry.delete(0, "end") if self.hist_search_var.get() == "🔍 Tìm kiếm theo tên file hoặc nội dung..." else None)
        bind_right_click_menu(self.search_entry)

        # Filter Combobox
        self.hist_time_var = tk.StringVar(value="Tất cả")
        cb = ttk.Combobox(sf_row, textvariable=self.hist_time_var, state="readonly", width=12, values=["Tất cả", "Hôm nay", "7 ngày qua"])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.filter_history())

        self.hist_search_var.trace_add("write", lambda *args: self.filter_history())

        # Listbox containing History
        self.hist_listbox = tk.Listbox(list_card, bg="#0e1621", fg=TEXT_COLOR, selectbackground=ACCENT_COLOR,
                                       font=("Segoe UI", 10), bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR,
                                       activestyle="none")
        self.hist_listbox.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.hist_listbox.bind("<<ListboxSelect>>", self._on_select_history_item)

        # Toolbar under list
        tb = tk.Frame(list_card, bg=PANEL2_BG)
        tb.pack(fill="x", padx=14, pady=(0, 12))

        tk.Button(tb, text="▶ Nghe lại", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  bd=0, cursor="hand2", padx=12, pady=6, command=self.play_history_action).pack(side="left", padx=(0, 6))

        tk.Button(tb, text="📂 Mở thư mục chứa", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=10, pady=5, command=self.open_dir_action).pack(side="left", padx=(0, 6))

        tk.Button(tb, text="🗑 Xóa khỏi lịch sử", font=("Segoe UI", 9), bg=PANEL2_BG, fg="#f87171",
                  bd=0, activebackground=PANEL2_BG, activeforeground="#ffffff", cursor="hand2",
                  command=self.delete_history_action).pack(side="right")

        # RIGHT PANE: Audio Player & Detailed Info
        info_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        info_card.pack(fill="both", expand=True)

        tk.Label(info_card, text="Chi tiết file âm thanh", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 6))

        # Audio Player (ẩn khi chưa chọn file)
        self.audio_player = AudioPlayerWidget(info_card, self.engine)
        self.audio_player.pack_forget()

        # Detailed Text Info Box
        self.info_text_box = tk.Text(info_card, height=10, font=("Segoe UI", 10), bg="#0e1621", fg=TEXT_COLOR,
                                     bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, state="disabled")
        self.info_text_box.pack(fill="both", expand=True, padx=14, pady=10)

        self.refresh_history_ui()

    def filter_history(self):
        """Lọc danh sách lịch sử theo chuỗi tìm kiếm"""
        query = self.hist_search_var.get().strip().lower()
        if query == "🔍 tìm kiếm theo tên file hoặc nội dung...":
            query = ""

        self.hist_listbox.delete(0, "end")
        self.filtered_history = []

        for item in reversed(self.history):
            label = item.get("label", "")
            path = item.get("path", "")
            if not query or query in label.lower() or query in path.lower():
                self.filtered_history.append(item)
                self.hist_listbox.insert("end", label)

        count = len(self.filtered_history)
        self.hist_badge.config(text=f"{count} mục")

    def refresh_history_ui(self):
        """Cập nhật lại giao diện danh sách lịch sử"""
        self.filter_history()

    def _on_select_history_item(self, event):
        """Sự kiện chọn 1 dòng trong danh sách lịch sử"""
        sel = self.hist_listbox.curselection()
        if not sel:
            return

        idx = sel[0]
        if idx < len(self.filtered_history):
            item = self.filtered_history[idx]
            path = item.get("path", "")
            label = item.get("label", "")
            created_time = item.get("time", "N/A")

            # Hiển thị thông tin chi tiết
            self.info_text_box.config(state="normal")
            self.info_text_box.delete("1.0", "end")
            self.info_text_box.insert("end", f"📄 Tên mục: {label}\n")
            self.info_text_box.insert("end", f"⏰ Thời gian: {created_time}\n")
            self.info_text_box.insert("end", f"📁 Đường dẫn: {path}\n")
            if os.path.exists(path):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                self.info_text_box.insert("end", f"📊 Kích thước: {size_mb:.2f} MB\n")
            else:
                self.info_text_box.insert("end", "⚠️ Trạng thái: File không tồn tại trên ổ đĩa!\n")
            self.info_text_box.config(state="disabled")

            # Tải file vào player nếu file tồn tại
            if path and os.path.exists(path):
                self.audio_player.pack(fill="x", padx=14, pady=(0, 6), before=self.info_text_box)
                self.audio_player.load_audio(path)
            else:
                self.audio_player.pack_forget()

    def play_history_action(self):
        """Phát lại file đang được chọn"""
        sel = self.hist_listbox.curselection()
        if not sel:
            messagebox.showwarning("Chưa chọn mục", "Vui lòng chọn 1 mục trong danh sách để nghe lại.")
            return

        idx = sel[0]
        if idx < len(self.filtered_history):
            path = self.filtered_history[idx].get("path")
            if path and os.path.exists(path):
                self.audio_player.pack(fill="x", padx=14, pady=(0, 6), before=self.info_text_box)
                self.audio_player.load_audio(path)
                self.audio_player.play()
            else:
                messagebox.showerror("File không tồn tại", f"Không tìm thấy file âm thanh tại:\n{path}")

    def open_dir_action(self):
        """Mở thư mục chứa file âm thanh đang chọn"""
        sel = self.hist_listbox.curselection()
        if not sel:
            messagebox.showwarning("Chưa chọn mục", "Vui lòng chọn 1 mục trong danh sách.")
            return

        idx = sel[0]
        if idx < len(self.filtered_history):
            path = self.filtered_history[idx].get("path")
            if path:
                folder = os.path.dirname(path)
                if os.path.exists(folder):
                    try:
                        open_folder(folder)
                    except Exception as e:
                        messagebox.showerror("Lỗi mở thư mục", str(e))
                else:
                    messagebox.showerror("Thư mục không tồn tại", folder)

    def delete_history_action(self):
        """Xóa mục chọn khỏi lịch sử"""
        sel = self.hist_listbox.curselection()
        if not sel:
            messagebox.showwarning("Chưa chọn mục", "Vui lòng chọn mục cần xóa.")
            return

        idx = sel[0]
        if idx < len(self.filtered_history):
            from config.settings import settings_manager
            if settings_manager.get("confirm_delete_history", True):
                if not messagebox.askyesno("Xác nhận xóa", "Bạn có chắc chắn muốn xóa mục này khỏi Lịch sử không?"):
                    return
            item = self.filtered_history[idx]
            self.main_window.remove_from_history(item.get("label"))
            self.refresh_history_ui()
            self.audio_player.pack_forget()
            self.info_text_box.config(state="normal")
            self.info_text_box.delete("1.0", "end")
            self.info_text_box.config(state="disabled")
