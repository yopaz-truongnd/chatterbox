"""Intelligent Asset Library Service (Phase 18).

Handles secure file ingest (path traversal + symlink escape checks, magic byte
format validation, SHA-256 dedup, size limits), directory scanning, and usage
tracking. Business logic only — no FastAPI dependencies.
"""

from __future__ import annotations

import hashlib
import os
import struct
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.asset_library_models import (
    AssetCategory,
    AssetIngestResult,
    AssetScanResult,
    LibraryAsset,
)
from services.asset_library_store import AssetLibraryStore, get_asset_library_store

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Permitted root directories for ingest. Defaults to the project assets/ dir.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PERMITTED_ROOTS: list[Path] = [
    _PROJECT_ROOT / "assets",
    Path(os.getenv("ASSET_INGEST_ROOT", str(_PROJECT_ROOT / "assets"))),
]

# Maximum file size allowed for ingest (default 200 MB).
_MAX_FILE_SIZE_BYTES = int(os.getenv("ASSET_MAX_FILE_BYTES", str(200 * 1024 * 1024)))

# Supported audio formats by extension.
_SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac"}

# Magic byte signatures for supported audio formats.
_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"RIFF", "wav"),       # WAV (RIFF header at offset 0)
    (b"ID3", "mp3"),        # MP3 with ID3 tag
    (b"\xff\xfb", "mp3"),   # MP3 frame sync (MPEG1, Layer 3, no ID3)
    (b"\xff\xf3", "mp3"),   # MP3 frame sync (MPEG2)
    (b"\xff\xf2", "mp3"),   # MP3 frame sync (MPEG2.5)
    (b"\xff\xe3", "mp3"),   # MP3 frame sync variant
    (b"fLaC", "flac"),      # FLAC
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as fh:
        while chunk := fh.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _detect_format_from_magic(file_path: Path) -> str | None:
    """Read the first 12 bytes and identify audio format from magic bytes."""
    try:
        with open(file_path, "rb") as fh:
            header = fh.read(12)
    except OSError:
        return None

    for magic, fmt in _MAGIC_SIGNATURES:
        if header[: len(magic)] == magic:
            return fmt

    return None


