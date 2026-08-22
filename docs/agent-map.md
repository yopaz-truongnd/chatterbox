# Chatterbox Agent Routing Map

Chọn đúng nhóm tính năng trước khi đọc code. Đọc primary files trước và chỉ mở secondary files khi thay đổi đi qua trách nhiệm của chúng.

## Product planning flow

Dùng cho topic, câu hỏi bổ sung, xác nhận yêu cầu, xác nhận script, segmentation và project lifecycle.

- Primary: `services/project_planner.py`
- REST API: `routers/projects.py`
- MCP adapter: `mcp_server.py`
- Web UI: `webui/js/projects.js`
- Tests: `tests/test_project_workflow.py`

## Voice quality pipeline

Dùng cho evaluate, trim silence, normalize, auto-fix, re-evaluate, merge và publish.

1. `services/audio.py` — signal evaluation và audio transformations.
2. `services/batch_runner.py` — in-process batch sequencing.
3. `inference_runner.py` — chỉ đọc khi thay đổi phải chạy qua subprocess.
4. `services/job_manager.py` — chỉ đọc khi thay đổi job status, phase hoặc event.
5. `services/project_planner.py::sync_project_with_job` — chỉ đọc khi public project state thay đổi.
6. `tests/test_project_workflow.py` và `tests/test_batch_studio_advanced.py` — regression tests.

Invariant:

```text
generate -> evaluate -> auto-fix once -> re-evaluate
         -> merge passing chunks -> publish
```

Không sao chép quality rules ra ngoài `services/audio.py`.

## Events

- Primary: `services/event_bus.py`
- Producer: `services/job_manager.py`
- Project synchronization: `services/project_planner.py`
- REST API: `routers/events.py`
- MCP adapter: `mcp_server.py::chatterbox_get_events`

`JobManager` sở hữu technical progress. Project planner chỉ đồng bộ product state và không nên phát lại terminal event đã có.

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

## UI applications

- Material Web UI: `webui/`
- Desktop application: `apps/desktop.py`, `ui/`, `utils/`
- Gradio applications: `apps/gradio/`

Không mở cả ba UI stack nếu task chỉ liên quan một stack.

## Ownership rules

- Audio tensors và signal QC thuộc `services/audio.py`.
- Batch sequencing thuộc `services/batch_runner.py`.
- Worker state và technical events thuộc `services/job_manager.py`.
- Product state và confirmation gates thuộc `services/project_planner.py`.
- HTTP validation thuộc `routers/`.
- MCP chỉ chuyển request/response, không chứa business logic.
- UI không tự triển khai lại state machine của backend.
