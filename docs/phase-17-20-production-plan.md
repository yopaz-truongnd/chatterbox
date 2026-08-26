# Phase 17–20 Production Plan

Tracking document for the combined production-readiness PR.

## Scope

- Repository: `yopaz-truongnd/chatterbox`
- Base: latest approved and merged Phase 16 commit
- Proposed branch: `feature/mythology-voice-director-phase-17-20-production`
- PR strategy: one PR, commits split by phase
- Browser UI: out of scope
- New QC engine: out of scope
- Alternative operation manager: out of scope unless an architectural need is demonstrated
- Provider fallback from local to Gemini or FakeTTSProvider: forbidden

## Status

Use one status per item: `TODO`, `IN PROGRESS`, `BLOCKED`, or `DONE`.

| Gate | Status | Notes |
|---|---|---|
| Phase 16 fixes verified | DONE | Revision, approval, invalidation, and reproduction regressions are covered |
| Phase 17 complete | DONE | In-process runtime capabilities and fail-fast production preflight implemented |
| Phase 18 complete | DONE | Secure reusable asset catalog, matching, usage, and export attribution implemented |
| Phase 19 complete | DONE | Persisted series operations, episode snapshots, bounded batch production, and gates implemented |
| Phase 20 complete | DONE | Structured events, recovery, health, diagnostics, and concurrent persistence implemented |
| Phase 1–20 regression green | DONE | `417 passed, 1 skipped` on 2026-08-26 |
| Real local production smoke test passed | TODO | Opt-in when runtime is available |

### Review remediation status

The production-readiness review findings are closed in the current branch:

- [x] Series preflight runs before operation scheduling and returns structured errors.
- [x] Reference voice, pronunciation, mixing/mastering profiles, output formats, loudness, and series sound palettes reach their authoritative runtime stages.
- [x] Palette mismatches become resource gaps before render instead of late MixPlan failures.
- [x] Each episode uses its creation-time production snapshot; later series-default changes do not rewrite pending, retry, or completed episodes.
- [x] Completed episodes are skipped by production preflight.
- [x] Series subset totals and progress are aggregated from the selected episodes.
- [x] All asset-index mutations share process and file locks.
- [x] Workflow cancellation events are emitted only after terminal `CANCELLED` state.
- [x] Workflow start, step, approval, failure, cancellation, and export events are persisted.

## Target production flow

```text
story or series
  -> analyze and plan episodes
  -> generate resource shopping list
  -> reuse or add pronunciation/SFX/ambience assets
  -> render through local Chatterbox
  -> QC and retry
  -> request human review only when required
  -> incrementally mix, master, and export
  -> organize episode deliverables
  -> resume safely after cancellation or restart
```

## Gate 0 — Phase 16 prerequisite

No Phase 17–20 implementation starts until every item below has a regression test.

- [ ] Request policy cannot weaken the workflow final-approval policy.
- [ ] Incremental reproduction persists an approval gate with workflow/revision state, `artifact_id`, `artifact_sha256`, `human_action`, an approval interface, and resumable export.
- [ ] `_preserve_narration()` never overwrites `RESOURCE_BLOCKED`.
- [ ] Revision events persist every affected beat.
- [ ] Selective reproduction resolves only selected revision IDs.
- [ ] Reproduction preserves provider, mixing profile, mastering profile, output formats, resource substitution policy, and approval policy.
- [ ] Export invalidation marks `FINAL.wav`, `FINAL.mp3`, and `export-manifest.yaml` stale.
- [ ] Targeted Phase 16 tests pass.
- [ ] Existing Phase 1–16 regression suites pass.
- [ ] PR #16 is approved and merged.

Exit criterion: the Phase 17–20 branch is based on the approved Phase 16 result, not commit `332d25e`.

## Phase 17 — Production Runtime Validation

Objective: validate the complete production flow with the real in-process local Chatterbox runtime.

### Runtime integration

- [ ] Keep `local` as the default provider.
- [ ] Route in-server execution through `ChatterboxJobProvider -> JobExecutionGateway -> JobManager`.
- [ ] Ensure server services never use localhost HTTP loopback.
- [ ] Keep CLI access through the external REST API.
- [ ] Prevent Voice Director services from loading models directly.

### Runtime capabilities

