"""
Cấu hình Logger hệ thống thời gian thực cho Chatterbox Studio & Interceptor tiến độ Sampling
"""

import sys
import io
import re
import logging
import threading

# Quản lý Callback tiến độ real-time từ tqdm / stdout / stderr qua Thread-Local
_thread_local = threading.local()

def set_active_progress_callback(cb):
    _thread_local.cb = cb

def get_active_progress_callback():
    return getattr(_thread_local, 'cb', None)

class StreamProgressInterceptor:
    """Wrapper chặn stdout/stderr để bắt log progress % từ tqdm (Sampling: XX%)"""
    def __init__(self, original_stream):
        self.original_stream = original_stream

    def write(self, data):
        if self.original_stream:
            self.original_stream.write(data)
            self.original_stream.flush()

        if data:
            # Tìm phần trăm % trong tqdm output (ví dụ: "Sampling:  17%", " 35%|", "100%|")
            m = re.search(r"(?:Sampling:\s*|^\s*|\|\s*)(\d+)%", data)
            if not m:
                m = re.search(r"(\d+)%\|", data)
            if m:
                try:
                    pct = int(m.group(1))
                    cb = get_active_progress_callback()
                    if cb:
                        cb(pct)
                except Exception:
                    pass

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()

    def __getattr__(self, name):
        return getattr(self.original_stream, name)


# Thiết lập encoding UTF-8 cho dòng xuất chuẩn trên Windows
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

# Chặn sys.stderr và sys.stdout để bắt progress
if not isinstance(sys.stderr, StreamProgressInterceptor):
    sys.stderr = StreamProgressInterceptor(sys.stderr)
if not isinstance(sys.stdout, StreamProgressInterceptor):
    sys.stdout = StreamProgressInterceptor(sys.stdout)

# Cấu hình logging
logger = logging.getLogger("ChatterboxStudio")
logger.setLevel(logging.INFO)

# Formatter hiển thị thời gian, mức độ lỗi và thông tin log
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

# Stream handler ghi ra CMD Console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler ghi ra file logs cục bộ
try:
    file_handler = logging.FileHandler("chatterbox_studio.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Warning: Could not initialize log file: {e}")

# Kích hoạt realtime console line buffering
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
