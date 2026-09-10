"""Asset Ingest & Library Management Service (Phase 6).

Handles inspecting audio files from inbox/local paths, metadata extraction,
manifest ingestion, usage tracking, and cross-project shopping list aggregation.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
from typing import Any
import wave

from services.resource_models import (
    AssetInspection,
    IngestMetadata,
    RequirementPriority,
    ResourceCategory,
    ResourceEntry,
    ResourceFile,
    ResourceManifest,
    ResourceMixSettings,
    ResourceProperties,
    ResourceReport,
    ResourceShoppingList,
    ResourceUsage,
    ShoppingListItem,
)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".aiff"}


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_audio_metadata(file_path: Path) -> tuple[float, int, int]:
    """Read duration (seconds), sample rate, and channels from audio file.
    
    Falls back gracefully if header cannot be read.
    """
    ext = file_path.suffix.lower()
    duration = 0.0
    sample_rate = 44100
    channels = 2

    if ext == ".wav":
        try:
            with wave.open(str(file_path), "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                frames = wf.getnframes()
                if sample_rate > 0:
                    duration = round(frames / float(sample_rate), 2)
                return duration, sample_rate, channels
        except Exception:
            pass

    # Try audioread or soundfile if available
    try:
        import audioread
        with audioread.audio_open(str(file_path)) as f:
            duration = round(f.duration, 2)
            sample_rate = f.samplerate
            channels = f.channels
            return duration, sample_rate, channels
    except Exception:
        pass

    # Fallback estimate based on file size if 16-bit 44.1kHz stereo WAV
    size = file_path.stat().st_size if file_path.exists() else 0
    if size > 44:
        duration = round((size - 44) / (44100 * 2 * 2), 2)
    return max(0.5, duration), sample_rate, channels


def inspect_asset(file_path: str | Path) -> AssetInspection:
    """Inspect an audio asset file and extract properties and smart metadata suggestions."""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Asset file not found at: {file_path}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported audio format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    size_bytes = p.stat().st_size
    sha256_hash = _compute_sha256(p)
    duration, sample_rate, channels = _read_audio_metadata(p)

    stem = p.stem.lower()
    path_str = str(p).lower()

    # Suggest Category
    if any(k in path_str for k in ("ambience", "ambient", "atmosphere", "drone", "wind", "rain", "cave", "forest")):
        suggested_category = ResourceCategory.AMBIENCE
    elif any(k in path_str for k in ("music", "ost", "score", "theme")):
        suggested_category = ResourceCategory.MUSIC
    else:
        suggested_category = ResourceCategory.SFX

    # Suggest Intents
    clean_tokens = [re.sub(r"[^\w]", "", t) for t in stem.split("_") if t and not t.isdigit()]
    suggested_intents = []
    if clean_tokens:
        primary_intent = "_".join(clean_tokens)
        suggested_intents.append(primary_intent)
        if suggested_category == ResourceCategory.AMBIENCE and not primary_intent.endswith("_atmosphere"):
            suggested_intents.append(f"{primary_intent}_atmosphere")

    # Suggest Tags
    suggested_tags = list(set(t for t in clean_tokens if len(t) > 2))
    for parent_part in p.parts[:-1]:
        part_clean = re.sub(r"[^\w]", "", parent_part.lower())
        if part_clean and part_clean not in ("assets", "inbox", "wav", "audio", "sfx", "ambience"):
            suggested_tags.append(part_clean)

    # Suggest Intensity
    suggested_intensity = 3
    if any(k in stem for k in ("heavy", "huge", "slam", "boom", "climax", "intense")):
        suggested_intensity = 5
    elif any(k in stem for k in ("strong", "prominent", "impact", "roar")):
        suggested_intensity = 4
    elif any(k in stem for k in ("soft", "subtle", "whisper", "quiet")):
        suggested_intensity = 2

    # Suggest Loopable
    suggested_loopable = suggested_category == ResourceCategory.AMBIENCE or "loop" in stem

    return AssetInspection(
        file_path=str(p),
        filename=p.name,
        extension=ext.lstrip("."),
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        size_bytes=size_bytes,
        hash_sha256=sha256_hash,
        suggested_category=suggested_category,
        suggested_intents=suggested_intents,
        suggested_tags=suggested_tags,
        suggested_intensity=suggested_intensity,
        suggested_loopable=suggested_loopable,
    )


def ingest_asset(
    file_path: str | Path,
    metadata: IngestMetadata,
    manifest: ResourceManifest,
    target_relative_path: str | None = None,
) -> tuple[ResourceEntry, ResourceManifest]:
    """Ingest a new audio asset into the manifest with full validation.

    Does not copy or move files unless specified. Returns the created ResourceEntry and updated ResourceManifest.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Asset file not found at: {file_path}")

    # 1. Validation
    # Check duplicate ID
    if manifest.find_by_id(metadata.resource_id) is not None:
        raise ValueError(f"Duplicate resource ID '{metadata.resource_id}' already exists in manifest.")

    inspection = inspect_asset(p)

    rel_path = target_relative_path or str(p)

    # Check duplicate path
    for existing in manifest.resources:
        if existing.file.path == rel_path:
            raise ValueError(f"Resource with path '{rel_path}' already exists as ID '{existing.id}'.")

    # 2. Build ResourceEntry
    entry = ResourceEntry(
        id=metadata.resource_id,
        file=ResourceFile(
            path=rel_path,
            format=inspection.extension,
            size_bytes=inspection.size_bytes,
            hash=inspection.hash_sha256,
        ),
        category=metadata.category,
        intents=metadata.intents,
        tags=metadata.tags,
        properties=ResourceProperties(
            duration=inspection.duration,
            loopable=metadata.loopable,
            intensity=metadata.intensity,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
        ),
        mix=ResourceMixSettings(
            recommended_db=metadata.recommended_db,
            max_db=metadata.max_db,
        ),
        usage=ResourceUsage(total=0, last_used=None, recent_projects=[]),
    )

    manifest.resources.append(entry)
    return entry, manifest


