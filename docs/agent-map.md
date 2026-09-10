# Chatterbox Agent Routing Map

Chọn đúng nhóm tính năng trước khi đọc code. Đọc primary files trước và chỉ mở secondary files khi thay đổi đi qua trách nhiệm của chúng.

## Product Planning & Narration Pipeline

Dùng cho topic, câu hỏi làm rõ (single batch), xác nhận yêu cầu (Gate 1), lập kịch bản & phân đoạn (Gate 2), phát âm riêng (Pronunciation Dict), kế hoạch diễn cảm (Narration Plan) và vòng đời dự án.

- Primary Services:
  - `services/project_planner.py` — State machine facade, quản lý Gate 1/Gate 2, JobManager sync.
  - `services/project_requirements.py` — Trích xuất heuristic yêu cầu, phân tích thiếu sót, tạo câu hỏi.
  - `services/project_script.py` — Sinh cấu trúc scene outline, kịch bản tiếng Anh, phân đoạn ngữ nghĩa (8-25s).
  - `services/narration_planner.py` — Quét từ cần xác nhận phát âm, áp dụng từ điển phiên âm, lập Narration Plan (role, emotion, energy, target WPM, dynamic pauses, emphasis, candidate strategy).
- REST API: `routers/projects.py`
- MCP Adapter:
  - `mcp_server.py` — JSON-RPC stdio server facade & HTTP dispatcher.
  - `mcp_adapter/catalog.py` — Tool schemas (16 tools).
  - `mcp_adapter/project_tools.py` — Handlers cho Project Planning, Pronunciation, Render và Event Stream.
  - `mcp_adapter/voice_tools.py` — Handlers cho Voice, TTS, Characters, Download và Audio Critic.
- Web UI: `webui/js/projects.js`
- Tests: `tests/test_project_workflow.py`, `tests/test_narration_plan.py`

## Voice Quality & Dual-Critic Pipeline

Dùng cho evaluate signal, Whisper ASR content critic, auto-fix, selective multi-candidate, adaptive retry, merge và publish.

1. `services/audio.py` — Signal evaluation (silence, RMS, clipping, duration, Crest factor) và signal auto-fix.
2. `services/critic.py` — ASR Speech Content Critic (`evaluate_speech_content`: Whisper transcribe, WER, missing words/dropped text detection, repetition/stutter detection, actual WPM measurement).
3. `services/batch_runner.py` — In-process batch sequencing, model-aware parameter stripping, selective 2-candidate generation cho dialogue/climax/pronunciation, ranking (60% Content + 40% Signal), adaptive retry.
4. `inference_runner.py` — Subprocess batch runner parity.
5. `services/job_manager.py` — Quản lý trạng thái tác vụ, phase (`evaluating`, `auto_fixing`, `re_evaluating`, `merging_audio`, `publishing`) và event.
6. `tests/test_audio_quality.py` — Test signal QC, auto-fix, resume và phase progress.
7. `tests/test_narration_plan.py` — Test Narration Plan, pronunciation dictionary, ASR content evaluation và candidate ranking.

Invariant xử lý segment:

```text
[Generate Candidate(s)] -> [Signal QC + Whisper ASR Content Critic]
                        -> [Signal Auto-Fix nếu fixable] -> [Re-evaluate]
                        -> [Nếu lỗi: Adaptive Retry với new seed/temperature (tối đa 2 lần)]
                        -> [Rank & Chọn candidate tốt nhất] -> [Merge passing chunks] -> [Publish]
```

## Events

- Primary: `services/event_bus.py`
- Producer: `services/job_manager.py`
- Project synchronization: `services/project_planner.py`
- REST API: `routers/events.py`
- MCP adapter: `mcp_adapter/project_tools.py::handle_get_events_stream`

`JobManager` sở hữu technical progress. Project planner chỉ đồng bộ product state và không phát lại terminal event đã có.

## TTS API

