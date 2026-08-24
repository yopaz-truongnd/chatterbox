"""Audio Export & Deliverables Packaging Service (Phase 14).

Packages mastered audio into final deliverable artifacts (FINAL.wav, FINAL.mp3)
and generates the cryptographic ExportManifest with atomic persistence.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
import uuid

from services.audio_mix_models import ExportManifest, ExportProfile, MixArtifact
from services.mix_plan_builder import get_wav_duration_ms
from services.tts.base import CancellationToken, ProgressCallback
from services.voice_project_models import (
    ExportDependencyUnavailableError,
    compute_file_sha256,
)

logger = logging.getLogger(__name__)


class AudioExportService:
    """Packaging and export service for master audio."""

    def export(
        self,
        project_id: str,
        master_wav_path: Path | str,
        export_profiles: list[ExportProfile],
        output_dir: Path | str,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExportManifest:
        """Export master audio to deliverable targets (FINAL.wav, FINAL.mp3) and write export-manifest.yaml."""
        src_master = Path(master_wav_path)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not src_master.exists():
            raise FileNotFoundError(f"Master audio file not found at '{src_master}'.")

        master_sha256 = compute_file_sha256(src_master)
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

                duration_ms = get_wav_duration_ms(target_wav)
                file_size = target_wav.stat().st_size if target_wav.exists() else 0
                sha = compute_file_sha256(target_wav)

                artifacts.append(
                    MixArtifact(
                        project_id=project_id,
                        artifact_id="final_wav",
                        artifact_type="final_wav",
                        file_path="exports/FINAL.wav",
                        sha256=sha,
                        duration_ms=round(duration_ms, 2),
                        sample_rate=profile.sample_rate,
                        channels=profile.channels,
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

                try:
                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-i", str(src_master),
                        "-codec:a", "libmp3lame",
                        "-qscale:a", "2",
                        str(temp_mp3),
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                except subprocess.CalledProcessError as exc:
                    if temp_mp3.exists():
                        temp_mp3.unlink()
                    raise RuntimeError(f"FFmpeg MP3 encoding failed: {exc.stderr}") from exc

                if not temp_mp3.exists() or temp_mp3.stat().st_size == 0:
                    if temp_mp3.exists():
                        temp_mp3.unlink()
                    raise RuntimeError("FFmpeg generated an empty or invalid MP3 file.")

                temp_mp3.replace(target_mp3)
                file_size = target_mp3.stat().st_size
                sha = compute_file_sha256(target_mp3)
                wav_duration_ms = get_wav_duration_ms(src_master)

                artifacts.append(
                    MixArtifact(
                        project_id=project_id,
                        artifact_id="final_mp3",
                        artifact_type="final_mp3",
                        file_path="exports/FINAL.mp3",
                        sha256=sha,
                        duration_ms=round(wav_duration_ms, 2),
                        sample_rate=profile.sample_rate,
                        channels=profile.channels,
                        file_size_bytes=file_size,
                    )
                )

            if progress_callback and total_profiles > 0:
                pct = (idx / float(total_profiles)) * 100.0
                progress_callback("exporting_deliverables", pct, {"format": fmt})

        if len(artifacts) != len(export_profiles):
            missing_fmts = [p.format for p in export_profiles if not any(a.artifact_type == f"final_{p.format.lower()}" for a in artifacts)]
            raise RuntimeError(f"Export failed to produce requested format(s): {', '.join(missing_fmts)}")

        # Save ExportManifest
        manifest = ExportManifest(
            project_id=project_id,
            artifacts=artifacts,
            source_master_sha256=master_sha256,
        )

        manifest_path = out_dir / "export-manifest.yaml"
        temp_manifest = manifest_path.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.yaml")
        with open(temp_manifest, "w", encoding="utf-8") as f:
            f.write(manifest.to_yaml())
        temp_manifest.replace(manifest_path)

        if progress_callback:
            progress_callback("export_complete", 100.0, {"artifacts_count": len(artifacts)})

        return manifest