- [ ] Add typed `LocalRuntimeCapabilities`.
- [ ] Report availability, loaded/cached models, languages, voice modes, device, memory estimate, concurrency, output formats, and warnings.
- [ ] Add `GET /api/v1/voice-runtime/capabilities`.
- [ ] Add MCP tool `chatterbox_voice_runtime_capabilities`.

### Production preflight

- [ ] Validate selected local model availability.
- [ ] Validate character/reference voice availability.
- [ ] Validate free disk space.
- [ ] Validate model cache availability/loadability.
- [ ] Require FFmpeg when MP3 is requested.
- [ ] Validate readable asset roots and writable output directory.
- [ ] Validate that the runtime is accepting jobs.
- [ ] Return structured errors before scheduling a background operation.

### Real-runtime smoke test

- [ ] Add an opt-in local-runtime integration marker.
- [ ] Skip cleanly when the local model is unavailable.
- [ ] Produce VoicePlan and ResourceReport.
- [ ] Produce selected narration attempts and complete QC/retry results.
- [ ] Produce MixPlan, `premaster.wav`, and `master.wav`.
- [ ] Exercise final approval.
- [ ] Produce `FINAL.wav`, optional `FINAL.mp3`, and `export-manifest.yaml`.
- [ ] Verify revision history and complete artifact lineage.

Exit criterion: one real local story completes the create-to-export flow without HTTP loopback or silent provider fallback.

## Phase 18 — Intelligent Asset Library

Objective: reuse local ambience, SFX, voice references, and pronunciation references across projects.

### Shared services and storage

- [ ] Add typed asset library models.
- [ ] Add atomic project-independent asset library storage at `assets/library-index.yaml`.
- [ ] Add shared asset library and matching services.
- [ ] Keep all business logic out of REST, MCP, and CLI adapters.
- [ ] Store identity, audio metadata, semantic metadata, licensing, timestamps, usage, and enabled state.

### Secure ingest

- [ ] Support WAV, MP3, and FLAC.
- [ ] Validate permitted root and reject traversal, absolute-path escape, and symlink escape.
- [ ] Validate real file type and readable audio instead of trusting extensions.
- [ ] Read duration, sample rate, channels, and SHA-256.
- [ ] Validate category and license metadata.
- [ ] Return the existing asset when SHA-256 content is already registered.

### Matching and binding

- [ ] Rank by intents, keywords, mood, environment, story context, duration, loop requirement, and category.
- [ ] Return score, reasons, exact/substitute classification, license, and preview artifact.
- [ ] Never silently bind a substitute.
- [ ] Require explicit approval for REQUIRED substitutions.
- [ ] Record usage count plus project and beat references.
- [ ] Preserve attribution and license in export manifests.
- [ ] Track source SHA-256 in MixPlan lineage.
- [ ] Avoid unnecessary source-file copies.

### Shopping-list integration

- [ ] Include suggested local matches and search queries.
- [ ] Include duration, mood, environment, loopability, accepted formats, and substitution options.

### Interfaces

- [ ] REST: list, get, register, scan, match, disable, and preview assets.
- [ ] MCP: assets, register, scan, match, and preview tools.
- [ ] CLI: `voice assets list|scan|register|match`.

Exit criterion: a missing resource can be securely matched or registered once, explicitly approved when required, reused, and traced into the export manifest.

## Phase 19 — Story Series & Batch Production

Objective: produce connected episodes while preserving narration, pronunciation, sound, and mastering consistency.

### Models and persistence

- [ ] Add `VoiceSeries`, `VoiceSeriesEpisode`, `SeriesVoiceBible`, `SeriesPronunciationBible`, `SeriesSoundBible`, `SeriesProductionPolicy`, and `SeriesProductionSummary`.
- [ ] Add atomic series store, service, and series operation coordinator.
- [ ] Persist series identity, episode ordering, bibles, policy, status, and timestamps.
- [ ] Persist episode project/workflow linkage, status, duration, artifacts, gaps, review state, and publication time.

### Consistency rules

- [ ] Inherit narrator reference, provider, model, language, and voice style.
- [ ] Inherit pronunciation overrides and recurring character pronunciations.
- [ ] Inherit common ambience and SFX palettes.
- [ ] Inherit mastering profile, loudness target, and output formats.
- [ ] Snapshot inherited settings per episode.
- [ ] Never silently rewrite completed episodes when series defaults change.

### Batch production