def _read_audio_metadata(file_path: Path, fmt: str) -> tuple[float, int, int]:
    """Return (duration_ms, sample_rate, channels) for the given audio file."""
    duration_ms = 0.0
    sample_rate = 44100
    channels = 2

    if fmt == "wav":
        try:
            with wave.open(str(file_path), "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                frames = wf.getnframes()
                if sample_rate > 0:
                    duration_ms = round((frames / float(sample_rate)) * 1000, 2)
            return duration_ms, sample_rate, channels
        except Exception:
            pass

    # Try audioread if available (mp3 / flac / etc.)
    try:
        import audioread

        with audioread.audio_open(str(file_path)) as af:
            duration_ms = round(af.duration * 1000, 2)
            sample_rate = af.samplerate
            channels = af.channels
            return duration_ms, sample_rate, channels
    except Exception:
        pass

    # Fallback: estimate from file size assuming 16-bit 44.1 kHz stereo
    size = file_path.stat().st_size if file_path.exists() else 0
    if size > 44:
        duration_ms = round(((size - 44) / (44100 * 2 * 2)) * 1000, 2)
    return max(500.0, duration_ms), sample_rate, channels


def _make_permitted_roots() -> list[Path]:
    """Return resolved permitted root directories."""
    roots = list(_DEFAULT_PERMITTED_ROOTS)
    extra = os.getenv("ASSET_EXTRA_ROOTS", "")
    for p in extra.split(os.pathsep):
        p = p.strip()
        if p:
            roots.append(Path(p))
    return [Path(os.path.realpath(str(r))) for r in roots]


def _resolve_and_validate_path(raw_path: str | Path, permitted_roots: list[Path]) -> Path:
    """
    Resolve path to absolute, reject:
    1. '..' components in the path string.
    2. Paths whose realpath is outside ALL permitted roots.
    3. Symlinks escaping permitted roots.

    Returns the resolved absolute Path on success.
    Raises ValueError / PermissionError on violations.
    """
    path_str = str(raw_path)

    # 1. Reject '..' traversal attempts (before any resolution)
    parts = Path(path_str).parts
    if ".." in parts:
        raise PermissionError(f"Path traversal detected: '..' is not allowed in '{raw_path}'")

    # 2. Resolve to absolute (follow symlinks for realpath check)
    abs_path = Path(path_str).resolve()
    real_path = Path(os.path.realpath(str(abs_path)))

    # 3. Ensure realpath is inside at least one permitted root
    in_permitted = any(
        str(real_path).startswith(str(root) + os.sep) or real_path == root
        for root in permitted_roots
    )
    if not in_permitted:
        raise PermissionError(
            f"Path '{raw_path}' resolves to '{real_path}' which is outside all permitted roots: "
            + ", ".join(str(r) for r in permitted_roots)
        )

    # 4. Detect symlink escape (symlink target is outside permitted roots)
    if abs_path.is_symlink():
        link_target = Path(os.path.realpath(str(abs_path)))
        in_permitted_via_link = any(
            str(link_target).startswith(str(root) + os.sep) or link_target == root
            for root in permitted_roots
        )
        if not in_permitted_via_link:
            raise PermissionError(
                f"Symlink '{abs_path}' points to '{link_target}' outside permitted roots."
            )

    return abs_path


def _make_asset_id() -> str:
    return "ast_" + uuid.uuid4().hex[:12]


def _relative_path(abs_path: Path, permitted_roots: list[Path]) -> str:
    """Return path relative to the matching permitted root, or the abs path string."""
    for root in permitted_roots:
        try:
            return str(abs_path.relative_to(root))
        except ValueError:
            continue
    return str(abs_path)


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


class AssetLibraryService:
    """Business logic for the Intelligent Asset Library."""

    def __init__(
        self,
        store: AssetLibraryStore | None = None,
        permitted_roots: list[Path] | None = None,
        max_file_bytes: int = _MAX_FILE_SIZE_BYTES,
    ) -> None:
        self._store = store or get_asset_library_store()
        raw_roots = permitted_roots if permitted_roots is not None else _make_permitted_roots()
        self._permitted_roots = [Path(os.path.realpath(str(r))) for r in raw_roots]
        self._max_file_bytes = max_file_bytes

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_file(
        self,
        path: str | Path,
        category: AssetCategory,
        metadata: dict[str, Any] | None = None,
    ) -> AssetIngestResult:
        """Validate and ingest a single audio file into the library.

        Security checks performed (in order):
        1. Reject '..' in path.
        2. Resolve absolute path, verify inside permitted root.
        3. Reject symlinks escaping permitted root.
        4. Validate real audio format via magic bytes (not extension).
        5. Reject files exceeding max size.
        6. SHA-256 dedup check.
        """
        metadata = metadata or {}

        # -- Security: path validation
        try:
            abs_path = _resolve_and_validate_path(path, self._permitted_roots)
        except (PermissionError, ValueError) as exc:
            return AssetIngestResult(
                asset_id="",
                status="rejected",
                reason=str(exc),
            )

        # -- File existence
        if not abs_path.exists() or not abs_path.is_file():
            return AssetIngestResult(
                asset_id="",
                status="rejected",
                reason=f"File not found: {abs_path}",
            )

        # -- Size limit
        size = abs_path.stat().st_size
        if size > self._max_file_bytes:
            return AssetIngestResult(
                asset_id="",
                status="rejected",
                reason=(
                    f"File size {size} bytes exceeds maximum allowed "
                    f"{self._max_file_bytes} bytes."
                ),
            )

        # -- Magic byte format validation
        fmt = _detect_format_from_magic(abs_path)
        if fmt is None:
            return AssetIngestResult(
                asset_id="",
                status="rejected",
                reason=(
                    f"Could not identify a supported audio format from file header. "
                    f"Supported formats: wav, mp3, flac."
                ),
            )

        # -- SHA-256 dedup
        sha256 = _compute_sha256(abs_path)
        existing = self._store.find_by_sha256(sha256)
        if existing is not None:
            return AssetIngestResult(
                asset_id=existing.asset_id,
                status="duplicate",
                existing_asset_id=existing.asset_id,
                reason=f"Duplicate of existing asset '{existing.asset_id}'.",
            )

        # -- Extract audio metadata
        duration_ms, sample_rate, channels = _read_audio_metadata(abs_path, fmt)

        # -- Build asset
        asset_id = metadata.get("asset_id") or _make_asset_id()
        rel_path = _relative_path(abs_path, self._permitted_roots)

        asset = LibraryAsset(
            asset_id=asset_id,
            category=category,
            file_path=rel_path,
            sha256=sha256,
            format=fmt,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            intents=metadata.get("intents", []),
            keywords=metadata.get("keywords", []),
            mood=metadata.get("mood"),
            environment=metadata.get("environment"),
            energy=metadata.get("energy"),
            loopable=bool(metadata.get("loopable", False)),
            license=metadata.get("license"),
            source_url=metadata.get("source_url"),
            attribution=metadata.get("attribution"),
        )

        self._store.save_asset(asset)
        return AssetIngestResult(asset_id=asset_id, status="registered")

    def scan_directory(
        self,
        path: str | Path,
        category: AssetCategory,
    ) -> AssetScanResult:
        """Batch ingest all supported audio files under the given directory."""
        # Validate directory path security
        try:
            abs_dir = _resolve_and_validate_path(path, self._permitted_roots)
        except (PermissionError, ValueError) as exc:
            return AssetScanResult(
                scanned_path=str(path),
                registered=0,
                duplicates=0,
                rejected=1,
                assets=[
                    AssetIngestResult(asset_id="", status="rejected", reason=str(exc))
                ],
            )

        if not abs_dir.is_dir():
            return AssetScanResult(
                scanned_path=str(path),
                registered=0,
                duplicates=0,
                rejected=1,
                assets=[
                    AssetIngestResult(
                        asset_id="",
                        status="rejected",
                        reason=f"Not a directory: {abs_dir}",
                    )
                ],
            )

        results: list[AssetIngestResult] = []
        registered = 0
        duplicates = 0
        rejected = 0

        for file_path in sorted(abs_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                continue
            result = self.ingest_file(file_path, category)
            results.append(result)
            if result.status == "registered":
                registered += 1
            elif result.status == "duplicate":
                duplicates += 1
            else:
                rejected += 1

        return AssetScanResult(
            scanned_path=str(path),
            registered=registered,
            duplicates=duplicates,
            rejected=rejected,
            assets=results,
        )

    # ------------------------------------------------------------------
    # Read / Management
    # ------------------------------------------------------------------

    def get_asset(self, asset_id: str) -> LibraryAsset | None:
        """Return a single asset by ID or None."""
        return self._store.get_asset(asset_id)

    def list_assets(self, category: AssetCategory | None = None) -> list[LibraryAsset]:
        """Return all assets, optionally filtered by category."""
        return self._store.list_assets(category=category)

    def disable_asset(self, asset_id: str) -> LibraryAsset | None:
        """Disable an asset so it is excluded from matching. Returns updated asset or None."""
        return self._store.disable_asset(asset_id)

    def record_usage(
        self,
        asset_id: str,
        project_id: str | None = None,
        beat_id: str | None = None,
    ) -> LibraryAsset | None:
        """Record that an asset was used in a project/beat. Increments usage_count."""
        return self._store.update_usage(asset_id)


# Module-level singleton
_service: AssetLibraryService | None = None


def get_asset_library_service() -> AssetLibraryService:
    global _service
    if _service is None:
        _service = AssetLibraryService()
    return _service
