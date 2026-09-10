"""Persistence Store for Story Series (Phase 19).

Handles atomic YAML reads and writes for VoiceSeries and VoiceSeriesEpisode
under projects/series/{series_id}/.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
import yaml

from services.voice_series_models import VoiceSeries, VoiceSeriesEpisode

_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')


def _validate_id(id_: str, label: str) -> None:
    if not _ID_RE.match(id_):
        raise ValueError(f"Invalid {label}: {id_!r}. Only a-z A-Z 0-9 _ - allowed.")


class VoiceSeriesStore:
    """Store for VoiceSeries and VoiceSeriesEpisode records."""

    def __init__(self, root_dir: Path | str | None = None) -> None:
        if root_dir is not None:
            self.root_dir = Path(root_dir)
        else:
            data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
            if data_dir:
                self.root_dir = Path(data_dir) / "series"
            else:
                self.root_dir = Path("projects/series")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _get_series_dir(self, series_id: str) -> Path:
        _validate_id(series_id, "series_id")
        return self.root_dir / series_id

    def _get_episodes_dir(self, series_id: str) -> Path:
        return self._get_series_dir(series_id) / "episodes"

    def series_exists(self, series_id: str) -> bool:
        return (self._get_series_dir(series_id) / "series.yaml").exists()

    def save_series(self, series: VoiceSeries) -> None:
        series_dir = self._get_series_dir(series.series_id)
        series_dir.mkdir(parents=True, exist_ok=True)
        file_path = series_dir / "series.yaml"
        tmp_path = series_dir / "series.yaml.tmp"

        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(series.to_yaml())
        tmp_path.replace(file_path)

    def get_series(self, series_id: str) -> VoiceSeries | None:
        file_path = self._get_series_dir(series_id) / "series.yaml"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return VoiceSeries.from_dict(data) if data else None

    def list_series(self) -> list[VoiceSeries]:
        results = []
        if not self.root_dir.exists():
            return results
        for p in self.root_dir.iterdir():
            if p.is_dir():
                s = self.get_series(p.name)
                if s is not None:
                    results.append(s)
        results.sort(key=lambda s: s.created_at, reverse=True)
        return results

    def save_episode(self, episode: VoiceSeriesEpisode) -> None:
        _validate_id(episode.series_id, "series_id")
        _validate_id(episode.episode_id, "episode_id")
        ep_dir = self._get_episodes_dir(episode.series_id)
        ep_dir.mkdir(parents=True, exist_ok=True)
        file_path = ep_dir / f"{episode.episode_id}.yaml"
        tmp_path = ep_dir / f"{episode.episode_id}.yaml.tmp"

        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(episode.to_yaml())
        tmp_path.replace(file_path)

    def get_episode(self, series_id: str, episode_id: str) -> VoiceSeriesEpisode | None:
        _validate_id(series_id, "series_id")
        _validate_id(episode_id, "episode_id")
        file_path = self._get_episodes_dir(series_id) / f"{episode_id}.yaml"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return VoiceSeriesEpisode.from_dict(data) if data else None

    def list_episodes(self, series_id: str) -> list[VoiceSeriesEpisode]:
        ep_dir = self._get_episodes_dir(series_id)
        results = []
        if not ep_dir.exists():
            return results
        for p in ep_dir.glob("*.yaml"):
            if not p.name.endswith(".tmp"):
                with open(p, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if data:
                    results.append(VoiceSeriesEpisode.from_dict(data))
        results.sort(key=lambda e: e.episode_number)
        return results


_GLOBAL_SERIES_STORE: VoiceSeriesStore | None = None


def get_voice_series_store(root_dir: Path | str | None = None) -> VoiceSeriesStore:
    global _GLOBAL_SERIES_STORE
    if root_dir is not None:
        return VoiceSeriesStore(root_dir=root_dir)
    if _GLOBAL_SERIES_STORE is None:
        _GLOBAL_SERIES_STORE = VoiceSeriesStore()
    return _GLOBAL_SERIES_STORE
