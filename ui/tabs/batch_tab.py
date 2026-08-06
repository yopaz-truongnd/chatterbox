"""
Tab 2: Batch Studio — Xử lý sinh âm thanh hàng loạt nhiều nhân vật & chuyên nghiệp
"""

import os
import csv
import time
import wave
import shutil
import tempfile
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from config.constants import *
from ui.components.audio_player import AudioPlayerWidget
from ui.components.waveform_canvas import WaveformCanvas
from utils.threading_helper import run_in_background
from utils.context_menu import bind_right_click_menu
from utils.logger import logger

def parse_batch_file(file_path):
    """
    Đọc và trích xuất nội dung văn bản từ file .txt hoặc .csv
    Hỗ trợ tự động nhận diện encoding, phân tách dấu (phẩy, chấm phẩy, tab) và trích xuất đúng cột chứa văn bản.
    """
    text_content = ""
    for enc in ["utf-8-sig", "utf-8", "utf-16", "latin-1", "cp1252"]:
        try:
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                text_content = f.read()
            if text_content:
                break
        except Exception:
            continue

    if not text_content:
        return []

    if file_path.lower().endswith(".csv"):
        try:
            lines = [l for l in text_content.splitlines() if l.strip()]
            if not lines:
                return []

            sample = "\n".join(lines[:5])
            delimiter = ","
            if ";" in sample and sample.count(";") > sample.count(","):
                delimiter = ";"
            elif "\t" in sample and sample.count("\t") > sample.count(","):
                delimiter = "\t"

            reader = csv.reader(lines, delimiter=delimiter)
            rows = [row for row in reader if row and any(cell.strip() for cell in row)]

            if not rows:
                return []

            num_cols = max(len(r) for r in rows)
            if num_cols == 1:
                extracted = [r[0].strip() for r in rows if r and r[0].strip()]
                if extracted and extracted[0].lower() in ["text", "content", "nội dung", "văn bản", "sentence", "prompt", "line", "id"]:
                    extracted = extracted[1:]
                return extracted
            else:
                header = [c.strip().lower() for c in rows[0]]
                text_col_idx = -1

                for idx, col_name in enumerate(header):
                    if any(k in col_name for k in ["text", "content", "nội dung", "văn bản", "sentence", "prompt", "line", "speech"]):
                        text_col_idx = idx
                        break

                has_header = (text_col_idx != -1) or any(not c.replace(".", "").isdigit() for c in header)
                data_rows = rows[1:] if has_header else rows

                if text_col_idx == -1 and data_rows:
                    col_avg_lens = []
                    for col_idx in range(num_cols):
                        lens = [len(r[col_idx]) for r in data_rows if col_idx < len(r)]
                        avg_len = sum(lens) / len(lens) if lens else 0
                        col_avg_lens.append((avg_len, col_idx))
                    col_avg_lens.sort(reverse=True)
                    text_col_idx = col_avg_lens[0][1]

                extracted = []
                for r in data_rows:
                    if text_col_idx < len(r):
                        val = r[text_col_idx].strip()
                        if val:
                            extracted.append(val)
                return extracted

        except Exception as e:
            logger.warning("CSV parse fallback to raw lines: %s", e)
            return [l.strip() for l in text_content.splitlines() if l.strip()]
    else:
        return [l.strip() for l in text_content.splitlines() if l.strip()]

def merge_wav_files(file_paths, output_path, silence_sec=0.5):
    """Gộp nhiều file WAV thành 1 file âm thanh duy nhất với khoảng lặng ở giữa"""
    valid_paths = [p for p in file_paths if p and os.path.exists(p)]
    if not valid_paths:
        return False

    try:
        params = None
        with wave.open(valid_paths[0], 'rb') as first:
            params = first.getparams()
            framerate = first.getframerate()
            nchannels = first.getnchannels()
            sampwidth = first.getsampwidth()

        silence_frames = int(framerate * float(silence_sec))
        silence_bytes = b'\x00' * (silence_frames * nchannels * sampwidth)

        with wave.open(output_path, 'wb') as outfile:
            outfile.setparams(params)
            for idx, wpath in enumerate(valid_paths):
                with wave.open(wpath, 'rb') as infile:
                    outfile.writeframes(infile.readframes(infile.getnframes()))
                if idx < len(valid_paths) - 1 and silence_sec > 0:
                    outfile.writeframes(silence_bytes)
        return True
    except Exception as e:
        logger.error("Could not merge WAV files: %s", e)
        return False