- Request validation: `routers/tts.py`
- Parameter normalization: `services/synthesis.py`
- Model catalog: `services/model_registry.py`
- Loaded model lifecycle: `services/model_runtime.py`
- Subprocess bridge: `services/inference.py`
- Character and reference voice: `character_api.py`
- Tests: `tests/test_api_app.py`, `tests/test_services_unified.py`, `tests/test_character_api.py`

## Batch Studio

- Primary: `services/batch_runner.py`
- Parsing: `services/script_parser.py`
- Audio assembly: `services/audio.py`
- Export: `services/batch_export.py`
- Job endpoints: `routers/jobs.py`
- Tests: `tests/test_batch_studio_advanced.py`

## UI Applications

- Material Web UI: `webui/`
- Desktop application: `apps/desktop.py`, `ui/`, `utils/`
- Gradio applications: `apps/gradio/`

## Resource Management & Pronunciation Knowledge (Phases 4-6)

Dùng cho asset manifest, resolution từ narrative intent sang local assets, candidate scoring, intent substitution graph, pronunciation verification cho proper nouns mythology, asset ingest và shopping list.

- Primary Services:
  - `services/resource_models.py` — Domain models cho Manifest, Requirements, Candidates, Resolutions, Gaps, Pronunciation, Reports.
  - `services/resource_manager.py` — Extract requirements từ Directed VoicePlan, scoring candidate (intent, intensity, duration, tags, usage), substitution graph, gap report & readiness calculation.
  - `services/pronunciation_knowledge.py` — Từ điển proper nouns, alias lookup, trạng thái kiểm duyệt (verified / unverified / rejected), phát hiện knowledge gap và tiêm pronunciation override vào VoiceDirection.
  - `services/asset_ingest.py` — Trích xuất thông tin tệp audio, nạp asset vào manifest, quản lý lịch sử sử dụng (usage tracking) và tổng hợp Resource Shopping List đa dự án.
  - `services/resource_doctor.py` — Chẩn đoán sức khỏe hệ thống tài nguyên, kiểm tra liên kết file, trùng lặp ID/path/hash và cảnh báo thiếu tag/intent.
- Configuration & Knowledge:
  - `assets/manifest.yaml` — Danh mục âm thanh mẫu (Ambience, SFX, Music).
  - `rules/resource-substitution.yaml` — Đồ thị thay thế ý định âm thanh (Sound Intent Substitution Graph).
  - `rules/resource-selection.yaml` — Trọng số chấm điểm, ngưỡng thay thế và chính sách chống lặp (Anti-repeat).
  - `knowledge/pronunciation.yaml` — Cơ sở tri thức phát âm thần thoại (Zhulong, Taotie, Qiongqi, Nuwa, Fuxi,...).
- Tests:
  - `tests/test_resource_manager.py`
  - `tests/test_pronunciation_knowledge.py`
  - `tests/test_asset_ingest.py`
  - `tests/test_resource_system_e2e.py`

## CLI Workflow, TTS Provider & Per-Beat Renderer, Voice QC (Phases 7-9)

Dùng cho CLI workspace orchestration, TTS provider abstraction (Fake & Gemini), per-beat audio rendering, Voice QC 3-layer (Signal, Content, Direction), deterministic retries, render manifest và candidate selection.

- Primary Services:
  - `services/render_models.py` — Domain models cho ProjectState, TTSRenderRequest, TTSRenderResult, RenderManifest, QC Results.
  - `services/tts/base.py`, `services/tts/fake.py`, `services/tts/gemini.py` — TTS Provider protocol và adapter (FakeTTSProvider offline test, GeminiTTSProvider centralized direction mapping).
  - `services/voice_renderer.py` — Per-beat renderer, render readiness gate, selective rerender, idempotency & resume.
  - `services/voice_qc.py` — 3-layer Voice QC (Signal: clipping/RMS/silence, Content: Whisper WER/omissions/proper noun risk, Direction: WPM/duration range), deterministic retry policy & candidate selection.
  - `services/voice_cli.py` — CLI Orchestrator (`voice new`, `inspect`, `plan`, `resources`, `resources missing`, `assets ingest`, `doctor`, `render`, `rerender`, `qc`).
  - `voice_cli.py` — Executable root CLI wrapper.
