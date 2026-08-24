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
- `JobManager` sở hữu tiến trình kỹ thuật chạy inference TTS và phát sinh sự kiện `EventBus`.
- Các router `routers/`, adapter MCP `mcp_adapter/`, UI `webui/` và CLI `services/voice_cli.py` tuyệt đối không chứa business logic; chỉ đóng vai trò validate, chuyển đổi hoặc hiển thị dữ liệu.
- Product state và confirmation gates thuộc `services/project_planner.py`.
- HTTP validation thuộc `routers/`.
- MCP chỉ đóng vai trò adapter chuyển đổi giao thức, định nghĩa schema trong `mcp_adapter/catalog.py`.
