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

        # Batch resumption: reuse chunk only if it passes QC (auto-fixing if necessary)
        if config.get("resume", False) and line_out.exists() and line_out.stat().st_size > 44:
            try:
                from services.audio import load_and_resample_audio, evaluate_audio_signal, auto_fix_audio_signal
                w_resumed, load_err = load_and_resample_audio(line_out, sr)
                sr_resumed = sr
                if w_resumed is not None and load_err is None:
                    eval_resumed = evaluate_audio_signal(w_resumed, sr_resumed)
                    actions_resumed = []
                    if not eval_resumed["passed"] and eval_resumed.get("fixable"):
                        fixed_w, actions_resumed, final_eval_resumed = auto_fix_audio_signal(w_resumed, sr_resumed)
                        if final_eval_resumed["passed"]:
                            ta.save(line_out, fixed_w, sr_resumed)
                            w_resumed = fixed_w
                            eval_resumed = final_eval_resumed

                    if eval_resumed["passed"]:
                        line_dur = round(w_resumed.shape[-1] / sr_resumed, 3)
                        successful_segments.append((line_out, line_pause, line_idx))
                        line_res = {
                            "idx": line_idx,
                            "status": "completed",
                            "audio_path": str(line_out),
                            "duration_seconds": line_dur,
                            "inference_seconds": 0.0,
                            "text": line_text,
                            "pause_duration": line_pause,
                            "quality": {
                                "initial": eval_resumed,
                                "actions": actions_resumed,
                                "final": eval_resumed,
                            },
                        }
                        if "start_seconds" in line_item:
                            line_res["original_start_seconds"] = line_item["start_seconds"]
                        if "end_seconds" in line_item:
                            line_res["original_end_seconds"] = line_item["end_seconds"]
                        lines_results.append(line_res)
                        continue
            except Exception:
                pass

        t0_line = time.time()
        try:
            from services.audio import evaluate_audio_signal, auto_fix_audio_signal
            from services.critic import evaluate_speech_content
            from services.narration_planner import apply_pronunciation_dict

            narration_plan = line_item.get("narration_plan", {})
            pron_dict = narration_plan.get("pronunciation")
            raw_text = line_item.get("text", "")
            synth_text = apply_pronunciation_dict(raw_text, pron_dict) if pron_dict else raw_text

            item_to_infer = dict(line_item)
            item_to_infer["text"] = synth_text
            if model_type == "turbo":
                item_to_infer.pop("cfg_weight", None)
                item_to_infer.pop("exaggeration", None)
                item_to_infer.pop("min_p", None)

            candidate_strategy = narration_plan.get("candidate_strategy", "single")
            num_candidates = 2 if candidate_strategy == "multi_selective" else 1

            candidate_attempts: list[dict[str, Any]] = []
            best_candidate = None
            best_score = -1.0

            report_progress("evaluating", pct, f"Đang tổng hợp và đánh giá dòng {i+1}/{total_lines}...")

            for cand_idx in range(num_candidates):
                cand_seed = line_item.get("seed")
                cand_temp = line_item.get("temperature", 0.8)
                if cand_idx > 0:
                    cand_seed = ((cand_seed or 42) + 42 * cand_idx) % 1000000
                    cand_temp = max(0.4, cand_temp - 0.1)

                cand_item = dict(item_to_infer)
                cand_item["seed"] = cand_seed
                cand_item["temperature"] = cand_temp

                cand_wav = None
                cand_sr = sr
                cand_meta: dict[str, Any] = {}
                cand_passed = False

                for attempt in range(2):
                    if attempt > 0:
                        cand_item["seed"] = ((cand_item.get("seed") or 42) + attempt * 17) % 1000000
                        cand_item["temperature"] = max(0.3, cand_item.get("temperature", 0.8) - 0.15)

                    try:
                        wav = generate_with_model(model, model_type, cand_item, device)
                        cand_wav = wav

                        # 1. Signal QC
                        initial_eval = evaluate_audio_signal(wav, sr)
                        actions = []
                        final_eval = initial_eval
                        if not initial_eval["passed"] and initial_eval.get("fixable"):
                            report_progress("auto_fixing", pct, f"Đang tự động chuẩn hóa tín hiệu dòng {i+1}/{total_lines}...")
                            fixed_wav, actions, final_eval = auto_fix_audio_signal(wav, sr)
                            report_progress("re_evaluating", pct, f"Đang tái đánh giá tín hiệu dòng {i+1}/{total_lines}...")
                            cand_wav = fixed_wav
                            wav = fixed_wav

                        # 2. Content QC (ASR Speech Critic)
                        target_wpm = narration_plan.get("target_wpm")
                        content_eval = evaluate_speech_content(wav, sr, reference_text=raw_text, target_wpm=target_wpm)

                        signal_score = 100.0 if final_eval["passed"] else 30.0
                        content_score = content_eval.get("score", 100.0)
                        combined_score = round(content_score * 0.6 + signal_score * 0.4, 1)
                        is_passing = final_eval["passed"] and content_eval.get("passed", True)

                        cand_meta = {
                            "candidate_idx": cand_idx,
                            "attempt": attempt + 1,
                            "seed": cand_item.get("seed"),
                            "temperature": cand_item.get("temperature"),
                            "signal": {
                                "initial": initial_eval,
                                "actions": actions,
                                "final": final_eval,
                            },
                            "content": content_eval,
                            "score": combined_score,
                            "passed": is_passing,
                        }

                        if is_passing:
                            cand_passed = True
                            break
                    except Exception as e:
                        cand_meta = {
                            "candidate_idx": cand_idx,
                            "attempt": attempt + 1,
                            "error": str(e),
                            "passed": False,
                            "score": 0.0,
                        }

                candidate_attempts.append(cand_meta)

                if cand_wav is not None:
                    if cand_meta.get("score", 0) > best_score:
                        best_candidate = (cand_wav, cand_sr, cand_meta)
                        best_score = cand_meta.get("score", 0)

            if not best_candidate:
                raise RuntimeError("All candidate generations failed to synthesize audio")

            selected_wav, selected_sr, selected_meta = best_candidate
            for ca in candidate_attempts:
                ca["selected"] = (ca is selected_meta)

            if not selected_meta.get("passed", False):
                issues_list = []
                if selected_meta.get("signal", {}).get("final", {}).get("issues"):
                    issues_list.extend(selected_meta["signal"]["final"]["issues"])
                if selected_meta.get("content", {}).get("issues"):
                    issues_list.extend(selected_meta["content"]["issues"])
                err_issues = ", ".join(issues_list) or "Quality and content checks failed"
                raise RuntimeError(f"QC failed: {err_issues}")

            ta.save(line_out, selected_wav, selected_sr)
            line_dur = round(selected_wav.shape[-1] / selected_sr, 3)
            successful_segments.append((line_out, line_pause, line_idx))

            line_res = {
                "idx": line_idx,
                "status": "completed",
                "audio_path": str(line_out),
                "duration_seconds": line_dur,
                "inference_seconds": round(time.time() - t0_line, 3),
                "text": raw_text,
                "pause_duration": line_pause,
                "quality": selected_meta.get("signal", {}),
                "content_evaluation": selected_meta.get("content", {}),
                "attempts": candidate_attempts,
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
                "quality": {
                    "initial": {"passed": False, "issues": [err_msg]},
                    "actions": [],
                    "final": {"passed": False, "issues": [err_msg]},
                },
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
            report_progress("publishing", 95, "Đang lưu tệp âm thanh hoàn chỉnh...")
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

    # Calculate quality summary report
    total_segs = len(lines_results)
    passed_segs = sum(1 for r in lines_results if r.get("status") == "completed" and r.get("quality", {}).get("final", {}).get("passed", False))
    auto_fixed_segs = sum(1 for r in lines_results if len(r.get("quality", {}).get("actions", [])) > 0)
    failed_segs = sum(1 for r in lines_results if r.get("status") == "failed")
    all_warnings = list(slot_warnings)
    for r in lines_results:
        for w in r.get("quality", {}).get("final", {}).get("warnings", []):
            all_warnings.append(f"Dòng {r['idx']+1}: {w}")

    quality_report = {
        "passed": (failed_segs == 0 and passed_segs == total_segs and total_segs > 0),
        "total_segments": total_segs,
        "passed_segments": passed_segs,
        "auto_fixed_segments": auto_fixed_segs,
        "failed_segments": failed_segs,
        "warnings": all_warnings,
    }

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
        "quality_report": quality_report,
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
                "quality": r.get("quality", {}),
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
        report_progress("completed_partial", 100, f"Hoàn tất sinh kịch bản ({completed_count}/{total_lines} dòng thành công, có lỗi ở một số dòng).")
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
