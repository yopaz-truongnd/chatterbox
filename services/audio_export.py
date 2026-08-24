"""Audio Export & Deliverables Packaging Domain Service (Phase 14).

Handles final packaging of mastered audio into requested distribution formats
(FINAL.wav, FINAL.mp3) with metadata, strict capability checks, and SHA-256 verification.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import uuid
import wave

from services.audio_mix_models import (
    ExportManifest,
    ExportProfile,
    MixArtifact,
    get_wav_duration_ms,
)
from services.tts.base import CancellationToken, ProgressCallback
from services.voice_project_models import (
    ExportDependencyUnavailableError,
    compute_file_sha256,
)

logger = logging.getLogger(__name__)


def _probe_audio_metadata(file_path: Path, fallback_sr: int = 44100, fallback_ch: int = 1, fallback_dur_ms: float = 0.0) -> tuple[int, int, float]:
    """Probe actual sample rate, channels, and duration_ms using wave or ffprobe."""
    if file_path.suffix.lower() == ".wav" and file_path.exists():
        try:
            with wave.open(str(file_path), "rb") as wf:
                ch = wf.getnchannels()
                sr = wf.getframerate()
                dur_ms = (wf.getnframes() / float(sr)) * 1000.0 if sr > 0 else 0.0
                return sr, ch, dur_ms
        except Exception as exc:
            logger.warning("Failed to inspect WAV header for '%s': %s", file_path, exc)

    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin and file_path.exists():
        try:
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-show_entries", "stream=sample_rate,channels,duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 3:
                sr = int(lines[0])
                ch = int(lines[1])
                dur_ms = float(lines[2]) * 1000.0
                return sr, ch, dur_ms
        except Exception:
            pass

    return fallback_sr, fallback_ch, fallback_dur_ms


def _run_ffmpeg_encode(
    cmd: list[str],
    temp_file: Path,
    cancellation_token: CancellationToken | None = None,
    timeout_s: float = 60.0,
) -> None:
    """Execute FFmpeg encoding subprocess with polling, cancellation check, and timeout."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start_t = time.time()

    while True:
        ret = proc.poll()
        if ret is not None:
            if ret != 0:
                _, stderr = proc.communicate()
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass
                raise RuntimeError(f"FFmpeg encoding failed with exit code {ret}: {stderr}")
            break

        # Check cooperative cancellation
        if cancellation_token and cancellation_token.is_cancelled():
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise RuntimeError("FFmpeg export cancelled by user.")

        # Check timeout
        if time.time() - start_t > timeout_s:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise TimeoutError(f"FFmpeg encoding timed out after {timeout_s}s.")

        time.sleep(0.05)


class AudioExportService:
    """Produces standardized deliverable files from the master track."""

    def export(
        self,
        project_id: str,
        master_path: Path | str | None = None,
        output_dir: Path | str | None = None,
        export_profiles: list[ExportProfile] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
        master_wav_path: Path | str | None = None,
    ) -> ExportManifest:
        """Export master audio to target formats (WAV, MP3) and generate export-manifest.yaml."""
        if not export_profiles:
            export_profiles = [ExportProfile(format="wav")]

        actual_master = master_path or master_wav_path
        if not actual_master:
            raise ValueError("Must provide master_path or master_wav_path to export.")

        out_dir = Path(output_dir) if output_dir else Path(actual_master).parent.parent / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        src_master = Path(actual_master)

        if not src_master.exists():
            raise FileNotFoundError(f"Master audio track not found at: {src_master}")

        # Probe master audio properties
        master_sr, master_ch, master_dur_ms = _probe_audio_metadata(src_master)
        artifacts: list[MixArtifact] = []

        total_profiles = len(export_profiles)
        for idx, profile in enumerate(export_profiles, 1):
            if cancellation_token and cancellation_token.is_cancelled():
                break

            fmt = profile.format.lower().strip()

            if fmt == "wav":
                target_wav = out_dir / "FINAL.wav"
                temp_wav = target_wav.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.wav")

                # Atomically copy master to FINAL.wav
                shutil.copy2(src_master, temp_wav)
                temp_wav.replace(target_wav)

                actual_sr, actual_ch, actual_dur_ms = _probe_audio_metadata(
                    target_wav,
                    fallback_sr=master_sr,
                    fallback_ch=master_ch,
                    fallback_dur_ms=master_dur_ms,
                )
                file_size = target_wav.stat().st_size if target_wav.exists() else 0
                sha = compute_file_sha256(target_wav)

                artifacts.append(
                    MixArtifact(
                        project_id=project_id,
                        artifact_id="final_wav",
                        artifact_type="final_wav",
                        file_path="exports/FINAL.wav",
                        sha256=sha,
                        duration_ms=round(actual_dur_ms, 2),
                        sample_rate=actual_sr,
                        channels=actual_ch,
                        file_size_bytes=file_size,
                    )
                )

            elif fmt == "mp3":
                ffmpeg_bin = shutil.which("ffmpeg")
                if not ffmpeg_bin:
                    raise ExportDependencyUnavailableError(
                        f"Cannot export MP3 for project '{project_id}': FFmpeg is not installed on this system. "
                        "Install FFmpeg or request output_formats=['wav']."
                    )

                target_mp3 = out_dir / "FINAL.mp3"
                temp_mp3 = target_mp3.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.mp3")

                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i", str(src_master),
                    "-codec:a", "libmp3lame",
                    "-qscale:a", "2",
                    str(temp_mp3),
                ]
                _run_ffmpeg_encode(cmd, temp_mp3, cancellation_token=cancellation_token)

                if not temp_mp3.exists() or temp_mp3.stat().st_size == 0:
                    if temp_mp3.exists():
                        try:
                            temp_mp3.unlink()
                        except OSError:
                            pass
                    raise RuntimeError("FFmpeg generated an empty or invalid MP3 file.")

                temp_mp3.replace(target_mp3)
                actual_sr, actual_ch, actual_dur_ms = _probe_audio_metadata(
                    target_mp3,
                    fallback_sr=master_sr,
                    fallback_ch=master_ch,
                    fallback_dur_ms=master_dur_ms,
                )
                file_size = target_mp3.stat().st_size
                sha = compute_file_sha256(target_mp3)

                artifacts.append(
                    MixArtifact(
                        project_id=project_id,
                        artifact_id="final_mp3",
                        artifact_type="final_mp3",
                        file_path="exports/FINAL.mp3",
                        sha256=sha,
                        duration_ms=round(actual_dur_ms, 2),
                        sample_rate=actual_sr,
                        channels=actual_ch,
                        file_size_bytes=file_size,
                    )
                )

            if progress_callback and total_profiles > 0:
                pct = (idx / float(total_profiles)) * 100.0
                progress_callback("exporting_deliverables", pct, {"format": fmt})

        if len(artifacts) != len(export_profiles):
            missing_fmts = [p.format for p in export_profiles if not any(a.artifact_type == f"final_{p.format.lower()}" for a in artifacts)]
            raise RuntimeError(f"Export failed to produce requested format(s): {', '.join(missing_fmts)}")

        manifest = ExportManifest(
            project_id=project_id,
            profiles=export_profiles,
            artifacts=artifacts,
            source_master_sha256=compute_file_sha256(src_master),
        )

        manifest_path = out_dir / "export-manifest.yaml"
        manifest.save_yaml(manifest_path)
        return manifest
