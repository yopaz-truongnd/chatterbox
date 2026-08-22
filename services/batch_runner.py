"""
Batch Runner Service - Orchestrates execution of batch and long-text jobs.
Saves job manager code length and resolves responsibilities cleanly.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from job_store import AudioJob
from services.audio import load_and_resample_audio, merge_speech_segments, mix_background_music, save_audio_wav
from services.inference import run_isolated_subprocess

logger = logging.getLogger("chatterbox.batch_runner")


class BatchRunner:
    def __init__(self, job_manager):
        self.jm = job_manager

    def run_batch_job(self, job: AudioJob, output_path: Path, in_process: bool) -> tuple[bool, str | None]:
        """Execute all lines in a batch or long-text job loading the model ONCE."""
        params = job.params
        sub_model = params.get("model", "nano")
        pause_duration = float(params.get("pause_duration", 0.8))
        bgm_path = params.get("bgm_audio_path")
        bgm_vol = float(params.get("bgm_volume", 0.15))
        export_srt = bool(params.get("export_srt", True))
        chunks_dir = self.jm.data_dir / "chunks" / job.id
        chunks_dir.mkdir(parents=True, exist_ok=True)

        if job.type == "long-text":
            from utils.text_cleaner import split_text_preserving_content
            text = params.get("text", "")
            min_chars = int(params.get("min_chars", 200))
            max_chars = int(params.get("max_chars", 500))
            raw_chunks = split_text_preserving_content(text, min_chars, max_chars)
            lines = [{"idx": i, "text": c["text"], **params} for i, c in enumerate(raw_chunks)]
        else:
            lines = params.get("lines", [])

        total_lines = len(lines)
        if total_lines == 0:
            return False, "Kịch bản rỗng sau khi xử lý (0 dòng)"

        pause_durations_list = [float(item.get("pause_duration", pause_duration)) for item in lines]
        normalize_loudness_flag = bool(params.get("normalize_loudness", True))
        crossfade_ms_val = int(params.get("crossfade_ms", 30))
        bgm_ducking_flag = bool(params.get("bgm_ducking", True))
        stop_on_error = bool(params.get("stop_on_error", False))
        keep_original_timeline = bool(params.get("keep_original_timeline", False))

        batch_params = {
            **params,
            "lines": lines,
            "model": sub_model,
            "chunks_dir": str(chunks_dir),
            "merge": True,
            "pause_duration": pause_duration,
            "pause_durations": pause_durations_list,
            "bgm_audio_path": bgm_path,
            "bgm_volume": bgm_vol,
            "export_srt": export_srt,
            "normalize_loudness": normalize_loudness_flag,
            "crossfade_ms": crossfade_ms_val,
            "bgm_ducking": bgm_ducking_flag,
            "stop_on_error": stop_on_error,
            "keep_original_timeline": keep_original_timeline,
        }

        if in_process:
            successful_segments: list[tuple[Path, float, int]] = []
            lines_results = []
            t0_start = time.time()

            from services.audio import evaluate_audio_signal, auto_fix_audio_signal

            for i, line_item in enumerate(lines):
                line_idx = line_item.get("idx", i)
                line_out = chunks_dir / f"line_{line_idx:04d}.wav"
                line_pause = float(line_item.get("pause_duration", pause_duration))

                pct = 10 + int((i / max(1, total_lines)) * 75)
                self.jm._update_job_status(job.id, phase="generating_tokens", progress_percent=pct)

                # Batch resumption: reuse chunk only if it passes QC (auto-fixing if necessary)
                if (params.get("resume", False) or job.params.get("resume", False)) and line_out.exists() and line_out.stat().st_size > 44:
                    try:
                        w_resumed, load_err = load_and_resample_audio(line_out, 24000)
                        sr_resumed = 24000
                        if w_resumed is not None and load_err is None:
                            eval_resumed = evaluate_audio_signal(w_resumed, sr_resumed)
                            actions_resumed = []
                            if not eval_resumed["passed"] and eval_resumed.get("fixable"):
                                fixed_w, actions_resumed, final_eval_resumed = auto_fix_audio_signal(w_resumed, sr_resumed)
                                if final_eval_resumed["passed"]:
                                    save_audio_wav(line_out, fixed_w, sr_resumed)
                                    w_resumed = fixed_w
                                    eval_resumed = final_eval_resumed

                            if eval_resumed["passed"]:
                                dur = round(w_resumed.shape[-1] / sr_resumed, 3)
                                successful_segments.append((line_out, line_pause, line_idx))
                                lines_results.append({
                                    "idx": line_idx,
                                    "status": "completed",
                                    "audio_path": str(line_out),
                                    "duration_seconds": dur,
                                    "inference_seconds": 0.0,
                                    "text": line_item.get("text", ""),
                                    "pause_duration": line_pause,
                                    "quality": {
                                        "initial": eval_resumed,
                                        "actions": actions_resumed,
                                        "final": eval_resumed,
                                    },
                                    "original_start_seconds": line_item.get("start_seconds"),
                                    "original_end_seconds": line_item.get("end_seconds"),
                                })
                                continue
                    except Exception:
                        pass

                t0_line = time.time()
                try:
                    from services.critic import evaluate_speech_content
                    from services.narration_planner import apply_pronunciation_dict
                    import services.job_manager

                    narration_plan = line_item.get("narration_plan", {})
                    pron_dict = narration_plan.get("pronunciation")
                    raw_text = line_item.get("text", "")
                    synth_text = apply_pronunciation_dict(raw_text, pron_dict) if pron_dict else raw_text

                    # Model-aware parameter handling (strip Turbo incompatible params)
                    item_to_infer = dict(line_item)
                    item_to_infer["text"] = synth_text
                    if sub_model == "turbo":
                        item_to_infer.pop("cfg_weight", None)
                        item_to_infer.pop("exaggeration", None)
                        item_to_infer.pop("min_p", None)

                    candidate_strategy = narration_plan.get("candidate_strategy", "single")
                    num_candidates = 2 if candidate_strategy == "multi_selective" else 1

                    candidate_attempts: list[dict[str, Any]] = []
                    best_candidate = None
                    best_score = -1.0

                    self.jm._update_job_status(job.id, phase="evaluating", progress_percent=pct)

                    for cand_idx in range(num_candidates):
                        cand_seed = line_item.get("seed")
                        cand_temp = line_item.get("temperature", 0.8)
                        if cand_idx > 0:
                            cand_seed = ((cand_seed or 42) + 42 * cand_idx) % 1000000
                            cand_temp = max(0.4, cand_temp - 0.1)

                        cand_item = dict(item_to_infer)
                        cand_item["seed"] = cand_seed
                        cand_item["temperature"] = cand_temp

                        # Adaptive retry (up to 2 tries per candidate if failure occurs)
                        cand_wav = None
                        cand_sr = 24000
                        cand_meta: dict[str, Any] = {}
                        cand_passed = False

                        for attempt in range(2):
                            if attempt > 0:
                                cand_item["seed"] = ((cand_item.get("seed") or 42) + attempt * 17) % 1000000
                                cand_item["temperature"] = max(0.3, cand_item.get("temperature", 0.8) - 0.15)

                            try:
                                wav, sr = services.job_manager.execute_model_inference(sub_model, cand_item, self.jm.device)
                                cand_wav = wav
                                cand_sr = sr

                                # 1. Signal QC
                                init_eval = evaluate_audio_signal(wav, sr)
                                actions = []
                                final_eval = init_eval
                                if not init_eval["passed"] and init_eval.get("fixable"):
                                    self.jm._update_job_status(job.id, phase="auto_fixing", progress_percent=pct)
                                    fixed_w, actions, final_eval = auto_fix_audio_signal(wav, sr)
                                    self.jm._update_job_status(job.id, phase="re_evaluating", progress_percent=pct)
                                    cand_wav = fixed_w
                                    wav = fixed_w

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
                                        "initial": init_eval,
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

                    save_audio_wav(line_out, selected_wav, selected_sr)
                    dur = round(selected_wav.shape[-1] / selected_sr, 3)
                    successful_segments.append((line_out, line_pause, line_idx))
                    lines_results.append({
                        "idx": line_idx,
                        "status": "completed",
                        "audio_path": str(line_out),
                        "duration_seconds": dur,
                        "inference_seconds": round(time.time() - t0_line, 3),
                        "text": raw_text,
                        "pause_duration": line_pause,
                        "quality": selected_meta.get("signal", {}),
                        "content_evaluation": selected_meta.get("content", {}),
                        "attempts": candidate_attempts,
                        "original_start_seconds": line_item.get("start_seconds"),
                        "original_end_seconds": line_item.get("end_seconds"),
                    })
                except Exception as exc:
                    lines_results.append({
                        "idx": line_idx,
                        "status": "failed",
                        "audio_path": None,
                        "duration_seconds": 0.0,
                        "inference_seconds": round(time.time() - t0_line, 3),
                        "text": line_item.get("text", ""),
                        "pause_duration": line_pause,
                        "error": str(exc),
                        "quality": {
                            "initial": {"passed": False, "issues": [str(exc)]},
                            "actions": [],
                            "final": {"passed": False, "issues": [str(exc)]},
                        },
                        "attempts": candidate_attempts if 'candidate_attempts' in locals() else [],
                        "original_start_seconds": line_item.get("start_seconds"),
                        "original_end_seconds": line_item.get("end_seconds"),
                    })
                    if stop_on_error:
                        break

            total_dur = 0.0
            if successful_segments:
                self.jm._update_job_status(job.id, phase="merging_audio", progress_percent=88)
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
                        pause_duration=pause_duration,
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

                    self.jm._update_job_status(job.id, phase="publishing", progress_percent=95)
                    save_audio_wav(output_path, merged_speech, target_sr)
                    total_dur = round(merged_speech.shape[-1] / target_sr, 3)

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

                p_len = item.get("pause_duration", pause_duration)

                if keep_original_timeline and item.get("original_start_seconds") is not None and item.get("original_end_seconds") is not None:
                    # Strict original timeline
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
                with open(output_path.with_suffix(".srt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(srt_lines))

            total_time = round(time.time() - t0_start, 3)
            rtf = round(total_time / max(0.01, total_dur), 3) if total_dur > 0 else 0.0
            ftr = round(total_dur / max(0.01, total_time), 2) if total_time > 0 else 0.0

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
                "device": self.jm.device,
                "model_type": sub_model,
                "total_lines": total_lines,
                "completed_lines": len([r for r in lines_results if r.get("status") == "completed"]),
                "failed_lines": len([r for r in lines_results if r.get("status") == "failed"]),
                "total_seconds": total_time,
                "audio_duration_seconds": total_dur,
                "realtime_factor": rtf,
                "faster_than_realtime": ftr,
                "slot_warnings": slot_warnings,
                "quality_report": quality_report,
                "lines_results": lines_results,
            }
            has_failures = any(r.get("status") == "failed" for r in lines_results)
            if has_failures and len(successful_segments) == 0:
                self.jm._update_job_status(
                    job.id,
                    benchmark=benchmark_data,
                    duration_seconds=0.0,
                    progress_percent=100,
                    phase="failed",
                    status="failed",
                    error="Toàn bộ các dòng trong kịch bản đều thất bại",
                )
                return False, "Toàn bộ các dòng trong kịch bản đều thất bại"

            final_job_status = "completed_partial" if has_failures else "completed"
            self.jm._update_job_status(
                job.id,
                status=final_job_status,
                phase="completed",
                benchmark=benchmark_data,
                duration_seconds=total_dur,
                progress_percent=100,
                output_path=str(output_path) if output_path.exists() else None,
            )
            return True, None

        else:
            ok, err, bm = run_isolated_subprocess(
                job_id=job.id,
                job_type="batch",
                params=batch_params,
                output_path=output_path,
                device=self.jm.device,
                cpu_threads=self.jm.cpu_threads,
                project_dir=self.jm.project_dir,
                data_dir=self.jm.data_dir,
                timeout_seconds=self.jm.timeout_seconds,
                progress_callback=lambda ph, pct, msg: self.jm._update_job_status(job.id, phase=ph, progress_percent=pct),
                line_progress_callback=lambda lp: self.jm._handle_line_progress(job.id, lp),
                benchmark_callback=lambda bm_data: self.jm._update_job_status(job.id, benchmark=bm_data, duration_seconds=bm_data.get("audio_duration_seconds")),
                register_proc_callback=self.jm._register_proc,
                unregister_proc_callback=self.jm._unregister_proc,
            )
            return ok, err
