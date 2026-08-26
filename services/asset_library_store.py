"""Persistent store for the Intelligent Asset Library (Phase 18).

Persists to assets/library-index.yaml using atomic writes and yaml.safe_load.
Provides SHA-256 deduplication and all CRUD operations for LibraryAsset records.
"""

from __future__ import annotations

import os
import tempfile
import threading
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from services.asset_library_models import AssetCategory, LibraryAsset

# Default index file location
_DEFAULT_INDEX = Path(__file__).resolve().parent.parent / "assets" / "library-index.yaml"


def _get_index_path() -> Path:
    """Return the library index path (overridable via env for tests)."""
    env_path = os.getenv("ASSET_LIBRARY_INDEX_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_INDEX


def _load_index(index_path: Path) -> dict[str, Any]:
    """Load the library index from YAML. Always uses yaml.safe_load."""
    if not index_path.exists():
        return {"version": 1, "assets": []}
    with open(index_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "assets" not in data:
        data["assets"] = []
    if "version" not in data:
        data["version"] = 1
    return data


def _save_index(index_path: Path, data: dict[str, Any]) -> None:
    """Atomically write the library index to YAML."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(index_path.parent), suffix=".tmp", prefix="library-index-"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, str(index_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _asset_to_dict(asset: LibraryAsset) -> dict[str, Any]:
    return asset.model_dump(mode="json")


def _dict_to_asset(d: dict[str, Any]) -> LibraryAsset:
    return LibraryAsset.model_validate(d)


_INDEX_LOCKS: dict[str, threading.RLock] = {}
_INDEX_LOCKS_GUARD = threading.Lock()


def _index_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _INDEX_LOCKS_GUARD:
        return _INDEX_LOCKS.setdefault(key, threading.RLock())

class AssetLibraryStore:
    """Thread-safe in-process asset library store backed by YAML."""

    def __init__(self, index_path: Path | None = None) -> None:
        self._index_path: Path = index_path or _get_index_path()
        self._lock = _index_lock(self._index_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        return _load_index(self._index_path)

    def _save(self, data: dict[str, Any]) -> None:
        _save_index(self._index_path, data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_asset(self, asset_id: str) -> LibraryAsset | None:
        """Return a single asset by ID or None."""
        with self._lock:
            data = self._load()
            for item in data["assets"]:
                if item.get("asset_id") == asset_id:
                    return _dict_to_asset(item)
            return None

    def list_assets(self, category: AssetCategory | None = None) -> list[LibraryAsset]:
        """Return all assets, optionally filtered by category."""
        with self._lock:
            data = self._load()
            assets = [_dict_to_asset(item) for item in data["assets"]]
            if category is not None:
                assets = [a for a in assets if a.category == category]
            return assets

    def save_asset(self, asset: LibraryAsset) -> LibraryAsset:
        """Insert or update an asset by asset_id. Returns the saved asset."""
        with self._lock:
            data = self._load()
            assets = data["assets"]
            for i, item in enumerate(assets):
                if item.get("asset_id") == asset.asset_id:
                    assets[i] = _asset_to_dict(asset)
                    self._save(data)
                    return asset
            assets.append(_asset_to_dict(asset))
            self._save(data)
            return asset

    def save_if_sha256_absent(self, asset: LibraryAsset) -> tuple[LibraryAsset, bool]:
        """Atomically enforce content uniqueness across threads and processes."""
        with self._lock:
            lock_path = self._index_path.with_suffix(self._index_path.suffix + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "a", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    data = self._load()
                    for item in data["assets"]:
                        if item.get("sha256") == asset.sha256:
                            return _dict_to_asset(item), False
                    data["assets"].append(_asset_to_dict(asset))
                    self._save(data)
                    return asset, True
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def find_by_sha256(self, sha256: str) -> LibraryAsset | None:
        """Return the first asset matching a given SHA-256 hash, or None."""
        with self._lock:
            data = self._load()
            for item in data["assets"]:
                if item.get("sha256") == sha256:
                    return _dict_to_asset(item)
            return None

    def find_by_category(self, category: AssetCategory) -> list[LibraryAsset]:
        """Return all assets in a given category."""
        return self.list_assets(category=category)

    def disable_asset(self, asset_id: str) -> LibraryAsset | None:
        """Mark an asset as disabled. Returns the updated asset or None if not found."""
        with self._lock:
            data = self._load()
            for i, item in enumerate(data["assets"]):
                if item.get("asset_id") == asset_id:
                    data["assets"][i]["enabled"] = False
                    data["assets"][i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save(data)
                    return _dict_to_asset(data["assets"][i])
            return None

    def update_usage(
        self, asset_id: str, project_id: str | None = None, beat_id: str | None = None
    ) -> LibraryAsset | None:
        """Increment usage_count and set last_used_at timestamp. Returns updated asset or None."""
        with self._lock:
            lock_path = self._index_path.with_suffix(self._index_path.suffix + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "a", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    data = self._load()
                    for i, item in enumerate(data["assets"]):
                        if item.get("asset_id") == asset_id:
                            now = datetime.now(timezone.utc).isoformat()
                            data["assets"][i]["usage_count"] = item.get("usage_count", 0) + 1
                            data["assets"][i]["last_used_at"] = now
                            data["assets"][i]["updated_at"] = now
                            if project_id:
                                ref = {"project_id": project_id}
                                if beat_id:
                                    ref["beat_id"] = beat_id
                                refs = data["assets"][i].setdefault("usage_references", [])
                                if ref not in refs:
                                    refs.append(ref)
                            self._save(data)
                            return _dict_to_asset(data["assets"][i])
                    return None
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# Module-level singleton
_store: AssetLibraryStore | None = None


def get_asset_library_store() -> AssetLibraryStore:
    """Return module-level singleton store."""
    global _store
    if _store is None:
        _store = AssetLibraryStore()
    return _store
