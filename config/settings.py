"""
Settings Manager - Quản lý cài đặt dự án Chatterbox TTS Studio
"""

import os
import json
from pathlib import Path
from utils.logger import logger

SETTINGS_FILE = Path("config/settings.json")

cpu_count = os.cpu_count() or 4
default_cpu_threads = max(1, min(4, cpu_count - 2 if cpu_count > 2 else cpu_count))

DEFAULT_SETTINGS = {
    "export_dir": os.path.expanduser("~/Downloads"),
    "model_cache_dir": str(Path("/var/www/chatterbox/models").absolute()),
    "auto_open_export_dir": True,
    "device": "auto",
    "default_startup_model": "Chatterbox Standard (500M)",
    "max_chunk_chars": 4000,
    "auto_unload_models": False,
    "desktop_notifications": True,
    "confirm_delete_history": True,
    # Cấu hình Phần cứng & Chống treo máy
    "cpu_threads_limit": default_cpu_threads,
    "process_priority": "low",  # "low" (Thấp hơn - Tránh đơ OS/UI) hoặc "normal"
    "max_vram_fraction": 80,    # 80% VRAM GPU tối đa
    "force_gc_after_gen": True,
    "max_batch_workers": 2
}

class SettingsManager:
    def __init__(self, filepath=SETTINGS_FILE):
        self.filepath = Path(filepath)
        self.settings = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings.update(data)
                logger.info("Đã tải cài đặt từ %s", self.filepath)
            except Exception as e:
                logger.error("Lỗi khi nạp settings.json: %s", e)
        else:
            self.save()

    def save(self):
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            logger.info("Đã lưu cài đặt vào %s", self.filepath)
        except Exception as e:
            logger.error("Lỗi khi lưu settings.json: %s", e)

    def get(self, key, default=None):
        return self.settings.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        self.settings[key] = value

    def reset_defaults(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.save()

# Singleton instance for easy import across the project
settings_manager = SettingsManager()