- Tests:
  - `tests/test_voice_cli.py`
  - `tests/test_voice_renderer.py`
  - `tests/test_voice_qc.py`
  - `tests/test_voice_pipeline_e2e.py`

## Voice Project Application Core & REST/MCP Interfaces (Phases 11-13)

Dùng cho VoiceProject application service, YAML workspace storage, background operations concurrency, strict resource gating, REST asynchronous endpoints, và MCP Agent tools.

- Primary Services:
  - `services/voice_project_service.py` — Unified application facade cho CLI, REST và MCP.
  - `services/voice_project_models.py` — Domain contracts, error taxonomy và lifecycle results.
  - `services/voice_project_store.py` — Atomic YAML storage và staleness invalidation.
  - `services/voice_project_operations.py` — Background operations manager, YAML persistence, cancel & recovery.
  - `services/voice_project_preflight.py` — Synchronous preflight validation (fail-fast trước 202).
  - `services/voice_project_dependencies.py` — Dependency injection và strict TTS provider resolution.
- REST API: `routers/voice_projects.py`
- MCP Adapter:
  - `mcp_adapter/voice_project_tools.py` — MCP handlers chuyển tiếp qua REST API layer.
  - `mcp_adapter/catalog.py` — Tool schemas (35 tools).
- Tests:
  - `tests/test_voice_projects_api.py`
  - `tests/test_voice_project_mcp.py`
  - `tests/test_voice_project_cross_parity.py`
  - `tests/test_voice_project_cancellation.py`
  - `tests/test_voice_project_provider.py`
  - `tests/test_voice_preflight.py`

## Audio Mix, Master, Export & Autonomous Workflow (Phases 14-15)

Dùng cho multi-track timeline construction (MixPlan), pure Python WAV mixing & crossfade, dynamics mastering (LUFS loudness & true peak limiter), deliverable export (FINAL.wav, export-manifest.yaml), và autonomous workflow orchestration loop (`produce`, pause at human action gates, resume, cancel).

- Primary Services:
  - `services/audio_mix_models.py` — Domain models cho MixPlan, VoiceClip, AmbienceClip, SFXClip, MasteringProfile, ExportManifest.
  - `services/mix_plan_builder.py` — Xây dựng multi-track timeline từ real audio durations và beat pauses.
  - `services/audio_mix_execution.py` — Universal mixing execution protocol.
  - `services/wave_audio_mixer.py` — Pure Python 16-bit PCM WAV multi-track mixer.
  - `services/audio_mastering.py` — Pure Python LUFS loudness normalizer và soft-knee peak limiter.
  - `services/audio_export.py` — Package deliverable audio và tính toán SHA-256 manifest.
  - `services/voice_project_workflow_models.py` — Workflow state machine và step models.
  - `services/voice_project_workflow_store.py` — YAML persistence cho workflows.
  - `services/voice_project_workflow.py` — Multi-step autonomous orchestrator loop.
- REST API: `routers/voice_workflows.py`
- Configuration: `rules/mixing.yaml`, `rules/mastering.yaml`
- Tests:
  - `tests/test_mix_plan_builder.py`
  - `tests/test_wave_audio_mixer.py`
  - `tests/test_audio_mastering.py`
  - `tests/test_audio_export.py`
  - `tests/test_voice_workflow.py`

## Director Review, Resource Resolution & Incremental Reproduction (Phase 16)

Dùng cho director snapshot, resource shopping list/binding, beat candidate approval,
direction/timing/resource revisions, persisted audit trail và minimum-safe reproduction.

- Primary Services:
  - `services/director_review_models.py` — Typed public/application contracts cho review, gaps, candidates và impacts.
  - `services/director_review_service.py` — Read model tổng hợp từ immutable source, VoicePlan, ResourceReport và RenderManifest.
  - `services/director_resource_service.py` — Pronunciation overrides, managed asset registration/binding và omission policy.
  - `services/director_revision_service.py` — Candidate decisions, constrained beat patches và incremental reproduction.
  - `services/director_revision_store.py` — Atomic `revision-history.yaml` và explicit `revision-state.yaml`.
  - `services/resource_manager.py::apply_project_resource_overrides` — Reapply persisted project decisions on every canonical resource check.
