"""
File Importer Helper - Kiểm tra và trích xuất nội dung văn bản từ file kéo thả (Drag & Drop)
"""

import os
import re
from utils.logger import logger

def parse_drop_filepaths(data_str):
    """
    Trích xuất danh sách đường dẫn file từ chuỗi dữ liệu TkDnD <<Drop>>.
    Xử lý đúng cả đường dẫn có dấu ngoặc nhọn {file path with space} và không ngoặc.
    """
    if not data_str:
        return []

    data_str = data_str.strip()
    
    # Tìm các đường dẫn trong ngoặc nhọn {} trước
    paths = re.findall(r'\{([^}]+)\}', data_str)
    if paths:
        return [p.strip() for p in paths if p.strip()]

    # Nếu không có ngoặc nhọn, tách theo khoảng trắng hoặc dòng
    parts = data_str.splitlines() if "\n" in data_str else [data_str]
    cleaned = []
    for p in parts:
        p = p.strip('"\' ')
        if p and os.path.exists(p):
            cleaned.append(p)
    if cleaned:
        return cleaned

    # Fallback single path
    clean_single = data_str.strip('"\' ')
    return [clean_single] if clean_single else []

def validate_and_read_text_file(file_path):
    """
    Kiểm tra tính hợp lệ của file và đọc nội dung văn bản.
    Nếu là file nhị phân hoặc không phù hợp, ném ngoại lệ ValueError với lý do rõ ràng.
    """
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        raise ValueError(f"File không tồn tại: {os.path.basename(file_path)}")

    if os.path.isdir(file_path):
        raise ValueError(f"'{os.path.basename(file_path)}' là thư mục, không phải file văn bản!")

    ext = os.path.splitext(file_path)[1].lower()
    binary_extensions = {
        '.exe', '.dll', '.bin', '.so', '.dylib', '.png', '.jpg', '.jpeg', '.gif',
        '.bmp', '.webp', '.ico', '.pdf', '.zip', '.rar', '.7z', '.tar', '.gz',
        '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.mp4', '.avi', '.mkv',
        '.mov', '.wmv', '.pyc', '.iso', '.dmg', '.db', '.sqlite'
    }

    if ext in binary_extensions:
        raise ValueError(
            f"Định dạng file '{ext}' không được hỗ trợ!\n"
            "Vui lòng chọn hoặc kéo/thả file văn bản hợp lệ (.txt, .csv, .md, .json, .srt, .vtt)."
        )

    content = None
    for enc in ["utf-8-sig", "utf-8", "utf-16", "latin-1", "cp1252"]:
        try:
            with open(file_path, "r", encoding=enc) as f:
                raw = f.read()
            if "\x00" in raw[:2048]:
                raise ValueError("File chứa dữ liệu nhị phân không hợp lệ!")
            content = raw
            break
        except ValueError as ve:
            raise ve
        except Exception:
            continue

    if content is None:
        raise ValueError(f"Không thể đọc mã hóa văn bản của file '{os.path.basename(file_path)}'!")

    content = content.strip()
    if not content:
        raise ValueError(f"File '{os.path.basename(file_path)}' bị rỗng (không có văn bản)!")

    return content
