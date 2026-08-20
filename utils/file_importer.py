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


def parse_timestamp_to_seconds(ts_str: str) -> float:
    """Chuyển đổi chuỗi thời gian HH:MM:SS,mmm hoặc HH:MM:SS.mmm hoặc SS.mmm sang số giây (float)."""
    ts_str = ts_str.strip().replace(",", ".")
    parts = ts_str.split(":")
    if len(parts) == 3:
        try:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        except ValueError:
            return 0.0
    elif len(parts) == 2:
        try:
            m, s = float(parts[0]), float(parts[1])
            return m * 60 + s
        except ValueError:
            return 0.0
    elif len(parts) == 1:
        try:
            return float(parts[0])
        except ValueError:
            return 0.0
    return 0.0


def parse_srt_or_vtt(content: str) -> list[dict]:
    """
    Phân tích file phụ đề SRT hoặc WebVTT:
    - Loại bỏ số thứ tự cue và thẻ HTML (<i>, <b>, <font>, ...)
    - Giữ lại nội dung đối thoại và tính toán timeline start/end (giây).
    """
    if not content:
        return []

    # Clean WebVTT header
    lines = content.splitlines()
    cleaned_blocks = []
    current_block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_block:
                cleaned_blocks.append(current_block)
                current_block = []
            continue
        if stripped.startswith("WEBVTT") or stripped.startswith("NOTE"):
            continue
        current_block.append(stripped)

    if current_block:
        cleaned_blocks.append(current_block)

    results = []
    for block in cleaned_blocks:
        time_line_idx = -1
        start_s = 0.0
        end_s = 0.0

        for idx, line in enumerate(block):
            if "-->" in line:
                time_line_idx = idx
                time_parts = line.split("-->")
                if len(time_parts) == 2:
                    # Clean any trailing cue settings in VTT
                    raw_start = time_parts[0].strip()
                    raw_end = time_parts[1].strip().split()[0]
                    start_s = parse_timestamp_to_seconds(raw_start)
                    end_s = parse_timestamp_to_seconds(raw_end)
                break

        # Dialogue lines come after the timestamp line
        if time_line_idx != -1:
            text_lines = block[time_line_idx + 1:]
        else:
            # If no timestamp found, skip pure number line if present
            text_lines = [l for l in block if not l.isdigit()]

        raw_text = " ".join(text_lines)
        # Strip HTML tags
        clean_text = re.sub(r"</?[^>]+(>|$)", "", raw_text).strip()
        if clean_text:
            results.append({
                "text": clean_text,
                "start_seconds": round(start_s, 3),
                "end_seconds": round(end_s, 3),
                "duration_seconds": round(max(0.0, end_s - start_s), 3),
            })

    return results


def parse_csv_script(content: str) -> list[dict]:
    """
    Phân tích kịch bản từ file CSV:
    Hỗ trợ các cột: speaker, text, start, end, voice, pause
    Hoặc các dòng CSV tự do (speaker, text).
    """
    import csv
    import io

    if not content:
        return []

    f = io.StringIO(content.strip())
    reader = csv.reader(f)
    rows = [r for r in reader if any(field.strip() for field in r)]

    if not rows:
        return []

    # Check header
    header = [col.lower().strip() for col in rows[0]]
    has_header = any(key in header for key in ("speaker", "text", "dialogue", "voice", "content", "nhan_vat", "thoai"))

    speaker_idx = -1
    text_idx = -1
    voice_idx = -1
    start_idx = -1
    end_idx = -1
    pause_idx = -1

    data_rows = rows
    if has_header:
        data_rows = rows[1:]
        for idx, col in enumerate(header):
            if col in ("speaker", "nhan_vat", "character", "actor", "nguoi_noi"):
                speaker_idx = idx
            elif col in ("text", "dialogue", "thoai", "noi_dung", "content", "sentence"):
                text_idx = idx
            elif col in ("voice", "giong", "voice_id", "character_id"):
                voice_idx = idx
            elif col in ("start", "bat_dau"):
                start_idx = idx
            elif col in ("end", "ket_thuc"):
                end_idx = idx
            elif col in ("pause", "khoang_lang", "pause_duration"):
                pause_idx = idx

    results = []
    for r in data_rows:
        if not r:
            continue
        speaker = ""
        text = ""
        voice = ""
        start = None
        end = None
        pause = None

        if has_header:
            if text_idx != -1 and text_idx < len(r):
                text = r[text_idx].strip()
            if speaker_idx != -1 and speaker_idx < len(r):
                speaker = r[speaker_idx].strip()
            if voice_idx != -1 and voice_idx < len(r):
                voice = r[voice_idx].strip()
            if start_idx != -1 and start_idx < len(r):
                try: start = float(r[start_idx])
                except ValueError: pass
            if end_idx != -1 and end_idx < len(r):
                try: end = float(r[end_idx])
                except ValueError: pass
            if pause_idx != -1 and pause_idx < len(r):
                try: pause = float(r[pause_idx])
                except ValueError: pass
        else:
            # Heuristic for non-header CSV
            if len(r) >= 2:
                # If first column is short (< 30 chars), treat as speaker
                if len(r[0].strip()) < 30 and not r[0].strip().endswith((".", "!", "?")):
                    speaker = r[0].strip()
                    text = r[1].strip()
                else:
                    text = r[0].strip()
                    voice = r[1].strip()
            else:
                text = r[0].strip()

        if text:
            item = {"text": text}
            if speaker: item["speaker"] = speaker
            if voice: item["voice"] = voice
            if start is not None: item["start_seconds"] = start
            if end is not None: item["end_seconds"] = end
            if pause is not None: item["pause_duration"] = pause
            results.append(item)

    return results


