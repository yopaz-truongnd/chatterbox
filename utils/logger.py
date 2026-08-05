"""
Cấu hình Logger hệ thống thời gian thực cho Chatterbox Studio
"""

import sys
import io
import logging

# Thiết lập encoding UTF-8 cho dòng xuất chuẩn trên Windows
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

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
