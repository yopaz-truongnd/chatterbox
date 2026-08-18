"""
Custom HTML5-like Audio Player Widget cho Tkinter
"""

import os
import wave
import time
import threading
import tkinter as tk
from tkinter import ttk
import pygame

from config.constants import ACCENT_COLOR, PANEL2_BG, BORDER_COLOR, TEXT_COLOR, TEXT_DIM_COLOR, UI_FONT
from ui.components.waveform_canvas import WaveformCanvas
from utils.logger import logger

def format_time(seconds):
    """Định dạng số giây thành chuỗi mm:ss"""
    if not seconds or seconds < 0:
        return "00:00"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

class AudioPlayerWidget(tk.Frame):
    """
    Khối giao diện phát âm thanh phong cách HTML5 Audio Player
    Bao gồm: Play/Pause, Stop, Seekbar tua thời gian real-time, Waveform, Âm lượng & Nút Xóa/Reset
    """
    def __init__(self, parent, engine, on_delete=None, **kwargs):
        super().__init__(parent, bg="#0c1421", bd=1, relief="solid", highlightbackground=BORDER_COLOR, highlightthickness=1, **kwargs)
        self.engine = engine
        self.on_delete = on_delete
        self.current_file = None
        self.duration_sec = 0.0
        self.is_playing = False
        self.is_paused = False
        self.start_time = 0.0
        self.pause_offset = 0.0
        self._timer_id = None

        self._build_ui()

    def _build_ui(self):
        # Header / Title row
        hdr = tk.Frame(self, bg="#0c1421")
        hdr.pack(fill="x", padx=12, pady=(6, 2))

        self.title_lbl = tk.Label(hdr, text="🎵 Trình phát âm thanh (Audio Player)", font=(UI_FONT, 9, "bold"), fg="#a9c3ff", bg="#0c1421")
        self.title_lbl.pack(side="left")

        self.time_lbl = tk.Label(hdr, text="00:00 / 00:00", font=(UI_FONT, 9, "bold"), fg=TEXT_DIM_COLOR, bg="#0c1421")
        self.time_lbl.pack(side="right")

        # Waveform Display Canvas inside Player
        self.waveform = WaveformCanvas(self, height=32, bg="#080e18", on_seek=self._on_waveform_seek)
        self.waveform.pack(fill="x", padx=12, pady=(2, 4))

        # Control Toolbar Row
        ctrl_row = tk.Frame(self, bg="#0c1421")
        ctrl_row.pack(fill="x", padx=12, pady=(2, 8))

        # Play / Pause Button
        self.play_btn = tk.Button(ctrl_row, text="▶", font=(UI_FONT, 11, "bold"), bg=ACCENT_COLOR, fg="#ffffff",
                                  activebackground="#6fa0ff", activeforeground="#ffffff", bd=0, width=3, height=1,
                                  cursor="hand2", command=self.toggle_play_pause, state="disabled")
        self.play_btn.pack(side="left", padx=(0, 6))

        # Stop Button
        self.stop_btn = tk.Button(ctrl_row, text="■", font=(UI_FONT, 11, "bold"), bg="#1a2536", fg=TEXT_COLOR,
                                  activebackground="#e11d48", activeforeground="#ffffff", bd=1, relief="solid",
                                  width=3, height=1, cursor="hand2", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))

        # Progress / Seek Bar
        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_scale = ttk.Scale(ctrl_row, variable=self.seek_var, from_=0.0, to=100.0, orient="horizontal", command=self._on_seek)
        self.seek_scale.pack(side="left", fill="x", expand=True, padx=(0, 12))

        # Volume Icon & Slider
        tk.Label(ctrl_row, text="🔊", font=(UI_FONT, 10), fg=TEXT_DIM_COLOR, bg="#0c1421").pack(side="left", padx=(0, 2))
        self.vol_var = tk.DoubleVar(value=100.0)
        vol_scale = ttk.Scale(ctrl_row, variable=self.vol_var, from_=0.0, to=100.0, orient="horizontal", length=60, command=self._on_vol_change)
        vol_scale.pack(side="left")

        # Delete / Reset Button
        self.del_btn = tk.Button(ctrl_row, text="🗑 Xóa", font=(UI_FONT, 9, "bold"), bg="#1a2536", fg="#f87171",
                                 activebackground="#e11d48", activeforeground="#ffffff", bd=1, relief="solid",
                                 padx=8, pady=2, cursor="hand2", command=self.clear_audio, state="disabled")
        self.del_btn.pack(side="right", padx=(8, 0))

    def load_audio(self, file_path):
        """Tải file âm thanh mới vào Player và cập nhật giao diện"""
        self.stop()
        if not file_path or not os.path.exists(file_path):
            self.clear_audio()
            return

        self.current_file = file_path
        self.waveform.set_audio_file(file_path)

        # Tính thời lượng file audio bằng wave module
        try:
            with wave.open(file_path, "r") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                self.duration_sec = frames / float(rate) if rate > 0 else 0.0
        except Exception:
            self.duration_sec = 0.0

        fname = os.path.basename(file_path)
        self.title_lbl.config(text=f"🎵 {fname}")
        self.time_lbl.config(text=f"00:00 / {format_time(self.duration_sec)}")

        self.seek_scale.config(to=max(1.0, self.duration_sec))
        self.seek_var.set(0.0)

        self.play_btn.config(state="normal", text="▶")
        self.stop_btn.config(state="normal")
        self.del_btn.config(state="normal")

    def toggle_play_pause(self):
        """Chuyển đổi trạng thái Phát / Tạm dừng"""
        if not self.current_file or not os.path.exists(self.current_file):
            return

        if self.is_playing and not self.is_paused:
            # Đang phát -> Tạm dừng
            try:
                pygame.mixer.music.pause()
                self.is_paused = True
                self.play_btn.config(text="▶")
            except Exception:
                pass
        elif self.is_paused:
            # Đang tạm dừng -> Tiếp tục phát từ vị trí pause
            try:
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.start_time = time.time() - self.pause_offset
                self.play_btn.config(text="⏸")
                self._start_timer()
            except Exception:
                pass
        else:
            # Chưa phát -> Khởi chạy phát từ vị trí pause_offset
            self.play_at(self.pause_offset)

    def play(self):
        """Phát âm thanh từ đầu (0.0s)"""
        self.play_at(0.0)

    def play_at(self, start_sec):
        """Phát âm thanh từ điểm thời gian cụ thể (start_sec)"""
        if not self.current_file or not os.path.exists(self.current_file):
            return

        start_sec = max(0.0, min(self.duration_sec, float(start_sec)))

        try:
            self._cancel_timer()
            pygame.mixer.music.stop()
            pygame.mixer.music.load(self.current_file)
            pygame.mixer.music.play(start=start_sec)

            self.is_playing = True
            self.is_paused = False
            self.start_time = time.time() - start_sec
            self.pause_offset = start_sec

            self.play_btn.config(text="⏸", state="normal")
            self.stop_btn.config(state="normal")
            self._start_timer()
        except Exception as e:
            logger.error("Lỗi khi phát nhạc từ mốc %s: %s", start_sec, e)

    def stop(self):
        """Dừng hoàn toàn phát âm thanh và đưa về đầu"""
        self._cancel_timer()
        try:
            self.engine.stop_audio()
        except Exception:
            pass

        self.is_playing = False
        self.is_paused = False
        self.pause_offset = 0.0
        self.seek_var.set(0.0)
        self.waveform.set_progress(0.0)
        self.play_btn.config(text="▶")
        self.time_lbl.config(text=f"00:00 / {format_time(self.duration_sec)}")

    def clear_audio(self):
        """Xóa file âm thanh vừa render và reset hoàn toàn Trình phát âm thanh"""
        self.stop()
        if self.current_file and os.path.exists(self.current_file):
            try:
                os.remove(self.current_file)
            except Exception as e:
                logger.warning("Could not remove temp audio file: %s", e)

        self.current_file = None
        self.duration_sec = 0.0
        self.title_lbl.config(text="🎵 Chưa có file âm thanh")
        self.time_lbl.config(text="00:00 / 00:00")
        self.play_btn.config(state="disabled", text="▶")
        self.stop_btn.config(state="disabled")
        self.del_btn.config(state="disabled")
        self.seek_var.set(0.0)
        self.waveform.set_audio_file(None)

        try:
            self.pack_forget()
        except Exception:
            pass

        if self.on_delete:
            self.on_delete()

    def _start_timer(self):
        self._cancel_timer()
        self._update_loop()

    def _cancel_timer(self):
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def _update_loop(self):
        if not self.is_playing or self.is_paused:
            return

        # Kiểm tra pygame mixer có đang bận phát không
        if pygame.mixer.music.get_busy():
            elapsed = time.time() - self.start_time
            self.pause_offset = elapsed
            if elapsed > self.duration_sec:
                elapsed = self.duration_sec

            self.seek_var.set(elapsed)
            self.time_lbl.config(text=f"{format_time(elapsed)} / {format_time(self.duration_sec)}")
            if self.duration_sec > 0:
                self.waveform.set_progress(elapsed / self.duration_sec)
            self._timer_id = self.after(100, self._update_loop)
        else:
            # Đã phát xong hết file
            self.stop()

    def _on_seek(self, val):
        """Sự kiện kéo thanh seekbar"""
        try:
            target_sec = float(val)
            self.time_lbl.config(text=f"{format_time(target_sec)} / {format_time(self.duration_sec)}")
            if self.duration_sec > 0:
                self.waveform.set_progress(target_sec / self.duration_sec)
            
            # Nếu đang phát -> Nhảy tới điểm kéo phát tiếp ngay
            if self.is_playing and not self.is_paused:
                self.play_at(target_sec)
            else:
                self.pause_offset = target_sec
        except Exception:
            pass

    def _on_waveform_seek(self, pct):
        """Sự kiện click trực tiếp lên Waveform"""
        if self.duration_sec > 0:
            target_sec = pct * self.duration_sec
            self.seek_var.set(target_sec)
            self.time_lbl.config(text=f"{format_time(target_sec)} / {format_time(self.duration_sec)}")
            self.waveform.set_progress(pct)

            # Nếu đang phát -> Nhảy tới điểm click phát tiếp ngay
            if self.is_playing and not self.is_paused:
                self.play_at(target_sec)
            else:
                self.pause_offset = target_sec

    def _on_vol_change(self, val):
        """Sự kiện chỉnh âm lượng 0..100"""
        try:
            v = float(val) / 100.0
            pygame.mixer.music.set_volume(v)
        except Exception:
            pass
