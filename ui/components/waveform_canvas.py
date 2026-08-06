"""
Custom Canvas widget vẽ biểu đồ sóng âm thanh (Waveform) hiện đại & tương tác
"""

import os
import math
import wave
import threading
import tkinter as tk
from utils.logger import logger

class WaveformCanvas(tk.Canvas):
    """
    Custom Canvas render biểu đồ sóng âm thanh dạng capsule thanh lịch.
    Hỗ trợ:
    - Hiển thị tiến độ phát thực tế (highlight phần đã phát).
    - Tương tác click / hover để xem thời gian & tua vị trí.
    """
    def __init__(self, parent, height=40, bg="#080e18", num_bars=70, on_seek=None, **kwargs):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2", **kwargs)
        self.num_bars = num_bars
        self.height = height
        self.norm_data = []
        self.progress_pct = 0.0
        self.on_seek = on_seek
        self.is_loaded = False
        
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_click)

        self.draw_placeholder()

    def draw_placeholder(self):
        """Vẽ waveform mẫu hình sin mềm mại khi chưa có file"""
        self.delete("all")
        self.is_loaded = False
        self.norm_data = []
        w = self.winfo_width() or 320
        h = self.height or 40
        
        # Vẽ đường trục trung tâm
        self.create_line(4, h / 2, w - 4, h / 2, fill="#131e2e", width=1)

        bar_w = max(2, (w - 8 - (self.num_bars * 2)) / self.num_bars)

        for i in range(self.num_bars):
            x = 4 + i * (bar_w + 2) + bar_w / 2
            # Tạo hình nón sóng mẫu mềm mại
            sin_val = math.sin(i / self.num_bars * math.pi * 3) * 0.4 + 0.5
            bh = max(4, int(sin_val * (h - 10) * 0.4))
            y1 = (h - bh) / 2
            y2 = y1 + bh

            # Màu thanh xám tối nhẹ
            self.create_line(x, y1, x, y2, fill="#1c293d", width=bar_w, capstyle="round")

    def set_audio_file(self, file_path):
        """Đọc và trích xuất độ cao sóng âm từ file audio"""
        if not file_path or not os.path.exists(file_path):
            self.draw_placeholder()
            return

        def load_thread():
            try:
                # Đọc dữ liệu thô từ file WAV bằng module wave tiêu chuẩn
                with wave.open(file_path, "rb") as wf:
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    n_frames = wf.getnframes()
                    raw_bytes = wf.readframes(n_frames)

                if not raw_bytes or n_frames == 0:
                    self.after(0, self.draw_placeholder)
                    return

                # Chuyển đổi byte thành mảng giá trị biên độ
                step_bytes = n_channels * sampwidth
                total_samples = len(raw_bytes) // step_bytes
                
                # Gom nhóm các mẫu dữ liệu vào num_bars
                samples_per_bar = max(1, total_samples // self.num_bars)
                sampled_amps = []

                for i in range(0, total_samples, samples_per_bar):
                    chunk_bytes = raw_bytes[i * step_bytes : (i + samples_per_bar) * step_bytes]
                    if not chunk_bytes:
                        break
                    
                    # Tính độ cao trung bình của đoạn
                    amp_sum = 0
                    count = 0
                    for j in range(0, len(chunk_bytes), step_bytes):
                        b = chunk_bytes[j:j+step_bytes]
                        if len(b) >= 2:
                            val = int.from_bytes(b[:2], byteorder="little", signed=True)
                            amp_sum += abs(val)
                            count += 1
                    
                    avg_amp = amp_sum / count if count > 0 else 0
                    sampled_amps.append(avg_amp)

                sampled_amps = sampled_amps[:self.num_bars]
                max_amp = max(sampled_amps) if sampled_amps and max(sampled_amps) > 0 else 1.0
                norm = [float(v / max_amp) for v in sampled_amps]

                self.after(0, lambda: self._apply_norm_data(norm))

            except Exception as e:
                logger.warning("Could not parse waveform for %s: %s", file_path, e)
                self.after(0, self.draw_placeholder)

        threading.Thread(target=load_thread, daemon=True).start()

    def _apply_norm_data(self, norm_data):
        self.norm_data = norm_data
        self.is_loaded = True
        self.progress_pct = 0.0
        self.redraw()

    def set_progress(self, progress_pct):
        """Cập nhật tiến độ phát (0.0 đến 1.0) và tô màu tương ứng"""
        self.progress_pct = max(0.0, min(1.0, float(progress_pct)))
        if self.is_loaded:
            self.redraw()

    def redraw(self):
        """Vẽ lại toàn bộ Waveform với phần highlight và đầu kim Playhead"""
        if not self.is_loaded or not self.norm_data:
            self.draw_placeholder()
            return

        self.delete("all")
        w = self.winfo_width() or 320
        h = self.height or 40
        
        # Đường trục trung tâm
        self.create_line(4, h / 2, w - 4, h / 2, fill="#152233", width=1)

        num_bars = len(self.norm_data)
        bar_w = max(2, (w - 8 - (num_bars * 2)) / num_bars)
        playhead_x = 4 + (self.progress_pct * (w - 8))

        for i, val in enumerate(self.norm_data):
            x = 4 + i * (bar_w + 2) + bar_w / 2
            bh = max(4, int(val * (h - 8)))
            y1 = (h - bh) / 2
            y2 = y1 + bh

            # Kiểm tra xem thanh này đã được phát qua hay chưa
            if x <= playhead_x:
                # Đã phát: Màu xanh sáng nổi bật (Vibrant Blue/Cyan)
                fill_color = "#38bdf8"
            else:
                # Chưa phát: Màu xám xanh slate tối trầm
                fill_color = "#1e2d42"

            self.create_line(x, y1, x, y2, fill=fill_color, width=bar_w, capstyle="round")

        # Vẽ vạch Playhead đầu kim định vị vị trí phát hiện tại
        if self.progress_pct > 0:
            self.create_line(playhead_x, 2, playhead_x, h - 2, fill="#60a5fa", width=2)
            self.create_oval(playhead_x - 3, 1, playhead_x + 3, 7, fill="#ffffff", outline="#38bdf8")

    def _on_click(self, event):
        """Sự kiện click vào Waveform để tua vị trí phát"""
        w = self.winfo_width() or 320
        x = event.x - 4
        pct = max(0.0, min(1.0, x / (w - 8)))
        self.set_progress(pct)
        if self.on_seek:
            self.on_seek(pct)
