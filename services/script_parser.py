"""Script Parsing Service for Batch and Dialogue Processing.

Supports TXT, CSV, Markdown dialogue formats, SRT, VTT subtitles, and custom delimiter/regex rules.
"""

from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("chatterbox.script_parser")


def split_script_text(
    text_content: str,
    split_mode: str = "auto",
    custom_delimiter: str = "",
) -> list[str]:
    """Split raw text content according to chosen split_mode."""
    if not text_content:
        return []

    # 1. Custom Delimiter Mode
    if split_mode == "delimiter" and custom_delimiter:
        raw_chunks = text_content.split(custom_delimiter)
        return [c.strip() for c in raw_chunks if c.strip()]

    # 2. Sentence Splitting Mode (. ! ? \n)
    if split_mode == "sentence":
        sentences = re.split(r"(?<=[.!?\n])\s+", text_content.strip())
        return [s.strip() for s in sentences if s.strip()]

    # 3. Paragraph Splitting Mode (\n\n)
    if split_mode == "paragraph":
        paragraphs = re.split(r"\n\s*\n", text_content.strip())
        return [p.strip() for p in paragraphs if p.strip()]

    # 4. Regular Expression Mode
    if split_mode == "regex" and custom_delimiter:
        try:
            raw_chunks = re.split(custom_delimiter, text_content)
            return [c.strip() for c in raw_chunks if c.strip()]
        except Exception as e:
            logger.warning("Invalid regex delimiter: %s", e)

    # 5. Default Line Splitting
    return [l.strip() for l in text_content.splitlines() if l.strip()]


def parse_srt_script(content: str) -> list[dict[str, Any]]:
    """Parse SRT subtitle text into structured dialogue items."""
    pattern = re.compile(
        r"(\d+)\s*\n"
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n"
        r"([\s\S]*?)(?=\n\s*\n\d+|\Z)",
        re.MULTILINE,
    )
    items = []
    for match in pattern.finditer(content):
        idx_str, start_ts, end_ts, text = match.groups()
        clean_text = re.sub(r"<[^>]+>", "", text).strip()
        clean_text = " ".join(clean_text.splitlines())
        if clean_text:
            items.append({
                "idx": int(idx_str) - 1,
                "start_timestamp": start_ts.replace(".", ","),
                "end_timestamp": end_ts.replace(".", ","),
                "text": clean_text,
            })
    return items


def parse_vtt_script(content: str) -> list[dict[str, Any]]:
    """Parse WebVTT subtitle text into structured dialogue items."""
    pattern = re.compile(
        r"(?:^\s*\d+\s*\n)?"
        r"((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})[^\n]*\n"
        r"([\s\S]*?)(?=\n\s*(?:(?:\d+\s*\n)?(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3}\s*-->|\Z))",
        re.MULTILINE,
    )
    items = []
    idx = 0
    for match in pattern.finditer(content):
        start_ts, end_ts, text = match.groups()
        clean_text = re.sub(r"<[^>]+>", "", text).strip()
        clean_text = " ".join(clean_text.splitlines())
        if clean_text:
            items.append({
                "idx": idx,
                "start_timestamp": start_ts,
                "end_timestamp": end_ts,
                "text": clean_text,
            })
            idx += 1
    return items


def parse_csv_script(content: str) -> list[str]:
    """Parse CSV text with smart delimiter detection and text column extraction."""
    lines = [l for l in content.splitlines() if l.strip()]
    if not lines:
        return []

    sample = "\n".join(lines[:5])
    delimiter = ","
    if ";" in sample and sample.count(";") > sample.count(","):
        delimiter = ";"
    elif "\t" in sample and sample.count("\t") > sample.count(","):
        delimiter = "\t"

    reader = csv.reader(lines, delimiter=delimiter)
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        return []

    num_cols = max(len(r) for r in rows)
    if num_cols == 1:
        extracted = [r[0].strip() for r in rows if r and r[0].strip()]
        if extracted and extracted[0].lower() in ["text", "content", "nội dung", "văn bản", "sentence", "prompt", "line", "id"]:
            extracted = extracted[1:]
        return extracted

    header = [c.strip().lower() for c in rows[0]]
    text_col_idx = -1

    for idx, col_name in enumerate(header):
        if any(k in col_name for k in ["text", "content", "nội dung", "văn bản", "sentence", "prompt", "line", "speech"]):
            text_col_idx = idx
            break

    has_header = (text_col_idx != -1) or any(not c.replace(".", "").isdigit() for c in header)
    data_rows = rows[1:] if has_header else rows

    if text_col_idx == -1 and data_rows:
        col_avg_lens = []
        for col_idx in range(num_cols):
            lens = [len(r[col_idx]) for r in data_rows if col_idx < len(r)]
            avg_len = sum(lens) / len(lens) if lens else 0
            col_avg_lens.append((avg_len, col_idx))
        col_avg_lens.sort(reverse=True)
        text_col_idx = col_avg_lens[0][1]

    extracted = []
    for r in data_rows:
        if text_col_idx < len(r):
            val = r[text_col_idx].strip()
            if val:
                extracted.append(val)
    return extracted


def parse_batch_file(
    file_path: str | Path,
    split_mode: str = "auto",
    custom_delimiter: str = "",
) -> list[str]:
    """Read file with auto-encoding detection and extract lines/chunks."""
    path_str = str(file_path)
    text_content = ""
    for enc in ["utf-8-sig", "utf-8", "utf-16", "latin-1", "cp1252"]:
        try:
            with open(path_str, "r", encoding=enc, errors="replace") as f:
                text_content = f.read()
            if text_content:
                break
        except Exception:
            continue

    if not text_content:
        return []

    # Format specific handling
    lower_path = path_str.lower()
    if lower_path.endswith(".csv"):
        try:
            return parse_csv_script(text_content)
        except Exception as e:
            logger.warning("CSV parsing fallback: %s", e)
            return [l.strip() for l in text_content.splitlines() if l.strip()]

    if lower_path.endswith(".srt"):
        srt_items = parse_srt_script(text_content)
        return [item["text"] for item in srt_items]

    if lower_path.endswith(".vtt"):
        vtt_items = parse_vtt_script(text_content)
        return [item["text"] for item in vtt_items]

    return split_script_text(text_content, split_mode=split_mode, custom_delimiter=custom_delimiter)
