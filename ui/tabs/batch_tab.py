"""
Tab 4: Batch Processing & Session History Tab
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from config.constants import *
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu

class BatchTab(tk.Frame):
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        self.history = main_window.history

        self._build_ui()

    def _build_ui(self):
        # Split left/right pane
        left_pane = tk.Frame(self, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(self, bg=PANEL_BG, width=380)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # LEFT PANE: Batch Processing
        batch_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        batch_card.pack(fill="both", expand=True)

        hdr = tk.Frame(batch_card, bg=PANEL2_BG)
        hdr.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(hdr, text="Xử lý hàng loạt (Batch Processing)", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")
        tk.Button(hdr, text="📄 Nhập từ .txt/.csv", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=4,
                  command=self._import_batch_file).pack(side="right")

        self.batch_text_box = tk.Text(batch_card, height=10, font=("Segoe UI", 11), bg="#0e1621", fg=TEXT_COLOR,
                                      bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                      insertbackground="white")
        self.batch_text_box.pack(fill="both", expand=True, padx=14, pady=4)
        self.batch_text_box.insert("1.0", "Line 1: Hello from batch mode!\nLine 2: Chatterbox processes text easily.\nLine 3: Enjoy your AI voice generation.")
        bind_right_click_menu(self.batch_text_box)

        self.batch_char_lbl = tk.Label(batch_card, text="3 dòng · giọng mẫu: Mặc định", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.batch_char_lbl.pack(anchor="w", padx=14, pady=(0, 6))

        # Output dir
        out_lbl = tk.Label(batch_card, text="Thư mục xuất", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        out_lbl.pack(anchor="w", padx=14, pady=(4, 2))

        dir_row = tk.Frame(batch_card, bg=PANEL2_BG)
        dir_row.pack(fill="x", padx=14, pady=(0, 10))

        self.batch_out_dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Entry(dir_row, textvariable=self.batch_out_dir_var, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 10),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR).pack(side="left", fill="x", expand=True, padx=(0, 8), pady=1)
        
        tk.Button(dir_row, text="📁 Chọn...", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=10, pady=4,
                  command=self._pick_batch_out_dir).pack(side="right")

        # Run Button
        tk.Button(batch_card, text="⚡ Bắt đầu tạo hàng loạt", font=("Segoe UI", 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, pady=8, cursor="hand2",
                  command=self.run_batch_action).pack(fill="x", padx=14, pady=(4, 10))

        self.batch_prog_lbl = tk.Label(batch_card, text="Chưa chạy batch", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.batch_prog_lbl.pack(anchor="w", padx=14)
        self.batch_prog_bar = ttk.Progressbar(batch_card, orient="horizontal", mode="determinate")
        self.batch_prog_bar.pack(fill="x", padx=14, pady=(2, 14))

        # RIGHT PANE: History
        hist_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        hist_card.pack(fill="both", expand=True)

        hist_hdr = tk.Frame(hist_card, bg=PANEL2_BG)
        hist_hdr.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(hist_hdr, text="Lịch sử âm thanh đã tạo", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")
        self.hist_badge = tk.Label(hist_hdr, text="0 mục", font=("Segoe UI", 9, "bold"), bg="#192c4b", fg="#a9c3ff", padx=6, pady=2)
        self.hist_badge.pack(side="right")

        # Search / Filter
        sf_row = tk.Frame(hist_card, bg=PANEL2_BG)
        sf_row.pack(fill="x", padx=14, pady=4)
        
        self.hist_search_var = tk.StringVar()
        self.search_entry = tk.Entry(sf_row, textvariable=self.hist_search_var, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 10),
                                     bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search_entry.insert(0, "🔍 Tìm theo nội dung...")
        self.search_entry.bind("<FocusIn>", lambda e: self.search_entry.delete(0, "end") if self.hist_search_var.get() == "🔍 Tìm theo nội dung..." else None)
        bind_right_click_menu(self.search_entry)

        self.hist_time_var = tk.StringVar(value="Tất cả")
        ttk.Combobox(sf_row, textvariable=self.hist_time_var, state="readonly", width=10, values=["Tất cả", "Hôm nay", "7 ngày qua"]).pack(side="right")

        self.hist_listbox = tk.Listbox(hist_card, bg="#0e1621", fg=TEXT_COLOR, selectbackground=ACCENT_COLOR,
                                       font=("Segoe UI", 9), bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR,
                                       activestyle="none")
        self.hist_listbox.pack(fill="both", expand=True, padx=14, pady=8)

        # Register trace only after hist_listbox exists
        self.hist_search_var.trace_add("write", lambda *args: self.filter_history())

        # Toolbar
        hist_tb = tk.Frame(hist_card, bg=PANEL2_BG)
        hist_tb.pack(fill="x", padx=14, pady=(0, 14))
        
        tk.Button(hist_tb, text="▶ Nghe lại", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=4,
                  command=self.play_history_action).pack(side="left", padx=(0, 6))
        tk.Button(hist_tb, text="📂 Mở thư mục", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=4,
                  command=self.open_dir_action).pack(side="left", padx=(0, 6))
        tk.Button(hist_tb, text="🗑 Xóa mục đã chọn", font=("Segoe UI", 9), bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                  bd=0, activebackground=PANEL2_BG, activeforeground=TEXT_COLOR, cursor="hand2",
                  command=self.delete_history_action).pack(side="left")

    def _import_batch_file(self):
        path = filedialog.askopenfilename(title="Chọn file văn bản", filetypes=[("Text & CSV files", "*.txt *.csv")])
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.batch_text_box.delete("1.0", "end")
                self.batch_text_box.insert("1.0", content)
                lines_cnt = len([l for l in content.split("\n") if l.strip()])
                self.batch_char_lbl.config(text=f"{lines_cnt} dòng · giọng mẫu: Mặc định")
                logger.info("Da nhap %d ky tu tu file: %s", len(content), path)
            except Exception as e:
                messagebox.showerror("Lỗi đọc file", str(e))

    def _pick_batch_out_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục xuất batch")
        if d:
            self.batch_out_dir_var.set(d)

    def _update_batch_prog(self, msg, val):
        self.batch_prog_lbl.config(text=f"{msg} ({val}%)")
        self.batch_prog_bar['value'] = val

    def run_batch_action(self):
        text = self.batch_text_box.get("1.0", "end").strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        if not lines:
            messagebox.showwarning("Không có dữ liệu", "Nhập ít nhất 1 câu văn bản để chạy batch.")
            return

        out_dir = Path(self.batch_out_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        m_name = self.main_window.get_active_model_name() or "Chatterbox Standard (500M)"

        def batch_process():
            total = len(lines)
            for idx, line in enumerate(lines, 1):
                pct = int((idx / total) * 100)
                self.after(0, lambda i=idx, t=total, p=pct: self._update_batch_prog(f"Đang xử lý dòng {i}/{t}", p))

                out_file = out_dir / f"batch_{idx:03d}.wav"
                
                # Chạy gọi Engine sinh tts đồng bộ trong luồng nền này
                self.engine.generate_tts(
                    text=line,
                    ref_path=self.main_window.get_ref_audio_path(),
                    model_name=m_name,
                    exag=self.main_window.get_exag_val(),
                    cfg=self.main_window.get_cfg_val(),
                    temp=self.main_window.get_temp_val(),
                    seed=self.main_window.get_seed_val(),
                    is_random_seed=self.main_window.get_random_seed_val(),
                    out_path=str(out_file)
                )

        def callback(success, result):
            if success:
                self._update_batch_prog("Hoàn thành Batch!", 100)
                self.main_window.set_status("Hoàn thành Batch!")
                
                # Thêm tất cả file vừa sinh vào history
                for i in range(1, len(lines) + 1):
                    out_file = out_dir / f"batch_{i:03d}.wav"
                    self.main_window.add_to_history(str(out_file), f"Batch #{i}: {lines[i-1][:25]}")
                
                self.refresh_history_ui()
                messagebox.showinfo("Hoàn tất Batch", f"Đã xuất thành công {len(lines)} file WAV tại:\n{out_dir}")
            else:
                self.main_window.set_status("Lỗi Batch Processing.")
                messagebox.showerror("Lỗi Batch Processing", str(result))

        run_in_background(batch_process, callback, self)

    def refresh_history_ui(self):
        self.hist_listbox.delete(0, "end")
        for h in reversed(self.history):
            self.hist_listbox.insert("end", h['label'])
        self.hist_badge.config(text=f"{len(self.history)} mục")

    def filter_history(self):
        query = self.hist_search_var.get().lower().strip()
        if "tìm theo nội dung" in query or not query:
            query = ""
        self.hist_listbox.delete(0, "end")
        for h in reversed(self.history):
            if not query or query in h['label'].lower():
                self.hist_listbox.insert("end", h['label'])

    def play_history_action(self):
        sel = self.hist_listbox.curselection()
        if sel:
            idx = sel[0]
            txt = self.hist_listbox.get(idx)
            for h in self.history:
                if h['label'] == txt and os.path.exists(h['path']):
                    self.engine.play_audio(h['path'])
                    break

    def open_dir_action(self):
        sel = self.hist_listbox.curselection()
        if sel:
            txt = self.hist_listbox.get(sel[0])
            for h in self.history:
                if h['label'] == txt and os.path.exists(h['path']):
                    folder = os.path.dirname(h['path'])
                    os.startfile(folder)
                    break

    def delete_history_action(self):
        sel = self.hist_listbox.curselection()
        if sel:
            idx = sel[0]
            txt = self.hist_listbox.get(idx)
            self.main_window.remove_from_history(txt)
            self.refresh_history_ui()
