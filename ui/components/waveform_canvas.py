"""
Custom Canvas widget vẽ biểu đồ sóng âm thanh (Waveform) cho các file audio
"""

import os
import random
import threading
import tkinter as tk
import torchaudio as ta
from utils.logger import logger

class WaveformCanvas(tk.Canvas):
    """Custom Canvas widget rendering vertical waveform bars from audio files."""
    def __init__(self, parent, height=34, bg="#0e1621", **kwargs):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.num_bars = 60
        self.draw_placeholder()

    def draw_placeholder(self):
        self.delete("all")
        w = self.winfo_width() or 300
        h = self.winfo_height() or 34
        bar_w = max(2, (w - self.num_bars * 2) / self.num_bars)

        for i in range(self.num_bars):
            x = i * (bar_w + 2) + 4
            bh = random.randint(4, max(6, int(h * 0.4)))
            y1 = (h - bh) / 2
            y2 = y1 + bh
            self.create_line(x, y1, x, y2, fill="#243149", width=bar_w)

    def set_audio_file(self, file_path):
        if not file_path or not os.path.exists(file_path):
            self.draw_placeholder()
            return

        def load_thread():
            try:
                waveform, sr = ta.load(file_path)
                data = waveform.abs().mean(dim=0).numpy()
                step = max(1, len(data) // self.num_bars)
                sampled = [data[i:i+step].mean() for i in range(0, len(data), step)][:self.num_bars]
                
                # Normalize height
                max_val = max(sampled) if max(sampled) > 0 else 1.0
                norm = [float(v / max_val) for v in sampled]
                
                self.after(0, lambda: self.draw_waveform(norm))
            except Exception as e:
                logger.warning("Could not render waveform for %s: %s", file_path, e)
                self.after(0, self.draw_placeholder)

        threading.Thread(target=load_thread, daemon=True).start()

    def draw_waveform(self, norm_data):
        self.delete("all")
        w = self.winfo_width() or 300
        h = self.winfo_height() or 34
        bar_w = max(2, (w - len(norm_data) * 2) / len(norm_data))

        for i, val in enumerate(norm_data):
            x = i * (bar_w + 2) + 4
            bh = max(4, int(val * (h - 6)))
            y1 = (h - bh) / 2
            y2 = y1 + bh
            self.create_line(x, y1, x, y2, fill="#4f8cff", width=bar_w)