- REST API: `routers/voice_projects.py` (`/director-review`, `/resource-shopping-list`, beat revisions, `/reproduce`).
- MCP Adapter: `mcp_adapter/voice_project_tools.py`, schemas in `mcp_adapter/catalog.py`.
- CLI: `services/voice_cli.py` Phase 16 commands use REST and never instantiate server inference.
- Tests: `tests/test_director_phase16.py` plus existing Phase 11-15 regression suites.

## Ownership Rules

- `services/project_requirements.py` sở hữu heuristic trích xuất và câu hỏi làm rõ.
- `services/project_script.py` sở hữu script outline và phân đoạn ngữ nghĩa.
- `services/narration_planner.py` sở hữu việc phát hiện phát âm và gán thông số Narration Plan.
- `services/voice_plan.py` sở hữu schema hợp đồng VoicePlan và khả năng tương thích ngược.
- `services/story_analyzer.py` sở hữu phân tích kịch bản thành StoryBeat và gán role.
- `services/sound_director.py` sở hữu đạo diễn âm thanh (Ambience, SFX, Silence) theo mạch kịch bản.
- `services/director_critic.py` sở hữu kiểm duyệt và tự động sửa xung đột âm thanh.
- `services/resource_manager.py` sở hữu việc trích xuất yêu cầu tài nguyên, tính điểm chấm chọn và đồ thị thay thế.
- `services/pronunciation_knowledge.py` sở hữu cơ sở tri thức phát âm tên riêng thần thoại.
- `services/asset_ingest.py` & `services/resource_doctor.py` sở hữu nạp tài nguyên và chẩn đoán thư viện.
- `services/voice_renderer.py` & `services/tts/` sở hữu render voice narration theo từng beat.
- `services/voice_qc.py` sở hữu kiểm định chất lượng âm thanh 3 lớp và chính sách retry.
- `services/voice_cli.py` sở hữu giao diện dòng lệnh orchestration layer.
- `services/voice_project_service.py` sở hữu business logic cốt lõi của Voice Projects.
- `services/mix_plan_builder.py`, `services/wave_audio_mixer.py`, `services/audio_mastering.py`, `services/audio_export.py` sở hữu hậu kỳ âm thanh (Mix/Master/Export).
- `services/voice_project_workflow.py` sở hữu điều phối quy trình tự động từ kịch bản đến sản phẩm cuối cùng.
- `JobManager` sở hữu tiến trình kỹ thuật chạy inference TTS và phát sinh sự kiện `EventBus`.
- Các router `routers/`, adapter MCP `mcp_adapter/`, UI `webui/` và CLI `services/voice_cli.py` tuyệt đối không chứa business logic; chỉ đóng vai trò validate, chuyển đổi hoặc hiển thị dữ liệu.
- Product state và confirmation gates thuộc `services/project_planner.py`.
- HTTP validation thuộc `routers/`.
- MCP chỉ đóng vai trò adapter chuyển đổi giao thức, định nghĩa schema trong `mcp_adapter/catalog.py`.

## Production Runtime Validation (Phase 17)

Kiểm tra in-process local runtime capabilities và preflight validation trước khi production.

- Primary Services:
  - `services/local_runtime_models.py` — `LocalRuntimeCapabilities`, `PreflightIssue` data contracts.
  - `services/local_runtime_service.py` — `get_capabilities()` (model cache, device, formats), `run_production_preflight()` (ffmpeg check, disk space, model readiness). Zero HTTP loopback.
