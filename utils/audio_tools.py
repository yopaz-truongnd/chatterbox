"""
Audio processing tools: Speed change, Volume normalization, Format conversion (WAV, MP3, FLAC, OGG),
Subtitles generation (SRT/VTT), BGM mixing, Audio trimming, and Microphone recording.
"""

import os
import wave
import torch
import torchaudio as ta
import numpy as np
from utils.logger import logger

def format_timestamp_srt(seconds: float) -> str:
    """Format float seconds into SRT timestamp format HH:MM:SS,mmm"""
    millis = int((seconds % 1) * 1000)
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def format_timestamp_vtt(seconds: float) -> str:
    """Format float seconds into VTT timestamp format HH:MM:SS.mmm"""
    millis = int((seconds % 1) * 1000)
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def generate_srt(subtitles_data, output_file: str):
    """
    subtitles_data: list of dicts [{"start": float, "end": float, "text": str}]
    """
    lines = []
    for idx, sub in enumerate(subtitles_data, 1):
        start_str = format_timestamp_srt(sub["start"])
        end_str = format_timestamp_srt(sub["end"])
        lines.append(f"{idx}\n{start_str} --> {end_str}\n{sub['text']}\n")
    
    content = "\n".join(lines)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
    return output_file

def generate_vtt(subtitles_data, output_file: str):
    """
    subtitles_data: list of dicts [{"start": float, "end": float, "text": str}]
    """
    lines = ["WEBVTT\n"]
    for idx, sub in enumerate(subtitles_data, 1):
        start_str = format_timestamp_vtt(sub["start"])
        end_str = format_timestamp_vtt(sub["end"])
        lines.append(f"{idx}\n{start_str} --> {end_str}\n{sub['text']}\n")
    
    content = "\n".join(lines)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
    return output_file

def get_audio_duration(file_path: str) -> float:
    """Trả về độ dài file âm thanh tính bằng giây."""
    try:
        info = ta.info(file_path)
        return info.num_frames / info.sample_rate
    except Exception:
        try:
            with wave.open(file_path, "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except Exception as e:
            logger.error("Cannot get audio duration: %s", e)
            return 0.0

def trim_audio(input_file: str, output_file: str, start_sec: float, end_sec: float):
    """Cắt file âm thanh từ start_sec đến end_sec"""
    waveform, sr = ta.load(input_file)
    start_frame = int(start_sec * sr)
    end_frame = int(end_sec * sr)
    
    num_frames = waveform.size(-1)
    start_frame = max(0, min(start_frame, num_frames))
    end_frame = max(start_frame, min(end_frame, num_frames))
    
    trimmed_wave = waveform[:, start_frame:end_frame]
    ta.save(output_file, trimmed_wave, sr)
    return output_file

def change_audio_speed(input_file: str, output_file: str, speed_factor: float = 1.0):
    """Thay đổi tốc độ phát của file âm thanh (0.5x - 2.0x)"""
    if abs(speed_factor - 1.0) < 0.01:
        if input_file != output_file:
            import shutil
            shutil.copy2(input_file, output_file)
        return output_file

    waveform, sr = ta.load(input_file)
    # Resample trick or speed modify using torchaudio resample
    new_sr = int(sr * speed_factor)
    resampled = ta.functional.resample(waveform, orig_freq=sr, new_freq=new_sr)
    ta.save(output_file, resampled, sr)
    return output_file

def normalize_audio(input_file: str, output_file: str, target_db: float = -1.0):
    """Chuẩn hóa âm lượng Peak Normalization"""
    waveform, sr = ta.load(input_file)
    max_val = torch.max(torch.abs(waveform))
    if max_val > 0:
        target_amplitude = 10 ** (target_db / 20.0)
        scale = target_amplitude / max_val
        waveform = waveform * scale
    ta.save(output_file, waveform, sr)
    return output_file

def convert_audio_format(input_file: str, output_file: str, fmt: str = "WAV"):
    """
    Chuyển đổi file âm thanh sang WAV, MP3, FLAC, OGG
    """
    fmt = fmt.upper()
    waveform, sr = ta.load(input_file)
    
    if fmt == "WAV":
        ta.save(output_file, waveform, sr, format="wav")
    elif fmt == "FLAC":
        ta.save(output_file, waveform, sr, format="flac")
    elif fmt in ["MP3", "OGG"]:
        try:
            ta.save(output_file, waveform, sr, format=fmt.lower())
        except Exception:
            # Fallback format save or keep wav extension if backend unsupported
            ta.save(output_file, waveform, sr)
    else:
        ta.save(output_file, waveform, sr)
    return output_file

def mix_bgm(speech_file: str, bgm_file: str, output_file: str, bgm_volume: float = 0.2):
    """
    Hòa trộn file âm thanh nói (speech_file) với file nhạc nền (bgm_file)
    bgm_volume: 0.0 đến 1.0 (ví dụ 0.2 = 20% âm lượng nhạc nền)
    """
    if not bgm_file or not os.path.exists(bgm_file):
        import shutil
        shutil.copy2(speech_file, output_file)
        return output_file

    speech_wave, sr = ta.load(speech_file)
    bgm_wave, bgm_sr = ta.load(bgm_file)

    # Resample BGM to speech SR if needed
    if bgm_sr != sr:
        bgm_wave = ta.functional.resample(bgm_wave, orig_freq=bgm_sr, new_freq=sr)

    # Ensure stereo/mono channel match
    if speech_wave.size(0) == 1 and bgm_wave.size(0) > 1:
        bgm_wave = bgm_wave.mean(dim=0, keepdim=True)
    elif speech_wave.size(0) > 1 and bgm_wave.size(0) == 1:
        bgm_wave = bgm_wave.repeat(speech_wave.size(0), 1)

    speech_len = speech_wave.size(-1)
    bgm_len = bgm_wave.size(-1)

    # Loop BGM if shorter than speech, or crop if longer
    if bgm_len < speech_len:
        repeats = (speech_len // bgm_len) + 1
        bgm_wave = bgm_wave.repeat(1, repeats)[:, :speech_len]
    else:
        bgm_wave = bgm_wave[:, :speech_len]

    # Apply volume scaling
    mixed = speech_wave + (bgm_wave * bgm_volume)
    
    # Avoid clipping
    max_val = torch.max(torch.abs(mixed))
    if max_val > 1.0:
        mixed = mixed / max_val

    ta.save(output_file, mixed, sr)
    return output_file


def create_temp_audio_file(suffix: str = ".wav", directory=None) -> str:
    """Safely create a unique temporary audio file path without race conditions."""
    import tempfile
    dir_str = str(directory) if directory else None
    if dir_str:
        os.makedirs(dir_str, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=dir_str)
    os.close(fd)
    return path
