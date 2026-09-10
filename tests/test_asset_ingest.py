"""Unit tests for Phase 6 Asset Ingest, Library Management, and Resource Doctor."""

import os
from pathlib import Path
import tempfile
import unittest
import wave

from services.resource_models import (
    DoctorIssue,
    DoctorReport,
    IngestMetadata,
    PronunciationEntry,
    PronunciationHint,
    PronunciationKnowledge,
    PronunciationStatus,
    ReadinessReport,
    RequirementPriority,
    ResourceCategory,
    ResourceEntry,
    ResourceFile,
    ResourceGap,
    ResourceManifest,
    ResourceMixSettings,
    ResourceProperties,
    ResourceReport,
    ResourceResolution,
    ResourceUsage,
)
from services.asset_ingest import (
    inspect_asset,
    ingest_asset,
    record_resource_usage,
    build_resource_shopping_list,
)
from services.resource_doctor import diagnose_resources


class TestAssetIngestPhase6(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create a sample test WAV file
        self.sample_wav = self.dir_path / "ancient_temple_drone_01.wav"
        with wave.open(str(self.sample_wav), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(44100)
            # Write 1 second of silence
            wf.writeframes(b"\x00" * 44100 * 4)

        self.manifest = ResourceManifest(
            version=1,
            resources=[
                ResourceEntry(
                    id="ambience_dark_01",
                    file=ResourceFile(path="ambience/dark/dark_wind_01.wav", format="wav", hash="hash_01"),
                    category=ResourceCategory.AMBIENCE,
                    intents=["ancient_dark_atmosphere"],
                    tags=["dark", "ancient", "wind"],
                    properties=ResourceProperties(duration=43.2, loopable=True, intensity=2),
                    mix=ResourceMixSettings(recommended_db=-29.0, max_db=-24.0),
                    usage=ResourceUsage(total=2, last_used={"project": "proj_a", "date": "2026-08-20"}, recent_projects=["proj_a"]),
                )
            ],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_asset(self):
        inspection = inspect_asset(self.sample_wav)
        self.assertEqual(inspection.filename, "ancient_temple_drone_01.wav")
        self.assertEqual(inspection.extension, "wav")
        self.assertEqual(inspection.channels, 2)
        self.assertEqual(inspection.sample_rate, 44100)
        self.assertAlmostEqual(inspection.duration, 1.0, places=1)
        self.assertEqual(inspection.suggested_category, ResourceCategory.AMBIENCE)
        self.assertIn("ancient_temple_drone", inspection.suggested_intents)
        self.assertIn("temple", inspection.suggested_tags)
        self.assertTrue(len(inspection.hash_sha256) == 64)

    def test_ingest_asset_success(self):
        meta = IngestMetadata(
            resource_id="ambience_temple_02",
            category=ResourceCategory.AMBIENCE,
            intents=["ancient_temple_drone", "sacred_chamber"],
            tags=["ancient", "temple", "sacred"],
            intensity=3,
            loopable=True,
            recommended_db=-30.0,
            max_db=-25.0,
        )

        entry, updated_manifest = ingest_asset(
            file_path=self.sample_wav,
            metadata=meta,
            manifest=self.manifest,
            target_relative_path="ambience/ancient/ancient_temple_drone_01.wav",
        )

        self.assertEqual(entry.id, "ambience_temple_02")
        self.assertEqual(entry.category, ResourceCategory.AMBIENCE)
        self.assertEqual(len(updated_manifest.resources), 2)
        self.assertEqual(updated_manifest.resources[-1].id, "ambience_temple_02")

    def test_ingest_duplicate_id_rejected(self):
        meta = IngestMetadata(
            resource_id="ambience_dark_01", # Duplicate ID
            category=ResourceCategory.AMBIENCE,
            intents=["dark_wind"],
            tags=["dark"],
        )
        with self.assertRaises(ValueError) as ctx:
            ingest_asset(self.sample_wav, meta, self.manifest)
        self.assertIn("Duplicate resource ID", str(ctx.exception))

    def test_ingest_duplicate_path_rejected(self):
        meta = IngestMetadata(
            resource_id="ambience_dark_02",
            category=ResourceCategory.AMBIENCE,
            intents=["dark_wind"],
            tags=["dark"],
        )
        with self.assertRaises(ValueError) as ctx:
            ingest_asset(
                self.sample_wav,
                meta,
                self.manifest,
                target_relative_path="ambience/dark/dark_wind_01.wav", # Duplicate path
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_record_resource_usage_explicit_commit(self):
        self.assertEqual(self.manifest.resources[0].usage.total, 2)
        
        # Explicitly record usage
        updated = record_resource_usage(
            manifest=self.manifest,
            project_id="proj_b",
            selected_resource_ids=["ambience_dark_01"],
        )

        self.assertEqual(updated.resources[0].usage.total, 3)
        self.assertEqual(updated.resources[0].usage.last_used["project"], "proj_b")
        self.assertIn("proj_b", updated.resources[0].usage.recent_projects)

    def test_build_resource_shopping_list_aggregation_and_ranking(self):
        # Report 1
        rep1 = ResourceReport(
            project_id="proj_01",
            readiness=ReadinessReport(score=80, render_blocked=True),
            missing=[
                ResourceGap(
                    id="RG_01",
                    type=ResourceCategory.KNOWLEDGE,
                    term="Qiongqi",
                    priority=RequirementPriority.REQUIRED,
                    suggested_search=["how to pronounce Qiongqi"],
                ),
                ResourceGap(
                    id="RG_02",
                    type=ResourceCategory.SFX,
                    intent="supernatural_reveal_riser",
                    priority=RequirementPriority.RECOMMENDED,
                    suggested_search=["dark supernatural riser"],
                ),
            ],
        )

        # Report 2
        rep2 = ResourceReport(
            project_id="proj_02",
            readiness=ReadinessReport(score=85, render_blocked=True),
            missing=[
                ResourceGap(
                    id="RG_03",
                    type=ResourceCategory.KNOWLEDGE,
                    term="Qiongqi",
                    priority=RequirementPriority.REQUIRED,
                    suggested_search=["Qiongqi pronunciation"],
                ),
                ResourceGap(
                    id="RG_04",
                    type=ResourceCategory.SFX,
                    intent="supernatural_reveal_riser",
                    priority=RequirementPriority.RECOMMENDED,
                    suggested_search=["cinematic tension riser"],
                ),
                ResourceGap(
                    id="RG_05",
                    type=ResourceCategory.SFX,
                    intent="cosmic_sparkle_sfx",
                    priority=RequirementPriority.OPTIONAL,
                ),
            ],
        )

        # Report 3
        rep3 = ResourceReport(
            project_id="proj_03",
            readiness=ReadinessReport(score=90, render_blocked=False),
            missing=[
                ResourceGap(
                    id="RG_06",
                    type=ResourceCategory.SFX,
                    intent="supernatural_reveal_riser",
                    priority=RequirementPriority.RECOMMENDED,
                ),
            ],
        )

        shopping_list = build_resource_shopping_list([rep1, rep2, rep3])
        items = shopping_list.items

        self.assertEqual(len(items), 3)

        # Item 1: Qiongqi (REQUIRED, needed by 2 projects)
        self.assertEqual(items[0].type, ResourceCategory.KNOWLEDGE)
        self.assertEqual(items[0].intent_or_term, "Qiongqi")
        self.assertEqual(items[0].priority, RequirementPriority.REQUIRED)
        self.assertEqual(items[0].needed_by_projects_count, 2)

        # Item 2: supernatural_reveal_riser (RECOMMENDED, needed by 3 projects)
        self.assertEqual(items[1].type, ResourceCategory.SFX)
        self.assertEqual(items[1].intent_or_term, "supernatural_reveal_riser")
        self.assertEqual(items[1].priority, RequirementPriority.RECOMMENDED)
        self.assertEqual(items[1].needed_by_projects_count, 3)

        # Item 3: cosmic_sparkle_sfx (OPTIONAL, needed by 1 project)
        self.assertEqual(items[2].type, ResourceCategory.SFX)
        self.assertEqual(items[2].priority, RequirementPriority.OPTIONAL)
        self.assertEqual(items[2].needed_by_projects_count, 1)

    def test_resource_doctor_diagnostics(self):
        # Manifest with an error (no intents) and a warning (untagged)
        faulty_manifest = ResourceManifest(
            version=1,
            resources=[
                ResourceEntry(
                    id="bad_asset_01",
                    file=ResourceFile(path="non/existent/path.wav", format="wav"),
                    category=ResourceCategory.SFX,
                    intents=[], # Error: no intents
                    tags=[], # Warning: untagged
                )
            ]
        )

        knowledge = PronunciationKnowledge(
            version=1,
            terms={
                "bad_term": PronunciationEntry(
                    display="BadTerm",
                    status=PronunciationStatus.VERIFIED,
                    pronunciation=PronunciationHint(tts_hint=None), # Warning: verified but no tts_hint
                )
            }
        )

        report = diagnose_resources(faulty_manifest, knowledge, assets_root=self.dir_path)
        self.assertFalse(report.healthy)
        self.assertTrue(any("no intents" in iss.message for iss in report.issues))
        self.assertTrue(any("no tags" in warn.message for warn in report.warnings))
        self.assertTrue(any("missing a tts_hint" in warn.message for warn in report.warnings))


if __name__ == "__main__":
    unittest.main()