- REST API: `routers/voice_runtime.py` (`GET /api/v1/voice-runtime/capabilities`, `POST /api/v1/voice-runtime/preflight/{project_id}`).
- MCP Adapter: `mcp_adapter/runtime_tools.py` → `chatterbox_voice_runtime_capabilities`, `chatterbox_voice_runtime_preflight`.
- Tests: `tests/test_local_runtime_capabilities.py`, `tests/test_voice_production_preflight.py`.

## Intelligent Asset Library (Phase 18)

Librarian service for ingesting, indexing, semantic matching and security-validating sound assets.

- Primary Services:
  - `services/asset_library_models.py` — `LibraryAsset`, `AssetCategory`, `AssetMatchResult`.
  - `services/asset_library_store.py` — Persistent `library-index.yaml`, atomic CRUD.
  - `services/asset_library_service.py` — Ingest with path-traversal security guard, symlink resolution.
  - `services/asset_matching_service.py` — Semantic scoring (intent overlap, mood, energy, duration).
- REST API: `routers/voice_assets.py` (`GET /api/v1/voice-assets`, `POST /register`, `POST /scan`, `POST /match`, `GET /{id}/preview`).
- MCP Adapter: `mcp_adapter/asset_tools.py` → `chatterbox_voice_asset*` tools via `handle_asset_tool()`.
- Tests: `tests/test_asset_library.py`, `tests/test_asset_matching.py`, `tests/test_asset_security.py`.

## Story Series & Batch Production (Phase 19)

Multi-episode production with shared Voice, Pronunciation and Sound bibles; concurrent batch execution.

- Primary Services:
  - `services/voice_series_models.py` — `VoiceSeries`, `VoiceSeriesEpisode`, `SeriesVoiceBible`, `SeriesPronunciationBible`, `SeriesSoundBible`, `SeriesProductionSummary`.
  - `services/voice_series_store.py` — `projects/series/{series_id}/series.yaml` and `episodes/{episode_id}.yaml`.
  - `services/voice_series_service.py` — Series/episode CRUD, completed episode invariant guard.
  - `services/voice_series_operations.py` — Concurrent batch execution, cancellation token, deliverable export packaging (`exports/` fallback `output/`).
- REST API: `routers/voice_series.py` (`POST /api/v1/voice-series`, `GET /{id}`, episodes, produce, status, review-queue, cancel).
- MCP Adapter: `mcp_adapter/series_tools.py` → `chatterbox_voice_series_*` tools.
- Tests: `tests/test_voice_series_models.py`, `tests/test_voice_series_service.py`, `tests/test_voice_series_operations.py`, `tests/test_voice_series_recovery.py`.

## Observability, Recovery & Release Readiness (Phase 20)

Structured audit events, health aggregation, sanitized diagnostics bundles for production observability.

- Primary Services:
  - `services/production_event_models.py` — `ProductionEvent`, `ProductionEventType`, `ProductionErrorCode`, `ProjectProductionHealth`, `SeriesProductionHealth`.
  - `services/production_event_store.py` — Append-only `events.jsonl` per project/series (fcntl-locked, corruption-tolerant, auto-rotating at 1000 events).
  - `services/production_health_service.py` — `get_project_health()`, `get_series_health()`: aggregate state + artifact freshness + active operations + runtime health.
  - `services/diagnostics_service.py` — `create_project_diagnostics()`, `create_series_diagnostics()`: sanitize paths, redact secrets, bundle runtime caps + health + events.
- REST API: `routers/voice_health.py` (`GET /api/v1/voice-projects/{id}/health`, `/events`, `POST /diagnostics`; equivalent series endpoints).
- MCP Adapter: `mcp_adapter/health_tools.py` → `chatterbox_voice_health`, `chatterbox_voice_events`, `chatterbox_voice_diagnostics`, `chatterbox_voice_series_health`, `chatterbox_voice_series_events`.
- Tests: `tests/test_production_events.py`, `tests/test_production_health.py`, `tests/test_diagnostics_bundle.py`.
- Cross-Phase Integration: `tests/test_phase17_20_rest.py`, `tests/test_phase17_20_mcp.py`, `tests/test_phase17_20_cross_parity.py`, `tests/test_phase17_20_e2e.py`.