class BatchTab(tk.Frame):
    """Tab Batch Studio chuyên biệt xử lý tạo âm thanh hàng loạt nhiều nhân vật"""
    def __init__(self, parent, engine, main_window):
        super().__init__(parent, bg=PANEL_BG)
        self.engine = engine
        self.main_window = main_window
        
        # Data store
        self.rows_list = []      # Danh sách dict các dòng [{'text': str, 'voice': str, 'widget': Frame}]
        self.batch_results = []   # Kết quả đợt vừa sinh
        self.merged_file_path = None
        self.ref_audio_path = None
        self.presets = main_window.presets

        self._build_ui()

    def _build_ui(self):
        # Split left (List & Config) / right (Voice & Parameters & Results)
        left_pane = tk.Frame(self, bg=PANEL_BG)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_pane = tk.Frame(self, bg=PANEL_BG, width=380)
        right_pane.pack(side="right", fill="both", padx=(8, 0))

        # ---------------- LEFT PANE ----------------
        # 1. Row List Card
        list_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        list_card.pack(fill="both", expand=True, pady=(0, 10))

        # Header toolbar
        hdr = tk.Frame(list_card, bg=PANEL2_BG)
        hdr.pack(fill="x", padx=14, pady=(10, 6))

        tk.Label(hdr, text="📦 Batch Studio — Danh sách câu thoại", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")

        tb_btns = tk.Frame(hdr, bg=PANEL2_BG)
        tb_btns.pack(side="right")

        self.btn_add_row = tk.Button(tb_btns, text="➕ Thêm dòng", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                                    bd=0, cursor="hand2", padx=8, pady=4, command=lambda: self.add_row_item(""))
        self.btn_add_row.pack(side="left", padx=(0, 4))
        
        self.btn_import_file = tk.Button(tb_btns, text="📄 Nhập từ .txt/.csv", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                       bd=1, relief="solid", cursor="hand2", padx=8, pady=4, command=self._import_batch_file)
        self.btn_import_file.pack(side="left", padx=(0, 4))

        self.btn_clear_all = tk.Button(tb_btns, text="🗑 Xóa hết", font=("Segoe UI", 9), bg=PANEL2_BG, fg="#f87171",
                                     bd=0, activebackground=PANEL2_BG, activeforeground="#ffffff", cursor="hand2", command=self.clear_all_rows)
        self.btn_clear_all.pack(side="left")

        # Scrollable Canvas container for Rows
        self.canvas_frame = tk.Frame(list_card, bg="#0e1621", bd=1, relief="solid", highlightbackground=BORDER_COLOR)
        self.canvas_frame.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        self.canvas = tk.Canvas(self.canvas_frame, bg="#0e1621", highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_inner = tk.Frame(self.canvas, bg="#0e1621")

        self.scrollable_inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.batch_char_lbl = tk.Label(list_card, text="0 dòng văn bản", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.batch_char_lbl.pack(anchor="w", padx=14, pady=(0, 6))

        # 2. Output Configuration Card
        out_card = tk.Frame(left_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        out_card.pack(fill="x", pady=(0, 10))

        tk.Label(out_card, text="⚙️ Cấu hình xuất file & Định dạng", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))

        # Row 1: Output Dir & Naming Template
        row1 = tk.Frame(out_card, bg=PANEL2_BG)
        row1.pack(fill="x", padx=14, pady=2)

        tk.Label(row1, text="Thư mục xuất:", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG, width=12, anchor="w").pack(side="left")
        self.batch_out_dir_var = tk.StringVar(value=DEFAULT_EXPORT_DIR)
        tk.Entry(row1, textvariable=self.batch_out_dir_var, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 9),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(row1, text="📁 Chọn", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=2, command=self._pick_batch_out_dir).pack(side="right")

        # Row 2: Naming Pattern Template
        row2 = tk.Frame(out_card, bg=PANEL2_BG)
        row2.pack(fill="x", padx=14, pady=4)

        tk.Label(row2, text="Mẫu tên file:", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG, width=12, anchor="w").pack(side="left")
        self.naming_pattern_var = tk.StringVar(value="line_{index}_{text}")
        self.naming_pattern_var.trace_add("write", lambda *args: self._update_pattern_preview())
        
        tk.Entry(row2, textvariable=self.naming_pattern_var, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 9),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR).pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.format_var = tk.StringVar(value="WAV")
        ttk.Combobox(row2, textvariable=self.format_var, state="readonly", width=6, values=["WAV", "MP3"]).pack(side="right")

        self.pattern_preview_lbl = tk.Label(out_card, text="Ví dụ tên file: line_001_Hello_world.wav", font=("Segoe UI", 8, "italic"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.pattern_preview_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        # Row 3: Merge option & Silence interval
        row3 = tk.Frame(out_card, bg=PANEL2_BG)
        row3.pack(fill="x", padx=14, pady=(2, 4))

        self.merge_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="🔗 Gộp tất cả câu thành 1 file âm thanh duy nhất", variable=self.merge_all_var,
                       font=("Segoe UI", 9, "bold"), fg="#a7f3d0", bg=PANEL2_BG, activebackground=PANEL2_BG, selectcolor="#0e1621").pack(side="left")

        tk.Label(row3, text="Khoảng lặng giữa câu:", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=(16, 4))
        self.silence_sec_var = tk.DoubleVar(value=0.5)
        tk.Entry(row3, textvariable=self.silence_sec_var, width=5, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 9),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR).pack(side="left")
        tk.Label(row3, text="giây", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=(2, 0))

        # Row 4: Multi-threading Concurrency Workers
        row4 = tk.Frame(out_card, bg=PANEL2_BG)
        row4.pack(fill="x", padx=14, pady=(2, 8))

        tk.Label(row4, text="⚡ Số luồng song song (Workers):", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg=PANEL2_BG).pack(side="left", padx=(0, 6))
        self.max_workers_var = tk.IntVar(value=2)
        sp = ttk.Spinbox(row4, from_=1, to=16, textvariable=self.max_workers_var, width=4)
        sp.pack(side="left", padx=(0, 6))
        tk.Label(row4, text="(Ví dụ: 2 luồng sẽ xử lý 2 câu song song cùng lúc để tăng tốc)", font=("Segoe UI", 8, "italic"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")

        # 3. Action Toolbar & Dual Progress Block
        run_row = tk.Frame(left_pane, bg=PANEL_BG)
        run_row.pack(fill="x")

        self.btn_run_batch = tk.Button(run_row, text="⚡ Bắt đầu tạo hàng loạt (Batch Run)", font=("Segoe UI", 10, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                                       activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, pady=9, cursor="hand2",
                                       command=self.run_batch_action)
        self.btn_run_batch.pack(fill="x", pady=(0, 6))

        # Khối tiến trình tổng đợt Batch & Thời gian
        total_prog_card = tk.Frame(run_row, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        total_prog_card.pack(fill="x", pady=(0, 6))

        t_hdr = tk.Frame(total_prog_card, bg=PANEL2_BG)
        t_hdr.pack(fill="x", padx=10, pady=(6, 2))

        self.batch_total_lbl = tk.Label(t_hdr, text="📦 Tiến trình tổng: Sẵn sàng.", font=("Segoe UI", 9, "bold"), fg="#a9c3ff", bg=PANEL2_BG)
        self.batch_total_lbl.pack(side="left")

        self.batch_timer_lbl = tk.Label(t_hdr, text="⏱ Đã chạy: 00:00 | Dự kiến xong: --:--:--", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg=PANEL2_BG)
        self.batch_timer_lbl.pack(side="right")

        self.batch_total_bar = ttk.Progressbar(total_prog_card, orient="horizontal", mode="determinate")
        self.batch_total_bar.pack(fill="x", padx=10, pady=(2, 6))

        # Khối tiến trình dòng hiện tại (Current Item Progress)
        cur_prog_card = tk.Frame(run_row, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        cur_prog_card.pack(fill="x")

        c_hdr = tk.Frame(cur_prog_card, bg=PANEL2_BG)
        c_hdr.pack(fill="x", padx=10, pady=(6, 2))

        self.batch_item_lbl = tk.Label(c_hdr, text="⚡ Tiến trình dòng hiện tại: Đang chờ...", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG)
        self.batch_item_lbl.pack(side="left")

        self.batch_item_bar = ttk.Progressbar(cur_prog_card, orient="horizontal", mode="determinate")
        self.batch_item_bar.pack(fill="x", padx=10, pady=(2, 6))

        # ---------------- RIGHT PANE ----------------
        # 1. Voice Clone Card
        vc_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        vc_card.pack(fill="x", pady=(0, 10))

        tk.Label(vc_card, text="🎙️ Giọng đọc mặc định & Preset", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(10, 4))

        self.ref_var = tk.StringVar(value="Mặc định")
        tk.Label(vc_card, textvariable=self.ref_var, bg="#0e1621", fg="#a7f3d0", font=("Segoe UI", 9),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, anchor="w", padx=8, pady=4).pack(fill="x", padx=14, pady=(0, 6))

        btn_r = tk.Frame(vc_card, bg=PANEL2_BG)
        btn_r.pack(fill="x", padx=14, pady=(0, 8))
        tk.Button(btn_r, text="📁 Chọn giọng...", font=("Segoe UI", 9, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                  bd=1, relief="solid", cursor="hand2", padx=8, pady=3, command=self._pick_ref_audio).pack(side="left", padx=(0, 6))
        tk.Button(btn_r, text="✖ Xóa giọng", font=("Segoe UI", 9), bg=PANEL2_BG, fg=TEXT_DIM_COLOR,
                  bd=0, cursor="hand2", command=self._clear_ref_audio).pack(side="left")

        # Preset Row
        pr_row = tk.Frame(vc_card, bg=PANEL2_BG)
        pr_row.pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(pr_row, text="Preset:", font=("Segoe UI", 9, "bold"), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=(0, 6))
        self.preset_var = tk.StringVar(value="Mặc định")
        self.preset_cb = ttk.Combobox(pr_row, textvariable=self.preset_var, state="readonly", values=list(self.presets.keys()))
        self.preset_cb.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.preset_cb.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # Apply voice to ALL rows button
        tk.Button(vc_card, text="⏩ Áp dụng giọng này cho TẤT CẢ các dòng", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#a9c3ff",
                  activebackground=ACCENT_COLOR, activeforeground="#ffffff", bd=1, relief="solid", pady=5, cursor="hand2",
                  command=self.apply_voice_to_all_rows).pack(fill="x", padx=14, pady=(0, 10))

        # 2. AI Parameters Card
        param_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        param_card.pack(fill="x", pady=(0, 10))

        tk.Label(param_card, text="🎛️ Thông số sinh âm thanh AI", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(anchor="w", padx=14, pady=(8, 4))

        # Quick Presets Combo Row
        qp_row = tk.Frame(param_card, bg=PANEL2_BG)
        qp_row.pack(fill="x", padx=14, pady=(2, 6))
        tk.Label(qp_row, text="Thông số nhanh:", font=("Segoe UI", 9, "bold"), fg="#a7f3d0", bg=PANEL2_BG).pack(side="left", padx=(0, 6))

        self.quick_presets = {
            "⚖️ Mặc định (Cân bằng)": {"exag": 0.50, "cfg": 0.70, "temp": 0.80},
            "🍃 Tự nhiên & Tròn giọng": {"exag": 0.20, "cfg": 0.50, "temp": 0.60},
            "🔥 Diễn cảm & Cảm xúc cao": {"exag": 1.10, "cfg": 0.90, "temp": 0.90},
            "📖 Kể chuyện & Truyền cảm": {"exag": 0.80, "cfg": 0.80, "temp": 0.75},
            "📰 Đọc tin tức & Chuẩn mực": {"exag": 0.30, "cfg": 0.60, "temp": 0.50},
        }

        self.quick_param_var = tk.StringVar(value="⚖️ Mặc định (Cân bằng)")
        self.quick_param_cb = ttk.Combobox(qp_row, textvariable=self.quick_param_var, state="readonly", values=list(self.quick_presets.keys()))
        self.quick_param_cb.pack(side="left", fill="x", expand=True)
        self.quick_param_cb.bind("<<ComboboxSelected>>", self._on_quick_param_selected)

        # Exaggeration
        ex_row = tk.Frame(param_card, bg=PANEL2_BG)
        ex_row.pack(fill="x", padx=14, pady=2)
        tk.Label(ex_row, text="Exaggeration:", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        self.exag_val_lbl = tk.Label(ex_row, text="0.50", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG)
        self.exag_val_lbl.pack(side="right")
        self.exag_var = tk.DoubleVar(value=0.5)
        ttk.Scale(param_card, variable=self.exag_var, from_=0.0, to=2.0, command=lambda v: self.exag_val_lbl.config(text=f"{float(v):.2f}")).pack(fill="x", padx=14, pady=(0, 6))

        # CFG Scale
        cfg_row = tk.Frame(param_card, bg=PANEL2_BG)
        cfg_row.pack(fill="x", padx=14, pady=2)
        tk.Label(cfg_row, text="CFG Scale:", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        self.cfg_val_lbl = tk.Label(cfg_row, text="0.70", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG)
        self.cfg_val_lbl.pack(side="right")
        self.cfg_var = tk.DoubleVar(value=0.7)
        ttk.Scale(param_card, variable=self.cfg_var, from_=0.1, to=2.0, command=lambda v: self.cfg_val_lbl.config(text=f"{float(v):.2f}")).pack(fill="x", padx=14, pady=(0, 6))

        # Temperature
        temp_row = tk.Frame(param_card, bg=PANEL2_BG)
        temp_row.pack(fill="x", padx=14, pady=2)
        tk.Label(temp_row, text="Temperature:", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left")
        self.temp_val_lbl = tk.Label(temp_row, text="0.80", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG)
        self.temp_val_lbl.pack(side="right")
        self.temp_var = tk.DoubleVar(value=0.8)
        ttk.Scale(param_card, variable=self.temp_var, from_=0.1, to=1.5, command=lambda v: self.temp_val_lbl.config(text=f"{float(v):.2f}")).pack(fill="x", padx=14, pady=(0, 6))

        # Seed Row
        seed_row = tk.Frame(param_card, bg=PANEL2_BG)
        seed_row.pack(fill="x", padx=14, pady=(2, 8))
        tk.Label(seed_row, text="Seed:", font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(side="left", padx=(0, 4))
        self.seed_var = tk.IntVar(value=12345)
        tk.Entry(seed_row, textvariable=self.seed_var, width=8, bg="#0e1621", fg=TEXT_COLOR, font=("Segoe UI", 9),
                 bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR).pack(side="left", padx=(0, 6))
        self.random_seed_var = tk.BooleanVar(value=True)
        tk.Checkbutton(seed_row, text="☑ Ngẫu nhiên", variable=self.random_seed_var, font=("Segoe UI", 9),
                       fg=TEXT_COLOR, bg=PANEL2_BG, activebackground=PANEL2_BG, selectcolor="#0e1621").pack(side="left")

        # 3. Batch Results Card (Rich Result View & Empty State)
        self.res_card = tk.Frame(right_pane, bg=PANEL2_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        self.res_card.pack(fill="both", expand=True)

        res_hdr = tk.Frame(self.res_card, bg=PANEL2_BG)
        res_hdr.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(res_hdr, text="Kết quả đợt Batch vừa chạy", font=("Segoe UI", 10, "bold"), fg="#a9c3ff", bg=PANEL2_BG).pack(side="left")
        self.res_badge = tk.Label(res_hdr, text="0 file", font=("Segoe UI", 9, "bold"), bg="#192c4b", fg="#a9c3ff", padx=6, pady=2)
        self.res_badge.pack(side="right")

        # Container cho trạng thái rỗng hoặc danh sách kết quả
        self.res_body = tk.Frame(self.res_card, bg=PANEL2_BG)
        self.res_body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        # Audio Player Preview cho Result
        self.audio_player = AudioPlayerWidget(self.res_card, self.engine)
        self.audio_player.pack_forget()

        # Thêm 3 dòng mặc định ban đầu
        self.add_row_item("Line 1: Hello from Batch Studio!")
        self.add_row_item("Line 2: Chatterbox processes text easily.")
        self.add_row_item("Line 3: Enjoy your AI voice generation.")

        self._render_results_ui()

    # ---------------- Row Management Methods ----------------
    def set_batch_inputs_enabled(self, enabled: bool):
        """Bật/Tắt khóa chỉnh sửa dữ liệu các dòng và nút bấm khi đang chạy Batch"""
        txt_state = "normal" if enabled else "disabled"
        cb_state = "readonly" if enabled else "disabled"
        btn_state = "normal" if enabled else "disabled"
        txt_bg = "#0e1621" if enabled else "#080d14"
        txt_fg = TEXT_COLOR if enabled else "#64748b"

        if hasattr(self, 'btn_add_row'):
            self.btn_add_row.config(state=btn_state)
            self.btn_import_file.config(state=btn_state)
            self.btn_clear_all.config(state=btn_state)
            self.btn_run_batch.config(state=btn_state)

        for r in self.rows_list:
            r['txt_box'].config(state=txt_state, bg=txt_bg, fg=txt_fg)
            r['voice_cb'].config(state=cb_state)
            for btn in r.get('action_btns', []):
                btn.config(state=btn_state)

    def add_row_item(self, text_val=""):
        """Thêm 1 dòng câu thoại mới vào danh sách với nhãn % tiến độ và viền màu động"""
        row_id = len(self.rows_list) + 1

        row_frame = tk.Frame(self.scrollable_inner, bg="#131e2e", bd=1, relief="solid",
                             highlightbackground=BORDER_COLOR, highlightthickness=2)
        row_frame.pack(fill="x", padx=4, pady=4)

        # Container nhãn bên trái: Index + Tiến độ %
        left_box = tk.Frame(row_frame, bg="#131e2e", width=50)
        left_box.pack(side="left", padx=6, pady=4)

        lbl_idx = tk.Label(left_box, text=f"#{row_id}", font=("Segoe UI", 9, "bold"), fg="#a9c3ff", bg="#131e2e")
        lbl_idx.pack(anchor="center")

        lbl_pct = tk.Label(left_box, text="", font=("Segoe UI", 8, "bold"), fg="#64748b", bg="#131e2e")
        lbl_pct.pack(anchor="center", pady=(2, 0))

        # Text input
        txt_box = tk.Text(row_frame, height=2, font=("Segoe UI", 10), bg="#0e1621", fg=TEXT_COLOR,
                          bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                          insertbackground="white")
        txt_box.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        txt_box.insert("1.0", text_val)
        bind_right_click_menu(txt_box)

        # Voice dropdown selection
        voice_var = tk.StringVar(value="Mặc định")
        voice_cb = ttk.Combobox(row_frame, textvariable=voice_var, state="readonly", width=12, values=self.get_available_voices())
        voice_cb.pack(side="left", padx=4)

        # Action Buttons
        btn_up = tk.Button(row_frame, text="▲", font=("Segoe UI", 8, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                           bd=0, cursor="hand2", width=2, command=lambda: self.move_row(row_frame, -1))
        btn_up.pack(side="left", padx=1)

        btn_dn = tk.Button(row_frame, text="▼", font=("Segoe UI", 8, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                           bd=0, cursor="hand2", width=2, command=lambda: self.move_row(row_frame, 1))
        btn_dn.pack(side="left", padx=1)

        btn_dup = tk.Button(row_frame, text="📋", font=("Segoe UI", 9), bg="#1a2536", fg=TEXT_COLOR,
                            bd=0, cursor="hand2", width=2, command=lambda: self.duplicate_row(txt_box.get("1.0", "end").strip(), voice_var.get()))
        btn_dup.pack(side="left", padx=1)

        btn_play = tk.Button(row_frame, text="▶", font=("Segoe UI", 9, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                             bd=0, cursor="hand2", width=2, command=lambda: self.preview_single_row(txt_box.get("1.0", "end").strip(), voice_var.get()))
        btn_play.pack(side="left", padx=1)

        btn_del = tk.Button(row_frame, text="🗑", font=("Segoe UI", 9), bg="#131e2e", fg="#f87171",
                            bd=0, cursor="hand2", width=2, command=lambda: self.delete_row(row_frame))
        btn_del.pack(side="left", padx=2)

        row_item = {
            'orig_idx': row_id,
            'frame': row_frame,
            'left_box': left_box,
            'lbl_idx': lbl_idx,
            'lbl_pct': lbl_pct,
            'txt_box': txt_box,
            'voice_var': voice_var,
            'voice_cb': voice_cb,
            'action_btns': [btn_up, btn_dn, btn_dup, btn_play, btn_del]
        }
        self.rows_list.append(row_item)
        self._update_rows_indices()

    def delete_row(self, row_frame):
        """Xóa 1 dòng khỏi danh sách"""
        self.rows_list = [r for r in self.rows_list if r['frame'] != row_frame]
        row_frame.destroy()
        self._update_rows_indices()

    def duplicate_row(self, text_val, voice_val):
        """Nhân bản 1 dòng câu thoại"""
        self.add_row_item(text_val)
        if self.rows_list:
            self.rows_list[-1]['voice_var'].set(voice_val)

    def move_row(self, row_frame, direction):
        """Di chuyển 1 dòng lên hoặc xuống"""
        idx = next((i for i, r in enumerate(self.rows_list) if r['frame'] == row_frame), -1)
        if idx == -1:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(self.rows_list):
            self.rows_list[idx], self.rows_list[new_idx] = self.rows_list[new_idx], self.rows_list[idx]
            # Redraw packed frames in new order
            for r in self.rows_list:
                r['frame'].pack_forget()
                r['frame'].pack(fill="x", padx=4, pady=4)
            self._update_rows_indices()

    def clear_all_rows(self):
        """Xóa sạch toàn bộ các dòng"""
        for r in self.rows_list:
            r['frame'].destroy()
        self.rows_list = []
        self._update_rows_indices()

    def _update_rows_indices(self):
        """Cập nhật lại số thứ tự #1, #2... và nhãn tổng số dòng"""
        for i, r in enumerate(self.rows_list, 1):
            r['orig_idx'] = i
            r['lbl_idx'].config(text=f"#{i}")
        cnt = len(self.rows_list)
        self.batch_char_lbl.config(text=f"{cnt} dòng văn bản câu thoại")

    def get_available_voices(self):
        """Trả về danh sách giọng đọc khả dụng (Mặc định + giọng mẫu + presets)"""
        voices = ["Mặc định"]
        if self.ref_audio_path:
            voices.append(f"Giọng mẫu ({os.path.basename(self.ref_audio_path)[:10]})")
        voices.extend(list(self.presets.keys()))
        return voices

    def apply_voice_to_all_rows(self):
        """Áp dụng giọng đọc đang chọn ở Right Pane cho TẤT CẢ các dòng"""
        target_voice = "Mặc định"
        if self.ref_audio_path:
            target_voice = f"Giọng mẫu ({os.path.basename(self.ref_audio_path)[:10]})"
        elif self.preset_var.get() and self.preset_var.get() != "Mặc định":
            target_voice = self.preset_var.get()

        for r in self.rows_list:
            r['voice_cb']['values'] = self.get_available_voices()
            r['voice_var'].set(target_voice)

        self.main_window.set_status(f"✓ Đã áp dụng giọng '{target_voice}' cho tất cả {len(self.rows_list)} dòng.", progress=None)

    def _update_pattern_preview(self):
        """Cập nhật ví dụ hiển thị mẫu tên file"""
        pat = self.naming_pattern_var.get().strip() or "line_{index}_{text}"
        fmt = self.format_var.get().lower()
        ex_text = "Hello_world"
        name = pat.replace("{index}", "001").replace("{text}", ex_text).replace("{timestamp}", time.strftime("%H%M%S"))
        self.pattern_preview_lbl.config(text=f"Ví dụ tên file: {name}.{fmt}")

    # ---------------- File Import & Helpers ----------------
    def _import_batch_file(self):
        path = filedialog.askopenfilename(
            title="Chọn file văn bản (TXT hoặc CSV)",
            filetypes=[("Văn bản & Bảng CSV", "*.txt *.csv"), ("Tất cả các file", "*.*")]
        )
        if path:
            try:
                extracted_lines = parse_batch_file(path)
                if not extracted_lines:
                    messagebox.showwarning("File rỗng", "Không tìm thấy nội dung văn bản hợp lệ trong file đã chọn.")
                    return

                self.clear_all_rows()
                for line in extracted_lines:
                    self.add_row_item(line)

                fname = os.path.basename(path)
                self.main_window.set_status(f"✓ Đã nhập thành công {len(extracted_lines)} dòng từ file {fname}", progress=None)
            except Exception as e:
                logger.error("Lỗi khi đọc file batch: %s", e, exc_info=True)
                messagebox.showerror("Lỗi đọc file", str(e))

    def _pick_batch_out_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục xuất batch")
        if d:
            self.batch_out_dir_var.set(d)

    def _pick_ref_audio(self):
        p = filedialog.askopenfilename(title="Chọn file giọng mẫu", filetypes=[("Audio files", "*.wav *.flac *.mp3")])
        if p:
            self.ref_audio_path = p
            self.ref_var.set(f"Giọng: {os.path.basename(p)}")
            vlist = self.get_available_voices()
            for r in self.rows_list:
                r['voice_cb']['values'] = vlist

    def _clear_ref_audio(self):
        self.ref_audio_path = None
        self.ref_var.set("Mặc định")
        vlist = self.get_available_voices()
        for r in self.rows_list:
            r['voice_cb']['values'] = vlist

    def _on_preset_selected(self, event):
        p_name = self.preset_var.get()
        if p_name in self.presets:
            p_path = self.presets[p_name]
            if os.path.exists(p_path):
                self.ref_audio_path = p_path
                self.ref_var.set(f"Preset: {p_name}")

    def _on_quick_param_selected(self, event):
        pname = self.quick_param_var.get()
        if pname in getattr(self, 'quick_presets', {}):
            p = self.quick_presets[pname]
            self.exag_var.set(p['exag'])
            self.exag_val_lbl.config(text=f"{p['exag']:.2f}")

            self.cfg_var.set(p['cfg'])
            self.cfg_val_lbl.config(text=f"{p['cfg']:.2f}")

            self.temp_var.set(p['temp'])
            self.temp_val_lbl.config(text=f"{p['temp']:.2f}")

    # ---------------- Execution & Results ----------------
    def preview_single_row(self, text, voice_name):
        """Đọc thử 1 dòng cụ thể"""
        if not text:
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản cho dòng này.")
            return

        ref_p = self.ref_audio_path
        if voice_name in self.presets:
            ref_p = self.presets[voice_name]

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)

        def callback(success, result):
            if success:
                self.audio_player.pack(fill="x", padx=14, pady=(0, 8), before=self.res_body)
                self.audio_player.load_audio(tmp_path)
                self.audio_player.play()
                self.main_window.set_status("▶ Đang đọc thử dòng...", progress=None)
            else:
                messagebox.showerror("Lỗi", str(result))

        self.main_window.set_status("⏳ Đang sinh giọng đọc thử...", progress="indeterminate")
        run_in_background(
            self.engine.generate_tts,
            callback,
            self,
            text=text,
            ref_path=ref_p,
            model_name=self.main_window.get_active_model_name(),
            exag=self.exag_var.get(),
            cfg=self.cfg_var.get(),
            temp=self.temp_var.get(),
            seed=self.seed_var.get(),
            is_random_seed=self.random_seed_var.get(),
            out_path=tmp_path
        )

    # ---------------- Timer & Dual Progress Helpers ----------------
    def _start_timer_loop(self):
        if self._timer_after_id:
            try:
                self.after_cancel(self._timer_after_id)
            except Exception:
                pass
        self._update_timer_loop()

    def _update_timer_loop(self):
        if not getattr(self, 'batch_is_running', False):
            return

        elapsed_sec = int(time.time() - self.batch_start_time)
        rem_sec = max(0, getattr(self, 'batch_estimated_eta_sec', 0))
        total_sec = elapsed_sec + rem_sec

        def fmt_p(sec):
            sec = max(0, int(sec))
            m = sec // 60
            s = sec % 60
            return f"{m}p{s:02d}s" if m > 0 else f"{s}s"

        elapsed_str = fmt_p(elapsed_sec)
        total_str = fmt_p(total_sec)
        rem_str = fmt_p(rem_sec)

        self.batch_timer_lbl.config(text=f"⏱ Đã chạy: {elapsed_str} | Dự kiến tổng: {total_str} (còn ~{rem_str})")
        self._timer_after_id = self.after(500, self._update_timer_loop)

    def _update_current_item_prog(self, orig_idx, item_pct):
        self.batch_item_bar['value'] = item_pct
        self.batch_item_lbl.config(text=f"⚡ Tiến trình dòng hiện tại (#{orig_idx}): {item_pct}% (Sampling...)")
        # Đổi viền VÀNG & cập nhật % tiến độ cho dòng đang chạy
        for r in self.rows_list:
            if r.get('orig_idx') == orig_idx:
                r['frame'].config(highlightbackground="#f59e0b", highlightthickness=2)
                r['lbl_pct'].config(text=f"{item_pct}%", fg="#fbbf24")

    def _mark_item_result_state(self, orig_idx, success):
        """Cập nhật viền XANH LÁ (hoàn thành) hoặc ĐỎ (lỗi) cho từng dòng khi xong"""
        for r in self.rows_list:
            if r.get('orig_idx') == orig_idx:
                if success:
                    r['frame'].config(highlightbackground="#10b981", highlightthickness=2)
                    r['lbl_pct'].config(text="100%", fg="#34d399")
                else:
                    r['frame'].config(highlightbackground="#ef4444", highlightthickness=2)
                    r['lbl_pct'].config(text="❌ Lỗi", fg="#f87171")

    def _update_total_prog(self, completed_cnt, total_cnt, overall_pct):
        self.batch_total_bar['value'] = overall_pct
        self.batch_total_lbl.config(text=f"📦 Tiến trình tổng: {completed_cnt}/{total_cnt} câu ({overall_pct}%)")

    def run_batch_action(self):
        """Chạy toàn bộ đợt Batch các dòng"""
        if not self.rows_list:
            messagebox.showwarning("Không có dữ liệu", "Vui lòng thêm ít nhất 1 dòng văn bản để chạy batch.")
            return

        items = []
        for i, r in enumerate(self.rows_list, 1):
            t = r['txt_box'].get("1.0", "end").strip()
            v = r['voice_var'].get()
            if t:
                items.append((i, t, v))

        if not items:
            messagebox.showwarning("Dữ liệu rỗng", "Tất cả các dòng hiện tại đều chưa có nội dung văn bản.")
            return

        out_dir = Path(self.batch_out_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        # Khóa tất cả các ô nhập liệu và nút bấm
        self.set_batch_inputs_enabled(False)

        # Reset màu viền và % của tất cả các dòng về mặc định
        for r in self.rows_list:
            r['frame'].config(highlightbackground=BORDER_COLOR, highlightthickness=2)
            r['lbl_pct'].config(text="0%", fg="#64748b")

        pat = self.naming_pattern_var.get().strip() or "line_{index}_{text}"
        fmt = self.format_var.get().lower()
        merge_all = self.merge_all_var.get()
        silence_sec = self.silence_sec_var.get()
        m_name = self.main_window.get_active_model_name() or "Chatterbox Standard (500M)"

        self.batch_results = []
        self.merged_file_path = None
        self.batch_start_time = time.time()
        self.batch_is_running = True
        self.batch_estimated_eta_sec = len(items) * 3
        self._timer_after_id = None

        self.batch_total_bar['value'] = 0
        self.batch_item_bar['value'] = 0
        self.batch_total_lbl.config(text=f"📦 Tiến trình tổng: 0/{len(items)} câu (0%)")
        self.batch_item_lbl.config(text="⚡ Tiến trình dòng hiện tại: Đang khởi tạo...")
        self._start_timer_loop()

        num_workers = max(1, self.max_workers_var.get())

        def batch_process():
            # Tối ưu hóa phân bổ luồng CPU của PyTorch để các worker chạy song song thực sự không tranh chấp CPU
            try:
                import torch
                total_cpus = os.cpu_count() or 4
                threads_per_worker = max(1, total_cpus // num_workers)
                torch.set_num_threads(threads_per_worker)
                logger.info("Đã cấu hình PyTorch CPU Threads: %d luồng / worker (Tổng: %d workers)", threads_per_worker, num_workers)
            except Exception:
                pass

            total = len(items)
            results_map = {}
            temp_paths_to_clean = []
            completed_cnt = 0

            def process_single_item(item_data):
                orig_idx, line_text, voice_name = item_data
                ref_p = self.ref_audio_path
                if voice_name in self.presets:
                    ref_p = self.presets[voice_name]

                if merge_all:
                    tmp_fd, tmp_file = tempfile.mkstemp(suffix=f".{fmt}")
                    os.close(tmp_fd)
                    target_out_path = tmp_file
                    temp_paths_to_clean.append(tmp_file)
                else:
                    clean_text = "".join(c for c in line_text if c.isalnum() or c in " _-")[:20]
                    fname = pat.replace("{index}", f"{orig_idx:03d}").replace("{text}", clean_text).replace("{timestamp}", time.strftime("%H%M%S"))
                    target_out_path = str(out_dir / f"{fname}.{fmt}")

                try:
                    self.engine.generate_tts(
                        text=line_text,
                        ref_path=ref_p,
                        model_name=m_name,
                        exag=self.exag_var.get(),
                        cfg=self.cfg_var.get(),
                        temp=self.temp_var.get(),
                        seed=self.seed_var.get(),
                        is_random_seed=self.random_seed_var.get(),
                        out_path=target_out_path,
                        progress_callback=lambda c, t, p, s, e, idx=orig_idx: self.after(0, lambda: self._update_current_item_prog(idx, s))
                    )
                    return {'status': True, 'path': target_out_path, 'text': line_text, 'index': orig_idx}
                except Exception as e:
                    logger.error("Lỗi xử lý dòng batch #%d: %s", orig_idx, e)
                    return {'status': False, 'path': None, 'text': line_text, 'index': orig_idx, 'error': str(e)}

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_to_item = {executor.submit(process_single_item, item): item for item in items}
                for future in concurrent.futures.as_completed(future_to_item):
                    res = future.result()
                    results_map[res['index']] = res
                    completed_cnt += 1
                    elapsed = time.time() - self.batch_start_time
                    avg_time_per_item = elapsed / completed_cnt
                    rem_items = total - completed_cnt
                    self.batch_estimated_eta_sec = int(rem_items * (avg_time_per_item / num_workers))
                    pct = int((completed_cnt / total) * 100)
                    
                    # Đánh dấu trạng thái XANH LÁ (thành công) hoặc ĐỎ (lỗi) cho dòng vừa chạy xong
                    self.after(0, lambda idx=res['index'], st=res['status']: self._mark_item_result_state(idx, st))
                    self.after(0, lambda c=completed_cnt, t=total, p=pct: self._update_total_prog(c, t, p))

            # Giữ đúng thứ tự ban đầu của các câu thoại
            sorted_results = [results_map[orig_idx] for orig_idx, _, _ in items if orig_idx in results_map]
            generated_paths = [r['path'] for r in sorted_results if r['status'] and r['path']]

            if not merge_all:
                self.batch_results = sorted_results
            else:
                if generated_paths:
                    merged_fname = f"batch_merged_{time.strftime('%Y%m%d_%H%M%S')}.{fmt}"
                    final_merged_path = str(out_dir / merged_fname)
                    if merge_wav_files(generated_paths, final_merged_path, silence_sec):
                        self.merged_file_path = final_merged_path
                        self.batch_results = [{
                            'status': True,
                            'path': final_merged_path,
                            'text': f"File gộp {len(generated_paths)} câu thoại",
                            'index': 1
                        }]

                # Dọn dẹp các file tạm lẻ
                for t_path in temp_paths_to_clean:
                    if os.path.exists(t_path):
                        try:
                            os.remove(t_path)
                        except Exception:
                            pass

        def callback(success, result):
            self.batch_is_running = False
            elapsed_sec = int(time.time() - self.batch_start_time)
            m = elapsed_sec // 60
            s = elapsed_sec % 60
            tot_str = f"{m}p{s:02d}s" if m > 0 else f"{s}s"

            # Mở khóa lại các ô nhập liệu
            self.set_batch_inputs_enabled(True)

            self.batch_total_bar['value'] = 100
            self.batch_item_bar['value'] = 100
            self.batch_total_lbl.config(text=f"📦 Tiến trình tổng: {len(items)}/{len(items)} câu (100%)")
            self.batch_item_lbl.config(text="✓ Tất cả các dòng đã hoàn thành!")
            self.batch_timer_lbl.config(text=f"⏱ Tổng thời gian xử lý: {tot_str} | ✓ Hoàn thành!")
            self.main_window.set_status("✓ Hoàn thành Batch!", progress=100)

            # Thêm vào history toàn cục
            for res in self.batch_results:
                if res['status'] and res['path']:
                    self.main_window.add_to_history(res['path'], f"Batch: {res['text'][:30]}")

            self._render_results_ui()
            if merge_all and self.merged_file_path:
                messagebox.showinfo("Hoàn tất Batch", f"Đã gộp thành công {len(items)} câu thoại vào 1 FILE DUY NHẤT tại:\n{self.merged_file_path}")
            else:
                ok_cnt = sum(1 for r in self.batch_results if r['status'])
                messagebox.showinfo("Hoàn tất Batch", f"Đã xuất thành công {ok_cnt}/{len(items)} file WAV tại:\n{out_dir}")

        run_in_background(batch_process, callback, self)

    def _update_batch_prog(self, msg, val):
        self.batch_prog_lbl.config(text=msg)
        self.batch_prog_bar['value'] = val
        self.main_window.set_status(f"⚡ {msg}", progress=val)

    # ---------------- Render Rich Results UI & Empty State ----------------
    def _render_results_ui(self):
        """Vẽ danh sách kết quả đợt vừa chạy với Selector On-top và Audio Player tích hợp ở bên dưới"""
        for w in self.res_body.winfo_children():
            w.destroy()

        if not self.batch_results:
            empty_frame = tk.Frame(self.res_body, bg=PANEL2_BG, pady=30)
            empty_frame.pack(fill="both", expand=True)

            tk.Label(empty_frame, text="📦", font=("Segoe UI", 28), fg=TEXT_DIM_COLOR, bg=PANEL2_BG).pack(pady=(10, 4))
            tk.Label(empty_frame, text="Chưa có kết quả đợt Batch nào", font=("Segoe UI", 10, "bold"), fg=TEXT_COLOR, bg=PANEL2_BG).pack()
            tk.Label(empty_frame, text="Kết quả các file âm thanh sẽ tự động hiển thị ở đây\nsau khi bạn bấm '⚡ Bắt đầu tạo hàng loạt'",
                     font=("Segoe UI", 9), fg=TEXT_DIM_COLOR, bg=PANEL2_BG, justify="center").pack(pady=(4, 10))
            self.res_badge.config(text="0 file")
            self.audio_player.pack_forget()
            return

        self.res_badge.config(text=f"{len(self.batch_results)} file")

        # Hiển thị Trình phát âm thanh tích hợp cố định bên dưới khung kết quả
        self.audio_player.pack(fill="x", padx=14, pady=(0, 10))

        # 1. On-top Selector Combobox cho phép chọn nhanh voice vừa tạo để nghe thử
        sel_row = tk.Frame(self.res_body, bg=PANEL2_BG)
        sel_row.pack(fill="x", pady=(0, 6))

        tk.Label(sel_row, text="🎧 Chọn voice nghe thử:", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg=PANEL2_BG).pack(side="left", padx=(0, 6))

        self.res_items_map = {}
        cb_options = []

        if self.merged_file_path and os.path.exists(self.merged_file_path):
            opt_title = "🎵 File Gộp Tất Cả (Merged Audio)"
            cb_options.append(opt_title)
            self.res_items_map[opt_title] = self.merged_file_path

        for res in self.batch_results:
            if res['status'] and res['path'] and os.path.exists(res['path']):
                fn = os.path.basename(res['path'])
                opt_title = f"#{res['index']}: {res['text'][:25]}... ({fn})"
                cb_options.append(opt_title)
                self.res_items_map[opt_title] = res['path']

        self.res_select_var = tk.StringVar()
        self.res_select_cb = ttk.Combobox(sel_row, textvariable=self.res_select_var, state="readonly", values=cb_options)
        self.res_select_cb.pack(side="left", fill="x", expand=True)
        self.res_select_cb.bind("<<ComboboxSelected>>", self._on_res_select_changed)

        # 2. Scrollable Canvas danh sách các thẻ file kết quả
        res_scroll_frame = tk.Frame(self.res_body, bg=PANEL2_BG)
        res_scroll_frame.pack(fill="both", expand=True)

        res_canvas = tk.Canvas(res_scroll_frame, bg=PANEL2_BG, highlightthickness=0, bd=0)
        res_sbar = ttk.Scrollbar(res_scroll_frame, orient="vertical", command=res_canvas.yview)
        res_inner = tk.Frame(res_canvas, bg=PANEL2_BG)

        res_inner.bind("<Configure>", lambda e: res_canvas.configure(scrollregion=res_canvas.bbox("all")))
        res_win = res_canvas.create_window((0, 0), window=res_inner, anchor="nw")
        res_canvas.configure(yscrollcommand=res_sbar.set)
        res_canvas.bind("<Configure>", lambda e: res_canvas.itemconfig(res_win, width=e.width))

        res_canvas.pack(side="left", fill="both", expand=True)
        res_sbar.pack(side="right", fill="y")

        # Thẻ File Gộp
        if self.merged_file_path and os.path.exists(self.merged_file_path):
            m_card = tk.Frame(res_inner, bg="#1a2e4a", bd=1, relief="solid", highlightbackground=ACCENT_COLOR)
            m_card.pack(fill="x", pady=(0, 6))

            m_row = tk.Frame(m_card, bg="#1a2e4a")
            m_row.pack(fill="x", padx=8, pady=6)

            tk.Label(m_row, text="🎵 File Gộp Tất Cả (Merged Audio)", font=("Segoe UI", 9, "bold"), fg="#a7f3d0", bg="#1a2e4a").pack(side="left")

            btn_box = tk.Frame(m_row, bg="#1a2e4a")
            btn_box.pack(side="right")

            tk.Button(btn_box, text="▶ Play", font=("Segoe UI", 8, "bold"), bg=ACCENT_COLOR, fg="#ffffff", bd=0, padx=6, pady=2, cursor="hand2",
                      command=lambda: self._play_res_file(self.merged_file_path)).pack(side="left", padx=2)

            tk.Button(btn_box, text="📂 Mở", font=("Segoe UI", 8), bg="#24344d", fg=TEXT_COLOR, bd=0, padx=6, pady=2, cursor="hand2",
                      command=lambda: self._open_res_dir(self.merged_file_path)).pack(side="left", padx=2)

        # Thẻ các file đơn lẻ
        for res in self.batch_results:
            row_card = tk.Frame(res_inner, bg="#0e1621", bd=1, relief="solid", highlightbackground=BORDER_COLOR)
            row_card.pack(fill="x", pady=3)

            r_line = tk.Frame(row_card, bg="#0e1621")
            r_line.pack(fill="x", padx=8, pady=4)

            if res['status']:
                st_lbl = tk.Label(r_line, text="✓ Successful", font=("Segoe UI", 8, "bold"), fg="#34d399", bg="#064e3b", padx=6, pady=1)
            else:
                st_lbl = tk.Label(r_line, text="❌ Error", font=("Segoe UI", 8, "bold"), fg="#f87171", bg="#4c1d1d", padx=6, pady=1)
            st_lbl.pack(side="left", padx=(0, 6))

            fname = os.path.basename(res['path']) if res['path'] else f"Dòng #{res['index']}"
            t_str = f"#{res['index']}: {res['text'][:20]}... ({fname})"
            tk.Label(r_line, text=t_str, font=("Segoe UI", 9), fg=TEXT_COLOR, bg="#0e1621", anchor="w").pack(side="left", fill="x", expand=True)

            if res['status'] and res['path'] and os.path.exists(res['path']):
                b_frame = tk.Frame(r_line, bg="#0e1621")
                b_frame.pack(side="right")

                tk.Button(b_frame, text="▶", font=("Segoe UI", 8, "bold"), bg=ACCENT_COLOR, fg="#ffffff", bd=0, width=2, cursor="hand2",
                          command=lambda p=res['path']: self._play_res_file(p)).pack(side="left", padx=1)
                tk.Button(b_frame, text="📂", font=("Segoe UI", 8), bg="#1a2536", fg=TEXT_COLOR, bd=0, width=2, cursor="hand2",
                          command=lambda p=res['path']: self._open_res_dir(p)).pack(side="left", padx=1)

        # Tự động chọn item đầu tiên vào Combobox và phát thử
        if cb_options:
            self.res_select_cb.set(cb_options[0])
            first_path = self.res_items_map.get(cb_options[0])
            if first_path:
                self.audio_player.load_audio(first_path)

    def _on_res_select_changed(self, event):
        opt = self.res_select_var.get()
        if opt in getattr(self, 'res_items_map', {}):
            path = self.res_items_map[opt]
            self._play_res_file(path)

    def _play_res_file(self, file_path):
        if file_path and os.path.exists(file_path):
            self.audio_player.load_audio(file_path)
            self.audio_player.play()

    def _open_res_dir(self, file_path):
        if file_path:
            folder = os.path.dirname(file_path)
            if os.path.exists(folder):
                try:
                    subprocess.Popen(["xdg-open", folder])
                except Exception as e:
                    messagebox.showerror("Lỗi mở thư mục", str(e))
