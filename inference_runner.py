"""Isolated inference runner for Chatterbox API with telemetry and benchmarking."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

# Force UTF-8 stdout/stderr encoding on Windows/all systems
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Set HF cache relative to project root
PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")

import torch
import torchaudio as ta

from services.inference import execute_model_inference, generate_with_model, load_model
from utils.platform_tools import clear_accelerator_cache, select_device


def report_progress(phase: str, percent: int, message: str) -> None:
    payload = json.dumps({"phase": phase, "percent": percent, "message": message})
    print(f"PROGRESS:{payload}", flush=True)


def run_batch_inference(config: dict) -> None:
    lines = config.get("lines", [])
    model_type = config.get("model", "nano")
    output_path = Path(config["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_dir = Path(config.get("chunks_dir", output_path.parent / "chunks"))
    chunks_dir.mkdir(parents=True, exist_ok=True)
    meta_path = Path(config["meta_path"]) if config.get("meta_path") else None

    device_pref = config.get("device", "auto")
    device = select_device(device_pref)

    cpu_threads = int(config.get("cpu_threads", 2))
    torch.set_num_threads(cpu_threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    t0_start = time.time()
    total_lines = len(lines)
    report_progress("loading_model", 5, f"Đang nạp mô hình {model_type.upper()} ({device.upper()}) một lần duy nhất...")

    # 1. LOAD MODEL ONCE FOR ENTIRE BATCH
    model, sr = load_model(model_type, device)
    report_progress("generating_tokens", 10, f"Mô hình {model_type.upper()} đã sẵn sàng ({total_lines} dòng). Bắt đầu sinh âm thanh...")

    lines_results = []
    successful_segments: list[tuple[Path, float, int]] = []
    stop_on_error = bool(config.get("stop_on_error", False))
    keep_original_timeline = bool(config.get("keep_original_timeline", False))
    default_pause_dur = float(config.get("pause_duration", 0.8))

    for i, line_item in enumerate(lines):
        line_idx = line_item.get("idx", i)
        line_text = line_item.get("text", "")
        line_out = chunks_dir / f"line_{line_idx:04d}.wav"
        line_pause = float(line_item.get("pause_duration", default_pause_dur))

        pct = 10 + int((i / max(1, total_lines)) * 75)
        report_progress("generating_tokens", pct, f"Đang xử lý dòng {i+1}/{total_lines}...")

        t0_line = time.time()
        try:
            wav = generate_with_model(model, model_type, line_item, device)
            t_infer = round(time.time() - t0_line, 3)

            ta.save(line_out, wav, sr)
            line_dur = round(wav.shape[-1] / sr, 3)
            successful_segments.append((line_out, line_pause, line_idx))

            line_res = {
                "idx": line_idx,
                "status": "completed",
                "audio_path": str(line_out),
                "duration_seconds": line_dur,
                "inference_seconds": t_infer,
                "text": line_text,
                "pause_duration": line_pause,
            }
            if "start_seconds" in line_item:
                line_res["original_start_seconds"] = line_item["start_seconds"]
            if "end_seconds" in line_item:
                line_res["original_end_seconds"] = line_item["end_seconds"]

            lines_results.append(line_res)

            line_progress_payload = json.dumps({
                "phase": "generating_tokens",
                "percent": pct,
                "line_idx": line_idx,
                "line_status": "completed",
                "line_duration": line_dur,
                "message": f"Hoàn tất dòng {i+1}/{total_lines}",
            })
            print(f"LINE_PROGRESS:{line_progress_payload}", flush=True)

        except Exception as exc:
            t_infer = round(time.time() - t0_line, 3)
            err_msg = str(exc)
            line_res = {
                "idx": line_idx,
                "status": "failed",
                "audio_path": None,
                "duration_seconds": 0.0,
                "inference_seconds": t_infer,
                "text": line_text,
                "pause_duration": line_pause,
                "error": err_msg,
            }
            if "start_seconds" in line_item:
                line_res["original_start_seconds"] = line_item["start_seconds"]
            if "end_seconds" in line_item:
                line_res["original_end_seconds"] = line_item["end_seconds"]

            lines_results.append(line_res)

            line_progress_payload = json.dumps({
                "phase": "generating_tokens",
                "percent": pct,
                "line_idx": line_idx,
                "line_status": "failed",
                "line_duration": 0.0,
                "error": err_msg,
                "message": f"Lỗi xử lý dòng {i+1}/{total_lines}: {err_msg}",
            })
            print(f"LINE_PROGRESS:{line_progress_payload}", flush=True)

            if stop_on_error:
                break

    # 2. OPTIONAL MERGE AT THE END
    should_merge = config.get("merge", True)
    normalize_loudness_flag = bool(config.get("normalize_loudness", True))
    crossfade_ms_val = int(config.get("crossfade_ms", 30))
    bgm_path = config.get("bgm_audio_path")
    bgm_vol = float(config.get("bgm_volume", 0.15))
    bgm_ducking_flag = bool(config.get("bgm_ducking", True))
    export_srt = config.get("export_srt", True)

    merged_duration = 0.0

    if should_merge and successful_segments:
        report_progress("merging_audio", 88, "Đang ghép nối toàn bộ đoạn thoại & hòa âm...")
        from services.audio import load_and_resample_audio, merge_speech_segments, mix_background_music
        tensors = []
        successful_pauses = []
        target_sr = 24000
        for p, p_pause, _ in successful_segments:
            w, _ = load_and_resample_audio(p, target_sr)
            if w is not None:
                tensors.append(w)
                successful_pauses.append(p_pause)

        if tensors:
            merged_speech = merge_speech_segments(
                tensors,
                pause_duration=default_pause_dur,
                pause_durations=successful_pauses,
                target_sr=target_sr,
                normalize=normalize_loudness_flag,
                crossfade_ms=crossfade_ms_val,
            )
            if bgm_path and Path(bgm_path).exists():
                merged_speech, _ = mix_background_music(
                    merged_speech,
                    bgm_path,
                    bgm_volume=bgm_vol,
                    target_sr=target_sr,
                    ducking=bgm_ducking_flag,
                )
            ta.save(output_path, merged_speech, target_sr)
            merged_duration = round(merged_speech.shape[-1] / target_sr, 3)

    # 3. GENERATE TIMELINES & SRT IF REQUESTED
    current_time = 0.0
    srt_lines = []
    slot_warnings = []

    def fmt_srt(t: float) -> str:
        t = max(0.0, t)
        hrs = int(t // 3600)
        mins = int((t % 3600) // 60)
        secs = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    for idx, item in enumerate(lines_results):
        if item.get("status") == "failed":
            item["start_seconds"] = 0.0
            item["end_seconds"] = 0.0
            continue

        p_len = item.get("pause_duration", default_pause_dur)

        if keep_original_timeline and "original_start_seconds" in item and "original_end_seconds" in item:
            # Strict original timeline: keep timestamps strictly as imported
            start_s = float(item["original_start_seconds"])
            end_s = float(item["original_end_seconds"])
            slot_dur = max(0.01, end_s - start_s)
            actual_dur = float(item["duration_seconds"])
            if actual_dur > slot_dur:
                slot_warnings.append(
                    f"Dòng {item['idx']+1}: Audio sinh ra ({actual_dur}s) dài hơn thời lượng timeline gốc ({slot_dur}s)"
                )
            item["start_seconds"] = round(start_s, 3)
            item["end_seconds"] = round(end_s, 3)
        else:
            start_s = current_time
            end_s = start_s + item["duration_seconds"]
            current_time = end_s + p_len

            item["start_seconds"] = round(start_s, 3)
            item["end_seconds"] = round(end_s, 3)

        if export_srt:
            srt_lines.append(f"{idx+1}\n{fmt_srt(start_s)} --> {fmt_srt(end_s)}\n{item['text']}\n")

    if export_srt and srt_lines:
        srt_content = "\n".join(srt_lines)
        srt_path = output_path.with_suffix(".srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

    total_time = round(time.time() - t0_start, 3)
    rtf = round(total_time / max(0.01, merged_duration), 3) if merged_duration > 0 else 0.0
    ftr = round(merged_duration / max(0.01, total_time), 2) if total_time > 0 else 0.0

    benchmark_data = {
        "device": device,
        "model_type": model_type,
        "total_lines": total_lines,
        "completed_lines": len([r for r in lines_results if r.get("status") == "completed"]),
        "failed_lines": len([r for r in lines_results if r.get("status") == "failed"]),
        "total_seconds": total_time,
        "audio_duration_seconds": merged_duration,
        "realtime_factor": rtf,
        "faster_than_realtime": ftr,
        "slot_warnings": slot_warnings,
        "lines_results": [
            {
                "idx": r["idx"],
                "status": r["status"],
                "duration_seconds": r["duration_seconds"],
                "inference_seconds": r.get("inference_seconds", 0.0),
                "start_seconds": r.get("start_seconds", 0.0),
                "end_seconds": r.get("end_seconds", 0.0),
                "text": r.get("text", ""),
                "error": r.get("error"),
            }
            for r in lines_results
        ],
    }

    print(f"BENCHMARK:{json.dumps(benchmark_data, ensure_ascii=False)}", flush=True)

    if meta_path:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_data, f, ensure_ascii=False, indent=2)

    has_failures = any(r.get("status") == "failed" for r in lines_results)
    completed_count = len(successful_segments)
    if has_failures and completed_count == 0:
        report_progress("failed", 100, "Toàn bộ các dòng trong kịch bản đều thất bại!")
    elif has_failures:
        report_progress("completed", 100, f"Hoàn tất sinh kịch bản ({completed_count}/{total_lines} dòng thành công, có lỗi ở một số dòng).")
    else:
        report_progress("completed", 100, "Hoàn tất sinh kịch bản hàng loạt thành công!")

    # Cleanup memory
    del model
    gc.collect()
    clear_accelerator_cache()



def run_inference(config: dict) -> None:
    job_type = config.get("type", "turbo")
    if job_type in ("batch", "long-text") or "lines" in config:
        run_batch_inference(config)
        return

    params = config.get("params", {})
    output_path = Path(config["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = Path(config["meta_path"]) if config.get("meta_path") else None

    device_pref = config.get("device", "auto")
    device = select_device(device_pref)

    cpu_threads = int(config.get("cpu_threads", 2))
    torch.set_num_threads(cpu_threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    # 1. Report loading
    report_progress("loading_model", 10, f"Đang nạp mô hình {job_type.upper()} ({device.upper()})...")
    t0_start = time.time()

    # 2. Execute inference using single canonical function
    report_progress("generating_tokens", 40, "Đang sinh chuỗi ngữ điệu & mã âm thanh (Tokens)...")
    t0_infer = time.time()
    wav, sr = execute_model_inference(job_type, params, device)
    infer_time = round(time.time() - t0_infer, 3)

    # 3. Postprocess & save audio
    report_progress("generating_audio", 85, "Đang xử lý hậu kỳ & giải mã sóng âm thanh (WAV)...")
    t0_save = time.time()
    ta.save(output_path, wav, sr)
    save_time = round(time.time() - t0_save, 3)

    audio_samples = wav.shape[-1]
    audio_duration = round(audio_samples / sr, 3)
    rtf = round(infer_time / max(0.01, audio_duration), 3)
    total_time = round(time.time() - t0_start, 3)

    benchmark_data = {
        "device": device,
        "model_type": job_type,
        "inference_seconds": infer_time,
        "save_seconds": save_time,
        "total_seconds": total_time,
        "audio_duration_seconds": audio_duration,
        "realtime_factor": rtf,
        "faster_than_realtime": round(audio_duration / max(0.01, infer_time), 2),
    }

    print(f"BENCHMARK:{json.dumps(benchmark_data, ensure_ascii=False)}", flush=True)

    if meta_path:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_data, f, ensure_ascii=False, indent=2)

    report_progress("completed", 100, "Hoàn tất sinh âm thanh thành công!")

    # Cleanup memory
    del wav
    gc.collect()
    clear_accelerator_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chatterbox Isolated Inference Worker")
    parser.add_argument("--config", required=True, help="JSON configuration string or path to JSON file")
    args = parser.parse_args()

    config_str = args.config.strip()
    config_path = Path(config_str)
    if config_str.startswith("{") and config_str.endswith("}"):
        config = json.loads(config_str)
    elif config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = json.loads(config_str)

    run_inference(config)


if __name__ == "__main__":
    main()
