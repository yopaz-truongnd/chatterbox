"""Tests for Asset Library CRUD, SHA-256 dedup, disable, and usage tracking (Phase 18)."""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path

import pytest

from services.asset_library_models import AssetCategory, LibraryAsset
from services.asset_library_store import AssetLibraryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> AssetLibraryStore:
    index = tmp_path / "library-index.yaml"
    return AssetLibraryStore(index_path=index)


def _make_wav(path: Path, duration_frames: int = 4410) -> None:
    """Create a minimal valid WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00" * duration_frames * 2)


def _asset(asset_id: str, category: AssetCategory = AssetCategory.SFX) -> LibraryAsset:
    return LibraryAsset(
        asset_id=asset_id,
        category=category,
        file_path=f"sfx/{asset_id}.wav",
        sha256="a" * 64,
        format="wav",
        duration_ms=1000.0,
        sample_rate=44100,
        channels=1,
        intents=["thunder_crack"],
        keywords=["thunder", "storm"],
    )


# ---------------------------------------------------------------------------
# Store CRUD
# ---------------------------------------------------------------------------


class TestAssetLibraryStoreCRUD:
    def test_save_and_get(self, tmp_path):
        store = _make_store(tmp_path)
        asset = _asset("ast_001")
        store.save_asset(asset)

        fetched = store.get_asset("ast_001")
        assert fetched is not None
        assert fetched.asset_id == "ast_001"
        assert fetched.category == AssetCategory.SFX

    def test_get_nonexistent_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_asset("does_not_exist") is None

    def test_list_assets_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_assets() == []

    def test_list_assets_all(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_001", AssetCategory.SFX))
        store.save_asset(_asset("ast_002", AssetCategory.AMBIENCE))
        assets = store.list_assets()
        assert len(assets) == 2

    def test_list_assets_filtered_by_category(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_001", AssetCategory.SFX))
        store.save_asset(_asset("ast_002", AssetCategory.AMBIENCE))
        sfx = store.list_assets(category=AssetCategory.SFX)
        assert len(sfx) == 1
        assert sfx[0].asset_id == "ast_001"

    def test_update_existing_asset(self, tmp_path):
        store = _make_store(tmp_path)
        asset = _asset("ast_001")
        store.save_asset(asset)

        # Overwrite with mood set
        updated = asset.model_copy(update={"mood": "dark"})
        store.save_asset(updated)

        fetched = store.get_asset("ast_001")
        assert fetched is not None
        assert fetched.mood == "dark"
        # Should still be only one record
        assert len(store.list_assets()) == 1

    def test_persistence_across_instances(self, tmp_path):
        """Data persists to disk and is reloaded by a fresh store instance."""
        index = tmp_path / "library-index.yaml"
        store1 = AssetLibraryStore(index_path=index)
        store1.save_asset(_asset("ast_persist"))

        store2 = AssetLibraryStore(index_path=index)
        fetched = store2.get_asset("ast_persist")
        assert fetched is not None
        assert fetched.asset_id == "ast_persist"


# ---------------------------------------------------------------------------
# SHA-256 dedup
# ---------------------------------------------------------------------------


class TestSHA256Dedup:
    def test_find_by_sha256_returns_asset(self, tmp_path):
        store = _make_store(tmp_path)
        asset = LibraryAsset(
            asset_id="ast_sha",
            category=AssetCategory.SFX,
            file_path="sfx/thunder.wav",
            sha256="deadbeef" * 8,
            format="wav",
            duration_ms=500,
            sample_rate=44100,
            channels=1,
        )
        store.save_asset(asset)

        found = store.find_by_sha256("deadbeef" * 8)
        assert found is not None
        assert found.asset_id == "ast_sha"

    def test_find_by_sha256_returns_none_for_unknown_hash(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.find_by_sha256("0" * 64) is None

    def test_service_dedup_returns_existing_asset_id(self, tmp_path):
        """Service-level dedup: ingesting same SHA-256 twice returns existing asset."""
        from services.asset_library_service import AssetLibraryService

        index = tmp_path / "library-index.yaml"
        store = AssetLibraryStore(index_path=index)

        # Create a real WAV file
        wav_file = tmp_path / "thunder.wav"
        _make_wav(wav_file)

        svc = AssetLibraryService(store=store, permitted_roots=[tmp_path])

        result1 = svc.ingest_file(wav_file, AssetCategory.SFX, {"intents": ["thunder"]})
        assert result1.status == "registered"
        first_id = result1.asset_id

        result2 = svc.ingest_file(wav_file, AssetCategory.SFX)
        assert result2.status == "duplicate"
        assert result2.existing_asset_id == first_id
        assert result2.asset_id == first_id

    def test_duplicate_does_not_create_second_record(self, tmp_path):
        """After dedup, the store still has exactly one record."""
        from services.asset_library_service import AssetLibraryService

        index = tmp_path / "library-index.yaml"
        store = AssetLibraryStore(index_path=index)

        wav_file = tmp_path / "loop.wav"
        _make_wav(wav_file)

        svc = AssetLibraryService(store=store, permitted_roots=[tmp_path])
        svc.ingest_file(wav_file, AssetCategory.AMBIENCE)
        svc.ingest_file(wav_file, AssetCategory.AMBIENCE)

        assets = store.list_assets()
        assert len(assets) == 1


# ---------------------------------------------------------------------------
# Disable
# ---------------------------------------------------------------------------


class TestDisableAsset:
    def test_disable_marks_asset_disabled(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_disable"))

        updated = store.disable_asset("ast_disable")
        assert updated is not None
        assert updated.enabled is False

    def test_disable_nonexistent_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.disable_asset("no_such_id") is None

    def test_disabled_asset_persisted(self, tmp_path):
        index = tmp_path / "library-index.yaml"
        store = AssetLibraryStore(index_path=index)
        store.save_asset(_asset("ast_d2"))
        store.disable_asset("ast_d2")

        store2 = AssetLibraryStore(index_path=index)
        fetched = store2.get_asset("ast_d2")
        assert fetched is not None
        assert fetched.enabled is False

    def test_disabled_assets_excluded_from_matching(self, tmp_path):
        """Disabled assets should not appear in match results."""
        from services.asset_library_service import AssetLibraryService
        from services.asset_matching_service import AssetMatchingService

        index = tmp_path / "library-index.yaml"
        store = AssetLibraryStore(index_path=index)

        wav1 = tmp_path / "forest.wav"
        _make_wav(wav1)
        wav2 = tmp_path / "rain.wav"
        _make_wav(wav2, duration_frames=8820)  # different content = different SHA-256

        svc = AssetLibraryService(store=store, permitted_roots=[tmp_path])
        r1 = svc.ingest_file(wav1, AssetCategory.AMBIENCE, {"intents": ["forest_atmosphere"]})
        r2 = svc.ingest_file(wav2, AssetCategory.AMBIENCE, {"intents": ["forest_atmosphere"]})

        # Disable the first
        store.disable_asset(r1.asset_id)

        matcher = AssetMatchingService(store=store)
        results = matcher.match_assets(["forest_atmosphere"], AssetCategory.AMBIENCE)
        result_ids = {r.asset_id for r in results}

        assert r1.asset_id not in result_ids
        assert r2.asset_id in result_ids


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------


class TestUsageTracking:
    def test_update_usage_increments_count(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_use"))

        updated = store.update_usage("ast_use")
        assert updated is not None
        assert updated.usage_count == 1

    def test_update_usage_twice(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_use2"))
        store.update_usage("ast_use2")
        updated = store.update_usage("ast_use2")
        assert updated.usage_count == 2

    def test_update_usage_sets_last_used_at(self, tmp_path):
        store = _make_store(tmp_path)
        store.save_asset(_asset("ast_ts"))
        updated = store.update_usage("ast_ts")
        assert updated.last_used_at is not None

    def test_update_usage_nonexistent_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.update_usage("ghost") is None

    def test_service_record_usage(self, tmp_path):
        """Service.record_usage delegates to store correctly."""
        from services.asset_library_service import AssetLibraryService

        index = tmp_path / "library-index.yaml"
        store = AssetLibraryStore(index_path=index)
        store.save_asset(_asset("ast_svc_use"))

        svc = AssetLibraryService(store=store, permitted_roots=[tmp_path])
        updated = svc.record_usage("ast_svc_use", project_id="proj_001", beat_id="B01")
        assert updated is not None
        assert updated.usage_count == 1
