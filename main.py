"""
Chatterbox TTS Studio - Điểm khởi chạy ứng dụng (Main Entry Point)
"""

import os
import json
import gc
import time
import threading
from pathlib import Path

# Load settings and configure model cache directory
PROJECT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = PROJECT_DIR / "config/settings.json"
def get_model_cache_dir():
    default_dir = PROJECT_DIR / "models"
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_dir = data.get("model_cache_dir")
                if custom_dir:
                    default_dir = Path(custom_dir).absolute()
                hf_token = data.get("hf_token")
                if hf_token:
                    os.environ["HF_TOKEN"] = hf_token
        except Exception:
            pass
    else:
        # Create default settings file
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"model_cache_dir": str(default_dir), "hf_token": ""}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return default_dir

cache_dir = get_model_cache_dir()
cache_dir.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(cache_dir)
os.environ["HF_HUB_CACHE"] = str(cache_dir)

# Cấu hình thư mục tạm trong dự án thay vì hệ thống
import tempfile
TMP_DIR = PROJECT_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TMP_DIR)
os.environ["TMPDIR"] = str(TMP_DIR)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMP"] = str(TMP_DIR)

import tkinter as tk
from utils.logger import logger
from core.chatterbox_engine import ChatterboxEngine
from ui.main_window import MainWindow
from utils.platform_tools import select_device

def main():
    logger.info("Khởi chạy ứng dụng Chatterbox TTS Studio...")
    logger.info("Thư mục lưu trữ model hiện tại: %s", cache_dir)
    
    try:
        import tkinterdnd2
        root = tkinterdnd2.TkinterDnD.Tk()
        logger.info("Đã nạp thành công bộ hỗ trợ Kéo-Thả TkinterDnD2!")
    except Exception as e:
        logger.warning("Không nạp được TkinterDnD2 (%s), chuyển sang tk.Tk() mặc định", e)
        root = tk.Tk()

    root.title("Chatterbox TTS Studio")
    
    # Thiết lập màu nền mặc định cho cửa sổ chính theo Material Design 3
    from config.constants import BG_COLOR
    root.configure(bg=BG_COLOR)

    # Khởi tạo engine xử lý AI Core
    device = select_device()
    engine = ChatterboxEngine(device=device)

    # Khởi tạo Giao diện MainWindow
    app = MainWindow(root, engine)

    # Khởi chạy main loop
    root.mainloop()

if __name__ == "__main__":
    main()
