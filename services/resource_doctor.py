"""Resource Doctor Service (Phase 6).

Diagnostics and health checks for Asset Manifest, Local Asset Files, and
Pronunciation Knowledge integrity.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.resource_models import (
    DoctorIssue,
    DoctorReport,
    PronunciationKnowledge,
    PronunciationStatus,
    ResourceManifest,
)


def diagnose_resources(
    manifest: ResourceManifest,
    knowledge: PronunciationKnowledge | None = None,
    assets_root: str | Path | None = None,
) -> DoctorReport:
    """Run comprehensive health checks on Asset Manifest and Pronunciation Knowledge."""
    issues: list[DoctorIssue] = []
    warnings: list[DoctorIssue] = []

    if assets_root:
        root_path = Path(assets_root)
    else:
        root_path = Path(__file__).resolve().parent.parent / "assets"

    # 1. Check Manifest Entries
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_hashes: dict[str, str] = {} # hash -> id

    for entry in manifest.resources:
        # ID uniqueness
        if entry.id in seen_ids:
            issues.append(
                DoctorIssue(
                    severity="error",
                    component="manifest",
                    message=f"Duplicate resource ID '{entry.id}' detected.",
                    details={"resource_id": entry.id},
                )
            )
        seen_ids.add(entry.id)

        # Path uniqueness
        if entry.file.path in seen_paths:
            issues.append(
                DoctorIssue(
                    severity="error",
                    component="manifest",
                    message=f"Duplicate file path '{entry.file.path}' registered in manifest.",
                    details={"resource_id": entry.id, "path": entry.file.path},
                )
            )
        seen_paths.add(entry.file.path)

        # File Existence check
        file_path = root_path / entry.file.path
        # Also try direct path if relative to workspace
        if not file_path.exists() and not Path(entry.file.path).exists():
            warnings.append(
                DoctorIssue(
                    severity="warning",
                    component="filesystem",
                    message=f"Asset file '{entry.file.path}' for resource '{entry.id}' does not exist on disk.",
                    details={"resource_id": entry.id, "expected_path": str(file_path)},
                )
            )

        # Hash duplication check
        if entry.file.hash:
            if entry.file.hash in seen_hashes:
                other_id = seen_hashes[entry.file.hash]
                warnings.append(
                    DoctorIssue(
                        severity="warning",
                        component="manifest",
                        message=f"Resource '{entry.id}' has identical file content hash as '{other_id}'.",
                        details={"resource_id": entry.id, "other_id": other_id},
                    )
                )
            else:
                seen_hashes[entry.file.hash] = entry.id

        # Untagged check
        if not entry.tags:
            warnings.append(
                DoctorIssue(
                    severity="warning",
                    component="manifest",
                    message=f"Resource '{entry.id}' has no tags assigned.",
                    details={"resource_id": entry.id},
                )
            )

        # No intents check
        if not entry.intents:
            issues.append(
                DoctorIssue(
                    severity="error",
                    component="manifest",
                    message=f"Resource '{entry.id}' has no intents defined.",
                    details={"resource_id": entry.id},
                )
            )

    # 2. Check Pronunciation Knowledge
    if knowledge:
        seen_aliases: dict[str, str] = {} # alias -> canonical_key

        for key, p_entry in knowledge.terms.items():
            if not p_entry.display:
                issues.append(
                    DoctorIssue(
                        severity="error",
                        component="pronunciation",
                        message=f"Pronunciation term '{key}' is missing a display name.",
                        details={"term_key": key},
                    )
                )

            # Verified terms should have tts_hint
            if p_entry.status == PronunciationStatus.VERIFIED:
                if not p_entry.pronunciation.tts_hint:
                    warnings.append(
                        DoctorIssue(
                            severity="warning",
                            component="pronunciation",
                            message=f"Verified pronunciation term '{key}' is missing a tts_hint.",
                            details={"term_key": key},
                        )
                    )

            # Check alias collisions
            for alias in p_entry.aliases:
                alias_norm = alias.strip().lower()
                if alias_norm in seen_aliases:
                    other_term = seen_aliases[alias_norm]
                    warnings.append(
                        DoctorIssue(
                            severity="warning",
                            component="pronunciation",
                            message=f"Alias '{alias}' in term '{key}' collides with term '{other_term}'.",
                            details={"alias": alias, "term_a": key, "term_b": other_term},
                        )
                    )
                else:
                    seen_aliases[alias_norm] = key

    # 3. Check TTS Provider Configuration (Gemini)
    try:
        from services.tts.gemini import GeminiTTSProvider, GeminiTTSConfig
        provider = GeminiTTSProvider()
        health = provider.healthcheck()
        if not health.configured:
            warnings.append(
                DoctorIssue(
                    severity="warning",
                    component="tts_provider",
                    message=f"Gemini TTS Provider not fully configured: {health.message}",
                    details=health.details,
                )
            )
    except Exception as exc:
        warnings.append(
            DoctorIssue(
                severity="warning",
                component="tts_provider",
                message=f"Failed to inspect Gemini TTS Provider: {exc}",
            )
        )

    healthy = len(issues) == 0

    return DoctorReport(
        healthy=healthy,
        issues=issues,
        warnings=warnings,
    )