def record_resource_usage(
    manifest: ResourceManifest,
    project_id: str,
    selected_resource_ids: list[str],
) -> ResourceManifest:
    """Record usage of selected resources after project accepts/commits them.

    Explicit state update — does not mutate during read-only preview/resolution.
    """
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    for res_id in selected_resource_ids:
        entry = manifest.find_by_id(res_id)
        if entry:
            entry.usage.total += 1
            entry.usage.last_used = {
                "project": project_id,
                "date": today_str,
            }
            if project_id not in entry.usage.recent_projects:
                entry.usage.recent_projects.insert(0, project_id)
                # Keep recent project history reasonable
                entry.usage.recent_projects = entry.usage.recent_projects[:10]
    return manifest


def build_resource_shopping_list(reports: list[ResourceReport]) -> ResourceShoppingList:
    """Aggregate missing resource gaps across multiple project reports into a prioritized shopping list."""
    aggregated: dict[str, dict[str, Any]] = {}

    for report in reports:
        proj_id = report.project_id
        for gap in report.missing:
            # Group key
            if gap.type == ResourceCategory.KNOWLEDGE and gap.term:
                item_key = f"knowledge:{gap.term.lower()}"
                display_name = gap.term
            else:
                item_key = f"{gap.type.value}:{gap.intent or gap.id}"
                display_name = gap.intent or gap.id

            if item_key not in aggregated:
                aggregated[item_key] = {
                    "item_key": item_key,
                    "type": gap.type,
                    "intent_or_term": display_name,
                    "priority": gap.priority,
                    "project_ids": set(),
                    "suggested_search": list(gap.suggested_search),
                    "reason": gap.reason,
                }

            aggregated[item_key]["project_ids"].add(proj_id)
            # If any project marks it REQUIRED, elevate priority
            if gap.priority == RequirementPriority.REQUIRED:
                aggregated[item_key]["priority"] = RequirementPriority.REQUIRED
            elif gap.priority == RequirementPriority.RECOMMENDED and aggregated[item_key]["priority"] == RequirementPriority.OPTIONAL:
                aggregated[item_key]["priority"] = RequirementPriority.RECOMMENDED

            for s in gap.suggested_search:
                if s not in aggregated[item_key]["suggested_search"]:
                    aggregated[item_key]["suggested_search"].append(s)

    # Convert to items
    items: list[ShoppingListItem] = []
    for data in aggregated.values():
        p_list = sorted(list(data["project_ids"]))
        items.append(
            ShoppingListItem(
                item_key=data["item_key"],
                type=data["type"],
                intent_or_term=data["intent_or_term"],
                priority=data["priority"],
                needed_by_projects_count=len(p_list),
                project_ids=p_list,
                suggested_search=data["suggested_search"],
                reason=data["reason"],
            )
        )

    # Ranking:
    # 1. Priority: REQUIRED (0) -> RECOMMENDED (1) -> OPTIONAL (2)
    # 2. Count: descending
    # 3. Item key: ascending
    priority_order = {
        RequirementPriority.REQUIRED: 0,
        RequirementPriority.RECOMMENDED: 1,
        RequirementPriority.OPTIONAL: 2,
    }

    items.sort(
        key=lambda item: (
            priority_order.get(item.priority, 3),
            -item.needed_by_projects_count,
            item.item_key,
        )
    )

    return ResourceShoppingList(items=items)
