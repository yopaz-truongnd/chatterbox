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

## Ownership Rules

- Audio tensors và signal QC thuộc `services/audio.py`.
- Whisper STT và Speech Content Critic thuộc `services/critic.py`.
- Narration Plan & Pronunciation Scanner thuộc `services/narration_planner.py`.
- Kịch bản & phân đoạn ngữ nghĩa thuộc `services/project_script.py`.
- Batch candidate generation & retry sequencing thuộc `services/batch_runner.py` và `inference_runner.py`.
- Worker state và technical events thuộc `services/job_manager.py`.
- Product state và confirmation gates thuộc `services/project_planner.py`.
- HTTP validation thuộc `routers/`.
- MCP chỉ đóng vai trò adapter chuyển đổi giao thức, định nghĩa schema trong `mcp_adapter/catalog.py`.

