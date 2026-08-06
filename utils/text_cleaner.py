"""
Utility module for text cleaning, normalization, and smart sentence chunking.
"""

import re

def clean_text(text: str) -> str:
    """
    Làm sạch và chuẩn hóa văn bản:
    - Xóa khoảng trắng thừa giữa các từ
    - Xóa nhiều dòng trống thừa
    - Chuẩn hóa khoảng trắng quanh các dấu câu (, . ! ? : ;)
    - Chuẩn hóa dấu ngoặc
    """
    if not text:
        return ""
    
    # Chuẩn hóa khoảng trắng đầu/cuối mỗi dòng
    lines = [line.strip() for line in text.splitlines()]
    # Loại bỏ dòng trống thừa quá 2 dòng liên tiếp
    cleaned_lines = []
    blank_count = 0
    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 1:
                cleaned_lines.append("")
        else:
            blank_count = 0
            cleaned_lines.append(line)
            
    text = "\n".join(cleaned_lines)
    
    # Thay thế nhiều khoảng trắng liền nhau bằng 1 khoảng trắng
    text = re.sub(r"[ \t]+", " ", text)
    
    # Chuẩn hóa khoảng trắng trước/sau dấu câu: xóa khoảng trắng trước dấu, đảm bảo 1 khoảng trắng sau dấu (nếu không ở cuối câu/dòng)
    text = re.sub(r"\s+([,.\!?;\:])", r"\1", text)
    text = re.sub(r"([,.\!?;\:])([^\s\d\"'\)\]\}])", r"\1 \2", text)
    
    return text.strip()

def split_into_sentences(text: str) -> list:
    """
    Tách văn bản thành danh sách các câu đơn lẻ dựa trên dấu câu hoặc xuống dòng.
    """
    text = clean_text(text)
    if not text:
        return []
    
    # Split by newline first, then by sentence ending punctuation
    raw_sentences = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        parts = re.split(r"(?<=[.!?])\s+", line)
        for p in parts:
            p_str = p.strip()
            if p_str:
                raw_sentences.append(p_str)
                
    return raw_sentences
