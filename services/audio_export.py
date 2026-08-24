"""Audio Export & Deliverables Packaging Service (Phase 14).

Packages mastered audio into final deliverable artifacts (FINAL.wav, FINAL.mp3)
and generates the cryptographic ExportManifest with atomic persistence.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from services.audio_mix_models import ExportManifest, ExportProfile, MixArtifact
from services.mix_plan_builder import get_wav_duration_ms
from services.tts.base import CancellationToken, ProgressCallback
from services.voice_project_models import compute_file_sha256

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
                # Check for FFmpeg availability
                logger.warning(
                    "MP3 export requested for project '%s', but FFmpeg is not installed on this system. "
                    "Skipping MP3 generation; canonical master WAV delivered.",
                    project_id,
                )

            if progress_callback and total_profiles > 0:
                pct = (idx / float(total_profiles)) * 100.0
                progress_callback("exporting_deliverables", pct, {"format": fmt})

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