- [ ] Implement `produce_series(series_id, episode_ids=None)`.
- [ ] Enforce configurable bounded parallelism across episodes.
- [ ] Serialize operations within each project.
- [ ] Allow independent episodes to continue when policy permits.
- [ ] Pause affected episodes on REQUIRED resource gaps.
- [ ] Expose series and episode progress.
- [ ] Support cooperative cancellation and restart recovery.
- [ ] Return a structured batch result with counts, progress, episode results, human actions, and suggested action.

### Human review queue

- [ ] Keep unrelated human actions as separate queue entries.
- [ ] Include episode/project identity, action type, reason, items, options, artifact ID, and artifact SHA-256.

### Interfaces

- [ ] REST: series CRUD subset, episode management, produce, cancel, review queue, and artifacts.
- [ ] MCP: create, get, add episode, produce, status, review queue, and cancel.
- [ ] CLI: `voice series create|add-episode|produce|status|review|cancel`.

### Deliverables

- [ ] Normalize safe series slugs and reject path traversal.
- [ ] Write `series-manifest.yaml`, voice bible, and pronunciation bible.
- [ ] Write numbered episode directories with current `FINAL.wav`, optional `FINAL.mp3`, and export manifest.

Exit criterion: multiple episodes can run with bounded concurrency, consistent production settings, isolated failures, explicit review queues, and safe organized exports.

## Phase 20 — Observability, Recovery & Release Readiness

Objective: make long-running production diagnosable, resumable, and safe.

### Structured events

- [ ] Add typed workflow, step, resource, review, retry, mix, master, approval, export, cancellation, and recovery events.
- [ ] Include IDs, UTC timestamp, scope IDs, operation/step, progress, status, message, and details.
- [ ] Sanitize secrets, private absolute paths, and full source scripts.
- [ ] Persist append-only project and series logs with atomic append and concurrent-writer protection.
- [ ] Add bounded retention or rotation.
- [ ] Load logs safely and tolerate corrupt records.

### Health aggregation

- [ ] Add typed project and series production health.
- [ ] Aggregate current step, progress, active operation, last successful step/error, human actions, freshness, runtime health, and suggested action.

### Recovery

- [ ] Recover queued, running, and cancelling operations at startup.
- [ ] Clean orphaned pending audio while preserving published artifacts.
- [ ] Validate lineage and mark inconsistent artifacts stale.
- [ ] Preserve human approval gates without continuing them.
- [ ] Never approve `NEEDS_REVIEW` automatically.
- [ ] Retry explicitly from the last safe step.
- [ ] Never rerun completed steps silently.

### Stable failure categories

- [ ] Use `VALIDATION_ERROR`, `PROJECT_NOT_FOUND`, `SERIES_NOT_FOUND`, `RESOURCE_BLOCKED`, `PROVIDER_UNAVAILABLE`, `MODEL_UNAVAILABLE`, `QC_REVIEW_REQUIRED`, `STALE_ARTIFACT`, `APPROVAL_REQUIRED`, `EXPORT_DEPENDENCY_UNAVAILABLE`, `OPERATION_CONFLICT`, `CANCELLED`, and `INTERNAL_ERROR`.

### Diagnostics bundle

- [ ] Support project- or series-scoped diagnostics creation.
- [ ] Include sanitized state, workflow, operations, resource report, artifact metadata, lineage results, recent events, runtime capabilities, and error summary.
- [ ] Exclude keys, secrets, full private paths, source audio, and model weights.
- [ ] Return operation IDs for long-running MCP diagnostics without indefinite polling.

### Interfaces

- [ ] REST: project health, events, and diagnostics.
- [ ] REST: series health, events, and diagnostics.
- [ ] MCP: project health/events/diagnostics and series health/events.

Exit criterion: interrupted production can be inspected and explicitly recovered from its last safe step without losing gates, overwriting fresh state, or publishing stale/cancelled output.

## Cross-phase operation and security gates

- [ ] Reuse the existing operation manager or justify a compatible series coordinator.
- [ ] Persist operation state and progress callbacks.
- [ ] Support cooperative cancellation.
- [ ] Enforce one active mutation per project.
- [ ] Enforce bounded series concurrency.
- [ ] Prevent stale-state overwrite and publish-after-cancellation.
- [ ] Prevent silent fallback and server-side HTTP loopback.
- [ ] Validate project, series, episode, asset, and operation ownership IDs.
- [ ] Validate formats, categories, file paths, output paths, and download boundaries.
- [ ] Reject traversal, root escape, symlink escape, arbitrary server-file registration, and duplicate poisoning.
- [ ] Use safe YAML loading only.