def parse_markdown_script(content: str, use_headings_as_chapters: bool = True) -> list[dict]:
    """
    Phân tích nội dung Markdown:
    - Loại bỏ code block, url link, hình ảnh và định dạng thừa.
    - Giữ heading làm tiêu đề phân đoạn hoặc tên chương nếu được yêu cầu.
    """
    if not content:
        return []

    # 1. Remove code blocks ``` ... ```
    cleaned = re.sub(r"```[\s\S]*?```", "", content)
    # 2. Remove inline code `...`
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    # 3. Remove images ![alt](url)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cleaned)
    # 4. Convert links [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)

    lines = cleaned.splitlines()
    results = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check heading
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            heading_text = heading_match.group(2).strip()
            if use_headings_as_chapters and heading_text:
                results.append({"text": heading_text, "is_chapter": True, "speaker": "Narrator"})
            continue

        # Remove list markers
        clean_line = re.sub(r"^[-*+]\s+", "", stripped)
        clean_line = re.sub(r"^\d+\.\s+", "", clean_line)
        clean_line = re.sub(r"^>\s+", "", clean_line)
        # Remove bold / italic
        clean_line = re.sub(r"[*_~]{1,3}", "", clean_line).strip()

        if clean_line:
            results.append({"text": clean_line})

    return results


def parse_multicharacter_script(content: str) -> list[dict]:
    """
    Nhận dạng kịch bản đa nhân vật dạng:
    [Narrator]: Ngày xửa ngày xưa...
    [Sarah]: Xin chào mọi người.
    John: Chúng ta bắt đầu nhé.
    Mary (vui vẻ): Rất vui được gặp bạn!
    """
    if not content:
        return []

    dialogue_pattern = re.compile(
        r"^(?:\[(?P<bracket_speaker>[^\]]+)\]|(?P<raw_speaker>[A-Za-z0-9_\u00C0-\u1EF9\s\.\-]+?))\s*(?:\((?P<emotion>[^)]*)\))?\s*[:：]\s*(?P<dialogue>.*)$"
    )

    lines = content.splitlines()
    results = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        match = dialogue_pattern.match(stripped)
        if match:
            speaker = (match.group("bracket_speaker") or match.group("raw_speaker") or "").strip()
            emotion = (match.group("emotion") or "").strip()
            dialogue = (match.group("dialogue") or "").strip()

            # Handle emotion inside bracket e.g. [Sarah (vui vẻ)]
            if "(" in speaker and ")" in speaker and not emotion:
                sub_m = re.match(r"^([^()]+)\s*\(([^()]+)\)$", speaker)
                if sub_m:
                    speaker = sub_m.group(1).strip()
                    emotion = sub_m.group(2).strip()

            # Discard false positives like URL http:// or timestamp 00:01:
            if speaker.lower() in ("http", "https") or (len(speaker) <= 2 and speaker.isdigit()):
                results.append({"text": stripped})
            elif dialogue:
                results.append({
                    "speaker": speaker,
                    "text": dialogue,
                    "emotion": emotion if emotion else None,
                })
            else:
                results.append({"text": stripped})
        else:
            results.append({"text": stripped})

    return results
