"""Project-scoped resource resolution without source-script mutation."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

from services.director_review_models import DirectorRevisionEvent, ResourceResolutionResult
from services.director_revision_store import DirectorRevisionStore
from services.render_models import RenderStatus
from services.resource_manager import load_manifest, resolve_asset_file_path
from services.resource_models import (
    ReadinessReport,
    RequirementPriority,
    ResourceCategory,
    ResourceEntry,
)
from services.voice_project_models import InvalidProjectStateError
from services.voice_project_service import VoiceProjectService


MIX_ARTIFACTS = ["mix_plan", "premaster_wav", "master_wav", "exports", "final_approval"]


class DirectorResourceService:
    def __init__(self, project_service: VoiceProjectService, revision_store: DirectorRevisionStore | None = None):
        self.project_service = project_service
        self.store = project_service.store
        self.revisions = revision_store or DirectorRevisionStore(self.store)

    def _require_project(self, project_id: str) -> None:
        self.store.get_project_state(project_id)

    def _persist_override(self, project_id: str, resource_id: str, decision: dict) -> None:
        import yaml
        path = self.store.get_project_dir(project_id) / "director-resource-overrides.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "overrides": {}}
        data.setdefault("overrides", {})[resource_id] = decision
        pending = path.with_suffix(".pending")
        try:
            pending.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            pending.replace(path)
        finally:
            if pending.exists():
                pending.unlink()

    @staticmethod
    def _public_report(report) -> dict:
        data = report.to_dict()
        for collection in ("resolved", "substituted"):
            for item in data.get(collection, []):
                selected = item.get("selected")
                if selected and selected.get("file"):
                    selected["file"] = {
                        "artifact_id": selected.get("id"),
                        "format": selected["file"].get("format"),
                    }
        return data

    @staticmethod
    def _refresh_readiness(report) -> None:
        required = sum(g.priority == RequirementPriority.REQUIRED for g in report.missing)
        recommended = sum(g.priority == RequirementPriority.RECOMMENDED for g in report.missing)
        optional = sum(g.priority == RequirementPriority.OPTIONAL for g in report.missing)
        penalty = required * 5 + recommended * 2 + optional
        report.readiness = ReadinessReport(
            score=max(0, 100 - penalty), render_blocked=required > 0,
            required_missing_count=required, recommended_missing_count=recommended,
            optional_missing_count=optional,
            block_reasons=[g.reason or g.term or g.intent or g.id for g in report.missing if g.priority == RequirementPriority.REQUIRED],
        )

    def _result(self, project_id: str, resource_id: str, resource_type: str, status: str, affected: list[str], invalidated: list[str], action: str) -> ResourceResolutionResult:
        report = self.store.load_resource_report(project_id)
        return ResourceResolutionResult(
            project_id=project_id, resource_id=resource_id, resource_type=resource_type,
            resolution_status=status, updated_resource_report=self._public_report(report),
            remaining_required_gaps=[g.id for g in report.missing if g.priority == RequirementPriority.REQUIRED],
            remaining_recommended_gaps=[g.id for g in report.missing if g.priority == RequirementPriority.RECOMMENDED],
            affected_beats=affected, invalidated_artifacts=invalidated, suggested_action=action,
        )

    def _audit(self, project_id: str, revision_type: str, resource_id: str, affected: list[str], artifacts: list[str], steps: list[str], actor_id: str, reason: str | None, after: dict) -> None:
        self.revisions.append(DirectorRevisionEvent(
            revision_id=f"rev_{uuid.uuid4().hex[:12]}", project_id=project_id,
            beat_id=affected[0] if len(affected) == 1 else None, revision_type=revision_type,
            actor_id=actor_id, reason=reason, after={"resource_id": resource_id, **after},
            affected_artifacts=artifacts, required_reproduction_steps=steps,
            approval_required="final_approval" in artifacts,
        ))

    def add_pronunciation(self, project_id: str, term: str, phonetic: str, actor_id: str, reason: str | None = None) -> ResourceResolutionResult:
        self._require_project(project_id)
        if not term.strip() or not phonetic.strip():
            raise ValueError("term and phonetic must not be empty")
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan.")
        affected = [beat.id for beat in plan.beats if term.casefold() in beat.script.text.casefold()]
        if not affected:
            raise InvalidProjectStateError(f"Pronunciation term '{term}' does not occur in the source script.")
        for beat in plan.beats:
            if beat.id in affected:
                beat.voice.pronunciation[term] = phonetic
        self.store.save_voice_plan(project_id, plan)
        manifest = self.store.load_manifest(project_id)
        for beat_id in affected:
            if beat_id in manifest.beats:
                manifest.beats[beat_id].selected_attempt = None
                manifest.beats[beat_id].status = RenderStatus.PENDING
        self.store.save_manifest(project_id, manifest)
        self.project_service.check_resources(project_id)
        artifacts = ["selected_attempt", "beat_qc", *MIX_ARTIFACTS]
        steps = ["render_beat", "evaluate", "prepare_mix", "mix", "master", "export"]
        self._audit(project_id, "pronunciation_added", term, affected, artifacts, steps, actor_id, reason, {"phonetic": phonetic})
        return self._result(project_id, term, "pronunciation", "resolved", affected, artifacts, "Rerender affected beats, then rebuild downstream audio.")

    def bind_asset(self, project_id: str, resource_id: str, asset_id: str, actor_id: str, reason: str | None = None, allow_substitution: bool = True) -> ResourceResolutionResult:
        self._require_project(project_id)
        report = self.store.load_resource_report(project_id)
        if not report:
            raise InvalidProjectStateError(f"Project '{project_id}' has no ResourceReport.")
        gap = next((item for item in report.missing if item.id == resource_id), None)
        if not gap:
            raise InvalidProjectStateError(f"Unknown or already resolved resource '{resource_id}'.")
        asset = load_manifest().find_by_id(asset_id)
        if not asset:
            raise InvalidProjectStateError(f"Unknown asset '{asset_id}'.")
        if asset.category != gap.type:
            raise InvalidProjectStateError(f"Asset '{asset_id}' has category '{asset.category.value}', expected '{gap.type.value}'.")
        asset_path = resolve_asset_file_path(asset.file.path, project_dir=self.store.get_project_dir(project_id))
        if not asset_path.is_file():
            raise ValueError(f"Asset '{asset_id}' points to a nonexistent file.")
        is_substitute = gap.intent not in asset.intents
        if is_substitute:
            try:
                from services.voice_project_dependencies import get_voice_project_workflow_service
                workflow = next(
                    (item for item in get_voice_project_workflow_service().store.list_workflows(limit=200)
                     if item.project_id == project_id), None
                )
                if workflow and not workflow.policy.allow_resource_substitute:
                    allow_substitution = False
            except Exception:
                pass
        if is_substitute and not allow_substitution:
            raise InvalidProjectStateError("Resource substitution is not allowed by policy.")
        self._persist_override(project_id, resource_id, {"action": "bind", "asset_id": asset_id})
        report = self.project_service.check_resources(project_id).report
        affected = gap.used_at or ([gap.narrative_context.beat_id] if gap.narrative_context and gap.narrative_context.beat_id else [])
        steps = ["check_resources", "prepare_mix", "mix", "master", "export"]
        self._audit(project_id, "resource_bound", resource_id, affected, MIX_ARTIFACTS, steps, actor_id, reason, {"asset_id": asset_id, "substitution": is_substitute})
        return self._result(project_id, resource_id, gap.type.value, "substitute" if is_substitute else "resolved", affected, MIX_ARTIFACTS, "Rebuild mix and downstream artifacts.")

    def omit_optional(self, project_id: str, resource_id: str, actor_id: str, reason: str | None = None) -> ResourceResolutionResult:
        self._require_project(project_id)
        report = self.store.load_resource_report(project_id)
        if not report:
            raise InvalidProjectStateError(f"Project '{project_id}' has no ResourceReport.")
        gap = next((item for item in report.missing if item.id == resource_id), None)
        if not gap:
            raise InvalidProjectStateError(f"Unknown resource '{resource_id}'.")
        if gap.priority == RequirementPriority.REQUIRED:
            raise InvalidProjectStateError("REQUIRED resources cannot be omitted.")
        self._persist_override(project_id, resource_id, {"action": "omit"})
        report = self.project_service.check_resources(project_id).report
        affected = gap.used_at
        self._audit(project_id, "optional_resource_omitted", resource_id, affected, MIX_ARTIFACTS, ["prepare_mix", "mix", "master", "export"], actor_id, reason, {})
        return self._result(project_id, resource_id, gap.type.value, "omitted", affected, MIX_ARTIFACTS, "Rebuild mix if an earlier binding was replaced.")

    def register_asset(self, project_id: str, resource_id: str, file_path: str, category: str, intent: str, actor_id: str, reason: str | None = None) -> ResourceResolutionResult:
        self._require_project(project_id)
        source = Path(file_path).resolve()
        project_dir = self.store.get_project_dir(project_id).resolve()
        repo_assets = (Path(__file__).resolve().parent.parent / "assets").resolve()
        roots = [project_dir / "assets", repo_assets]
        env_root = os.getenv("CHATTERBOX_ASSETS_DIR")
        if env_root:
            roots.append(Path(env_root).resolve())
        if not source.is_file() or not any(source.is_relative_to(root) for root in roots):
            raise ValueError("Asset path must be an existing file inside an explicitly permitted asset root.")
        if source.suffix.lower() not in {".wav", ".mp3", ".flac"}:
            raise ValueError("Unsupported audio format; accepted formats are WAV, MP3, and FLAC.")
        gap_report = self.store.load_resource_report(project_id)
        gap = next((item for item in gap_report.missing if item.id == resource_id), None) if gap_report else None
        if not gap:
            raise InvalidProjectStateError(f"Unknown resource '{resource_id}'.")
        if ResourceCategory(category) != gap.type:
            raise InvalidProjectStateError("Registered asset category does not match requested resource type.")
        # Persist the registration in the project; the source remains in its permitted managed root.
        registry = project_dir / "director-resources.yaml"
        import yaml
        data = yaml.safe_load(registry.read_text(encoding="utf-8")) if registry.exists() else {"resources": []}
        asset_id = f"project_{project_id}_{uuid.uuid4().hex[:8]}"
        data["resources"].append({"id": asset_id, "path": str(source), "category": category, "intent": intent})
        pending = registry.with_suffix(".pending")
        try:
            pending.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            pending.replace(registry)
        finally:
            if pending.exists():
                pending.unlink()

        entry = ResourceEntry.model_validate({
            "id": asset_id, "file": {"path": str(source), "format": source.suffix.lstrip(".")},
            "category": category, "intents": [intent],
        })
        self._persist_override(project_id, resource_id, {
            "action": "register", "asset_id": asset_id, "resource": entry.model_dump(mode="json")
        })
        gap_report = self.project_service.check_resources(project_id).report
        affected = gap.used_at
        self._audit(project_id, "resource_registered", resource_id, affected, MIX_ARTIFACTS, ["prepare_mix", "mix", "master", "export"], actor_id, reason, {"asset_id": asset_id})
        return self._result(project_id, resource_id, category, "registered", affected, MIX_ARTIFACTS, "Rebuild mix and downstream artifacts.")