## Test matrix

Planned test groups:

- [ ] `tests/test_local_runtime_capabilities.py`
- [ ] `tests/test_voice_production_preflight.py`
- [ ] `tests/test_asset_library.py`
- [ ] `tests/test_asset_matching.py`
- [ ] `tests/test_asset_security.py`
- [ ] `tests/test_voice_series_models.py`
- [ ] `tests/test_voice_series_service.py`
- [ ] `tests/test_voice_series_operations.py`
- [ ] `tests/test_voice_series_recovery.py`
- [ ] `tests/test_production_events.py`
- [ ] `tests/test_production_health.py`
- [ ] `tests/test_diagnostics_bundle.py`
- [ ] `tests/test_phase17_20_rest.py`
- [ ] `tests/test_phase17_20_mcp.py`
- [ ] `tests/test_phase17_20_cross_parity.py`
- [ ] `tests/test_phase17_20_e2e.py`

Mandatory scenarios:

- [ ] 1. Local runtime is the default provider.
- [ ] 2. Server-side local execution never calls localhost HTTP.
- [ ] 3. Missing local model fails preflight before scheduling.
- [ ] 4. MP3 request fails preflight when FFmpeg is unavailable.
- [ ] 5. Duplicate assets are detected by SHA-256.
- [ ] 6. Asset path traversal is rejected.
- [ ] 7. Symlink escape is rejected.
- [ ] 8. REQUIRED substitution needs explicit approval.
- [ ] 9. Asset license and attribution reach the export manifest.
- [ ] 10. Series voice and pronunciation settings are inherited.
- [ ] 11. Updating series defaults does not mutate completed episodes.
- [ ] 12. Batch production respects its concurrency limit.
- [ ] 13. One episode failure does not corrupt another episode.
- [ ] 14. Cancellation does not publish pending audio.
- [ ] 15. Restart recovery preserves human gates.
- [ ] 16. Restart recovery does not silently rerun completed steps.
- [ ] 17. Series progress is aggregated correctly.
- [ ] 18. Review queue includes artifact SHA-256 for approval.
- [ ] 19. Diagnostics contain no secrets or absolute paths.
- [ ] 20. REST and MCP produce equivalent business outcomes.
- [ ] 21. `FINAL.wav` and `FINAL.mp3` match current artifact lineage.
- [ ] 22. Existing Phase 1–16 regression suites remain green.

## Proposed commit sequence

1. `fix(phase-16): close revision and approval invariants`
2. `feat(phase-17): validate real local production runtime`
3. `feat(phase-18): add reusable intelligent asset library`
4. `feat(phase-19): add story series and batch production`
5. `feat(phase-20): add production events recovery and diagnostics`
6. `test(phase-17-20): add integration and regression coverage`
7. `docs: update agent map and production workflow`

Each commit must leave its targeted tests green. Do not create commits until explicitly requested.

## Definition of Done

- [ ] A real local Chatterbox story is produced end to end.
- [ ] Missing assets can be searched, registered, and reused.
- [ ] Multiple connected episodes can be produced as a series.
- [ ] Narrator, pronunciation, and sound style remain consistent.
- [ ] Batch production supports progress, cancellation, and recovery.
- [ ] Human approval cannot be bypassed.
- [ ] Incremental revisions preserve original production profiles.
- [ ] Every final artifact has valid dependency lineage.
- [ ] Health, events, and diagnostics explain production failures.
- [ ] REST, MCP, and CLI remain thin interfaces over shared services.
- [ ] All Phase 1–20 tests pass.

## Progress log

Add dated entries as work proceeds; keep decisions and blockers concise.

| Date (UTC) | Phase | Status | Change / Decision | Verification |
|---|---|---|---|---|
| 2026-08-26 | 16–20 | DONE | Closed production runtime, revision, series policy, asset lineage, concurrency, recovery, and observability review findings. Commits: `4a56c7d`, `fd6a175`; final remediation pending this documentation commit. | Targeted regression groups green; full suite `417 passed, 1 skipped`. Real-model smoke remains opt-in. |
