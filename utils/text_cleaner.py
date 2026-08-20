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
    
    # Chuẩn hóa khoảng trắng trước/sau dấu câu: xóa khoảng trắng trước dấu, đảm bảo 1 khoảng trắng sau dấu (nếu không ở cuối câu/dòng hoặc dấu liên tiếp)
    text = re.sub(r"\s+([,.\!?;\:…])", r"\1", text)
    text = re.sub(r"([,.\!?;\:…])([^\s\d\"'\)\]\},.\!?;\:…])", r"\1 \2", text)
    
    return text.strip()

def split_into_sentences(text: str) -> list[str]:
    """
    Tách văn bản thành danh sách các câu đơn lẻ dựa trên dấu câu hoặc xuống dòng.
    - Giữ nguyên dấu câu đứng liền với câu đứng trước.
    - Tuyệt đối không tạo row riêng chỉ chứa dấu câu (., ?, !, ..., ?, v.v.) hoặc khoảng trắng.
    """
    text = clean_text(text)
    if not text:
        return []

    # Split by newline first
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sentences: list[str] = []

    for line in lines:
        # Regex matches sentence endings like . ! ? ... followed by space or end of string
        parts = re.split(r"(?<=[.!?…])\s+", line)
        for part in parts:
            part_str = part.strip()
            if not part_str:
                continue
            # If the part is purely punctuation / whitespace without letters or digits
            is_pure_punctuation = not any(c.isalnum() for c in part_str)
            if is_pure_punctuation:
                if sentences:
                    # Merge with preceding sentence
                    sentences[-1] = (sentences[-1] + " " + part_str).strip()
                else:
                    # If it's the very first part and has no prior sentence, drop or keep
                    continue
            else:
                sentences.append(part_str)
                
    return sentences



def split_text_preserving_content(text: str, min_chars: int = 200, max_chars: int = 500) -> list[dict]:
    """Split text into semantic chunks while preserving 100% of characters and whitespace."""
    if min_chars > max_chars:
        raise ValueError("min_chars không được lớn hơn max_chars")

    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        hard_end = min(start + max_chars, text_length)
        end = hard_end
        if hard_end < text_length:
            soft_start = min(start + min_chars, hard_end)
            for index in range(hard_end, soft_start - 1, -1):
                if text[index - 1] in ".!?;:\n":
                    end = index
                    break
            else:
                for index in range(hard_end, soft_start - 1, -1):
                    if text[index - 1].isspace():
                        end = index
                        break
        chunks.append({"index": len(chunks), "start": start, "end": end, "text": text[start:end]})
        start = end
    return chunks

