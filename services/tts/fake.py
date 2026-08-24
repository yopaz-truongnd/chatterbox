"""Fake TTS Provider for deterministic offline testing and CI workflows (Phase 8)."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import wave
from typing import Any

from services.render_models import (
    ProviderCapabilities,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import TTSProvider


class FakeTTSProvider(TTSProvider):
    """Deterministic Fake TTS Provider that creates valid WAV files without API calls."""

    def __init__(
        self,
        sample_rate: int = 24000,
        fail_on_beats: list[str] | None = None,
        simulate_clipping_beats: list[str] | None = None,
        simulate_silent_beats: list[str] | None = None,
        fixed_duration: float | None = None,
    ):
        self.sample_rate = sample_rate
        self.fail_on_beats = set(fail_on_beats or [])
        self.simulate_clipping_beats = set(simulate_clipping_beats or [])
        self.simulate_silent_beats = set(simulate_silent_beats or [])
        self.fixed_duration = fixed_duration
        self.render_call_count = 0
        self.rendered_requests: list[TTSRenderRequest] = []

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            available=True,
            provider_name="fake",
            message="Fake TTS Provider is ready",
            details={"sample_rate": self.sample_rate},
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_emotion=True,
            supports_pace=True,
            supports_pronunciation=True,
            supports_director_notes=True,
            supports_ssml=False,
            supports_seed=True,
        )

    def render(self, request: TTSRenderRequest, output_dir: Path) -> TTSRenderResult:
        self.render_call_count += 1
        self.rendered_requests.append(request)

        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"attempt_{request.attempt_id:02d}.wav"
        audio_path = output_dir / filename

        # 1. Simulate failure if configured
        if request.beat_id in self.fail_on_beats:
            return TTSRenderResult(
                success=False,
                provider="fake",
                model="fake-tts-v1",
                audio_path=None,
                error=f"Simulated provider failure for beat {request.beat_id}",
            )

        # 2. Calculate duration
        words = request.text.split()
        target_wpm = request.target_wpm or 138
        if self.fixed_duration is not None:
            duration = self.fixed_duration
        else:
            # Baseline duration based on words and pace
            base_dur = max(0.6, (len(words) / max(60, target_wpm)) * 60.0)
            if request.pace:
                base_dur = base_dur / max(0.5, request.pace)
            duration = round(base_dur, 2)

        total_samples = int(self.sample_rate * duration)

        # 3. Generate PCM samples
        is_silent = request.beat_id in self.simulate_silent_beats
        is_clipping = request.beat_id in self.simulate_clipping_beats

        samples = bytearray()
        freq = 440.0  # standard A4 tone

        for i in range(total_samples):
            if is_silent:
                val = 0
            elif is_clipping:
                # Square wave saturated to maximum 16-bit range
                val = 32767 if (i % 50 < 25) else -32768
            else:
                # Clean sine wave with modest amplitude (-18 dBFS)
                t = float(i) / self.sample_rate
                # Envelope fade in/out
                env = min(1.0, i / 480.0) * min(1.0, (total_samples - i) / 480.0)
                raw_val = math.sin(2.0 * math.pi * freq * t) * 10000.0 * env
                val = int(max(-32768, min(32767, raw_val)))

            samples.extend(struct.pack("<h", val))

        # 4. Write WAV file
        with wave.open(str(audio_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(bytes(samples))

        return TTSRenderResult(
            success=True,
            provider="fake",
            model="fake-tts-v1",
            audio_path=str(audio_path),
            duration=duration,
            sample_rate=self.sample_rate,
            channels=1,
            provider_request_id=f"fake_req_{request.beat_id}_{request.attempt_id}",
            raw_metadata={"words_count": len(words), "simulated_pace": request.pace},
        )
