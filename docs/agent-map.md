# Chatterbox Agent Routing Map & Navigation Matrix

> **DÀNH CHO AI ASSISTANT**:
> Trước khi đọc hoặc sửa bất kỳ mã nguồn nào, hãy **tra cứu Bảng Ma trận Tính năng** ở mục 1 dưới đây để xác định chính xác 100% các file cần mở.
> **TUYỆT ĐỐI KHÔNG** nạp toàn bộ dự án hoặc đọc lan man các file không liên quan.
> Tuân thủ các quy tắc kiến trúc bất biến trong [docs/invariants.md](file:///e:/Project/chatterbox/docs/invariants.md).

---

## 1. Bảng Ma trận Tra cứu Nhanh (Feature-to-File Fast Lookup Matrix)

Tra cứu mục tiêu của người dùng trong bảng này để đến thẳng các file cần sửa:

| Nhóm tính năng | Từ khóa thường gặp | Service cốt lõi (`services/`) | Router REST (`routers/`) | Giao diện Web (`webui/`) | Công cụ MCP (`mcp_adapter/`) | Tài liệu Domain | File Test tương ứng |
|---|---|---|---|---|---|---|---|
| **TTS Đơn lẻ** | `tts`, `synthesize`, `seed`, `temperature`, `exaggeration` | `synthesis.py`, `model_runtime.py`, `inference.py` | `tts.py` | `js/tts.js` | `voice_tools.py` | [Domain 01](file:///e:/Project/chatterbox/docs/domains/01-tts-and-models.md) | `tests/test_api_app.py` |
| **Nhân vật & Clone** | `character`, `voice_clone`, `reference_audio` | `character_api.py`, `synthesis.py` | `character_api.py` | `js/characters.js`, `js/vc.js` | `voice_tools.py` | [Domain 01](file:///e:/Project/chatterbox/docs/domains/01-tts-and-models.md) | `tests/test_character_api.py` |
| **Đa ngôn ngữ** | `multilingual`, `mtl`, `translate` | `synthesis.py`, `model_registry.py` | `tts.py` | `js/multilingual.js` | `voice_tools.py` | [Domain 01](file:///e:/Project/chatterbox/docs/domains/01-tts-and-models.md) | `tests/test_api_app.py` |
| **Batch Studio & SRT** | `batch`, `script_parser`, `pause_duration`, `srt` | `batch_runner.py`, `script_parser.py`, `batch_export.py` | `jobs.py` | `js/batch.js` | `project_tools.py` | [Domain 02](file:///e:/Project/chatterbox/docs/domains/02-batch-and-qc.md) | `tests/test_batch_studio_advanced.py` |
| **Đánh giá Âm thanh (QC)** | `evaluator`, `critic`, `whisper`, `wer`, `wpm` | `audio.py`, `critic.py`, `audio_candidate_evaluator.py`, `voice_qc.py` | `critic.py` | — | `voice_tools.py` | [Domain 02](file:///e:/Project/chatterbox/docs/domains/02-batch-and-qc.md) | `tests/test_audio_quality.py` |
| **Tự động sửa (Auto-Fix)** | `auto_fix`, `trim_silence`, `normalize_rms`, `limiter` | `audio.py`, `audio_candidate_evaluator.py` | `critic.py` | — | `voice_tools.py` | [Domain 02](file:///e:/Project/chatterbox/docs/domains/02-batch-and-qc.md) | `tests/test_audio_quality.py` |
| **Sự kiện & Thông báo** | `notifications`, `notifications_active`, `events`, `long_polling` | `event_bus.py`, `job_manager.py` | `events.py` | `js/notifications.js` | `project_tools.py` | [Domain 05](file:///e:/Project/chatterbox/docs/domains/05-events-and-observability.md) | `tests/test_project_workflow.py` |
| **Voice Director (25 Steps)** | `director`, `beats`, `voice_plan`, `story_analyzer`, `reproduce` | `voice_project_service.py`, `voice_project_workflow.py`, `story_analyzer.py` | `voice_projects.py`, `voice_workflows.py` | `js/director-console.js` | `voice_project_tools.py` | [Domain 03](file:///e:/Project/chatterbox/docs/domains/03-voice-director-workflow.md) | `tests/test_voice_orchestration_phase24.py` |
| **Sinh kịch bản từ ý tưởng (Idea-to-Script)** | `prepare_project`, `two-gate`, `outline`, `confirm_requirements`, `confirm_script` | `project_planner.py` | `projects.py` | `js/director-console.js` (chế độ "Tạo từ ý tưởng" trong panel tạo bản thu của Director Console) | `project_tools.py` | [Domain 03](file:///e:/Project/chatterbox/docs/domains/03-voice-director-workflow.md) | `tests/test_project_workflow.py` |
| **Lập Timeline & Trộn sóng** | `mix`, `timeline`, `ducking`, `crossfade`, `wave_audio_mixer` | `mix_plan_builder.py`, `wave_audio_mixer.py` | `voice_workflows.py` | `js/director-console.js` | `voice_project_tools.py` | [Domain 04](file:///e:/Project/chatterbox/docs/domains/04-audio-engineering.md) | `tests/test_mix_plan_builder.py`, `test_wave_audio_mixer.py` |
| **Mastering & Limiter** | `master`, `lufs`, `true_peak`, `peak_limiter`, `ebur128` | `audio_mastering.py` | `voice_workflows.py` | `js/director-console.js` | `voice_project_tools.py` | [Domain 04](file:///e:/Project/chatterbox/docs/domains/04-audio-engineering.md) | `tests/test_audio_mastering.py` |
| **Xuất xưởng & SHA-256** | `export`, `manifest`, `sha256`, `final_wav` | `audio_export.py`, `atomic_io.py` | `voice_workflows.py` | `js/director-console.js` | `voice_project_tools.py` | [Domain 04](file:///e:/Project/chatterbox/docs/domains/04-audio-engineering.md) | `tests/test_audio_export.py` |
| **Tài nguyên & Phát âm** | `assets`, `sfx`, `ambience`, `pronunciation`, `proper_nouns` | `asset_library_service.py`, `pronunciation_knowledge.py`, `resource_manager.py` | `voice_assets.py` | — | `asset_tools.py` | [Domain 03](file:///e:/Project/chatterbox/docs/domains/03-voice-director-workflow.md) | `tests/test_asset_library.py`, `test_pronunciation_knowledge.py` |
| **Series Nhiều tập** | `series`, `episodes`, `voice_bible`, `series_production` | `voice_series_service.py`, `voice_series_operations.py` | `voice_series.py` | — | `series_tools.py` | [Domain 03](file:///e:/Project/chatterbox/docs/domains/03-voice-director-workflow.md) | `tests/test_voice_series_service.py` |
| **Sức khỏe & Chẩn đoán** | `health`, `diagnostics`, `runtime_caps`, `preflight` | `production_health_service.py`, `diagnostics_service.py`, `local_runtime_service.py` | `voice_health.py`, `voice_runtime.py`, `system.py` | `js/main.js` | `health_tools.py`, `runtime_tools.py` | [Domain 05](file:///e:/Project/chatterbox/docs/domains/05-events-and-observability.md) | `tests/test_production_health.py`, `test_diagnostics_bundle.py` |
| **Web Shell & Favicon** | `favicon`, `material_dashboard.html`, `theme`, `shortcuts` | `api_app.py` | `api_app.py` | `material_dashboard.html`, `js/main.js`, `favicon.ico`, `favicon.svg` | — | [Domain 06](file:///e:/Project/chatterbox/docs/domains/06-webui-and-mcp.md) | `tests/test_api_app.py` |
| **Tương thích Nền tảng** | `windows`, `linux`, `file_lock`, `atomic_io`, `psapi`, `ctypes` | `file_lock.py`, `atomic_io.py`, `production_validation_metrics.py`, `platform_tools.py` | — | — | — | [Invariants](file:///e:/Project/chatterbox/docs/invariants.md) | `tests/test_file_lock.py`, `test_atomic_io.py` |

---

## 2. Danh mục Tài liệu Chuyên sâu theo Domain

Để tìm hiểu chi tiết luồng dữ liệu và các quy tắc nghiệp vụ, đọc các tài liệu sau:

1. **[docs/domains/01-tts-and-models.md](file:///e:/Project/chatterbox/docs/domains/01-tts-and-models.md)**: TTS, Voice Cloning, vòng đời Checkpoints (Nano, Turbo, Standard, Multilingual).
2. **[docs/domains/02-batch-and-qc.md](file:///e:/Project/chatterbox/docs/domains/02-batch-and-qc.md)**: Batch Studio, phân tích kịch bản, phụ đề SRT, Signal QC & Whisper Content Critic.
3. **[docs/domains/03-voice-director-workflow.md](file:///e:/Project/chatterbox/docs/domains/03-voice-director-workflow.md)**: Quy trình 25 bước Voice Director, Story Beats, Human Approval Gates, Revisions.
4. **[docs/domains/04-audio-engineering.md](file:///e:/Project/chatterbox/docs/domains/04-audio-engineering.md)**: Hậu kỳ âm thanh, MixPlan đa track, chuẩn hóa LUFS, soft-knee limiter, xuất SHA-256.
5. **[docs/domains/05-events-and-observability.md](file:///e:/Project/chatterbox/docs/domains/05-events-and-observability.md)**: EventBus, Zero-CPU Long-Polling, Health Check, Diagnostics Redaction.
6. **[docs/domains/06-webui-and-mcp.md](file:///e:/Project/chatterbox/docs/domains/06-webui-and-mcp.md)**: Material Web UI (vanilla không build step) và 76 MCP Tools cho AI IDE.
7. **[docs/invariants.md](file:///e:/Project/chatterbox/docs/invariants.md)**: Quy tắc bất biến bắt buộc tuân thủ (Layering, Windows/Linux, Atomic IO).

---

## 3. Bản đồ Lịch sử Phát triển theo Phase (Phases 1–25)

### Phase 1–3: Phân tích Cốt truyện & Đạo diễn Âm thanh
- `services/story_analyzer.py` — Nhận diện StoryBeat, vai trò nhân vật, bối cảnh cảm xúc.
- `services/sound_director.py` — Đạo diễn âm thanh tự động (Ambience, SFX, khoảng lặng).
- `services/voice_plan.py` — Hợp đồng cấu trúc VoicePlan.

### Phase 4–6: Tài nguyên & Cơ sở Tri thức Phát âm
- `services/resource_manager.py` — Trích xuất yêu cầu âm thanh, chấm điểm ứng viên, đồ thị thay thế.
- `services/pronunciation_knowledge.py` — Cơ sở tri thức tên riêng thần thoại (proper nouns).
- `services/asset_ingest.py`, `services/resource_doctor.py` — Nạp asset, kiểm tra sức khỏe thư viện.

### Phase 7–10: Render Từng Beat & 3-Layer Voice QC
- `services/voice_renderer.py` — Render từng beat theo VoicePlan, idempotency và resume.
- `services/voice_qc.py` — Kiểm định 3 lớp (Signal, Content, Direction), candidate ranking.
- `services/tts/` — TTS Provider protocol (`FakeTTSProvider`, `GeminiTTSProvider`, Local).

### Phase 11–13: Ứng dụng Dự án & Giao diện REST/MCP
- `services/voice_project_service.py` — Application facade thống nhất.
- `services/voice_project_store.py` — Lưu trữ YAML nguyên tử.
- `routers/voice_projects.py`, `mcp_adapter/voice_project_tools.py`.

### Phase 14–16: Hậu kỳ Mix, Master, Export & Đạo diễn Đánh giá
- `services/mix_plan_builder.py`, `services/wave_audio_mixer.py` — Trộn sóng PCM đa track.
- `services/audio_mastering.py`, `services/audio_export.py` — Đo chuẩn LUFS, limiter, SHA-256.
- `services/director_review_service.py`, `services/director_revision_service.py` — Review snapshot, audit revisions, reproduce.

### Phase 17–20: Khả năng Runtime, Thư viện Thông minh, Series & Giám sát
- `services/local_runtime_service.py` — Capabilities & Preflight validation (Phase 17).
- `services/asset_library_service.py`, `services/asset_matching_service.py` — Semantic asset match (Phase 18).
- `services/voice_series_service.py`, `services/voice_series_operations.py` — Series đa tập (Phase 19).
- `services/production_health_service.py`, `services/diagnostics_service.py` — Health & Diagnostics (Phase 20).

### Phase 21–25: Tối ưu Nền tảng & Điều phối Tự trị Chuyên sâu
- **Phase 21 — Real-Runtime Validation**: `services/production_validation_service.py`, đo lường tài nguyên thực tế với peak memory telemetry.
- **Phase 22 — Windows Portability**: Khóa tệp `services/file_lock.py` (`msvcrt`), đo RAM `ctypes` (`psapi`), bảo toàn hash CRLF trong `services/atomic_io.py`.
- **Phase 23 — Static Delivery & Favicon**: Cung cấp `/favicon.ico` và `/favicon.svg`, giải quyết lỗi 404.
- **Phase 24 — Authoritative Next-Action Governance**: `services/voice_project_workflow.py::next_action()`, điều phối hành động đơn nhất, giám sát thao tác nền, chặn duplicate submission.
- **Phase 25 — Persistent Notifications & Dynamic UI**: `routers/events.py` (`DELETE /api/v1/events`), `webui/js/notifications.js` (lưu trữ `localStorage`, xóa từng tin, icon động `notifications_active`, cache-busting).

---

## 4. Trách nhiệm Sở hữu (Ownership Rules)

1. **Business Logic** chỉ được phép tồn tại trong `services/`.
2. **Routers** (`routers/`) chỉ validate và chuyển đổi HTTP.
3. **MCP Adapters** (`mcp_adapter/`) chỉ chuyển tiếp giao thức JSON-RPC, schema khai báo tại `mcp_adapter/catalog.py`.
4. **Web UI** (`webui/`) chỉ hiển thị và gọi API REST. Không chứa thuật toán nghiệp vụ.
5. **JobManager** sở hữu tiến trình kỹ thuật của task. **Project Planner** sở hữu trạng thái nghiệp vụ.
