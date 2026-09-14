# Domain 03: Voice Director & 25-Phase Production Workflow

Tài liệu hướng dẫn kiến trúc sản xuất âm thanh tự động (Autonomous Voice Production), quy trình 25 bước đạo diễn, quản lý Story Beats, kiểm soát phê duyệt của con người (Human Gates) và tái tạo tối thiểu an toàn (Incremental Reproduction).

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - Đọc kịch bản nguồn bất biến, phân tích cấu trúc kịch bản thành các nhịp truyện (`StoryBeat`), xác định vai trò (Narrator, Character, Ambient, Climax).
  - Lập kế hoạch đạo diễn âm thanh (`services/sound_director.py`): Gán ý định âm thanh (Ambience, SFX, khoảng lặng kịch tính).
  - Tạo và duy trì hợp đồng `VoicePlan` (Phát âm, cảm xúc, năng lượng, tốc độ WPM mục tiêu, chiến lược ứng viên).
  - Quản lý vòng đời dự án (`services/voice_project_service.py`) lưu trữ bằng YAML nguyên tử.
  - Vòng lặp điều phối tự động 25 bước (`services/voice_project_workflow.py`):
    - Tự động chạy qua các bước kỹ thuật (Plan, Resource Check, Render, QC, Mix, Master, Export).
    - Tự động dừng tại các cổng cần quyết định của con người (**Human Action Gates** như `requirements_confirmation`, `script_approval`, `narration_acceptance`).
    - Xác định hành động tiếp theo chính danh (**Authoritative Next Action - Phase 24**).
  - Tiếp nhận yêu cầu chỉnh sửa nghệ thuật (`DirectorRevisionService`), tính toán ảnh hưởng và chỉ render lại tối thiểu các phân đoạn bị ảnh hưởng (`reproduce`).
- **KHÔNG thuộc phạm vi**:
  - Thuật toán trộn sóng PCM WAV (thuộc `04-audio-engineering`).
  - Quản lý kho tệp tĩnh UI (thuộc `06-webui-and-mcp`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Phân tích cốt truyện** | `services/story_analyzer.py` | Phân đoạn ngữ nghĩa, nhận diện nhịp truyện, StoryBeat |
| **Đạo diễn âm thanh** | `services/sound_director.py` | Gán ý định SFX, Ambience, Music theo mạch cảm xúc |
| **Hợp đồng VoicePlan** | `services/voice_plan.py` | Cấu trúc dữ liệu kế hoạch giọng nói, backward compatibility |
| **Service dự án chính** | `services/voice_project_service.py` | Application Service facade cho Voice Projects |
| **Kho lưu trữ dự án** | `services/voice_project_store.py` | Đọc ghi atomic YAML, quản lý phiên bản `project.yaml` |
| **Quản lý tiến trình nền**| `services/voice_project_operations.py`| Chạy tác vụ nền (render, mix, master), huỷ, phục hồi |
| **Điều phối 25 bước** | `services/voice_project_workflow.py` | Vòng lặp workflow, state machine, Next Action Engine |
| **Đánh giá Đạo diễn** | `services/director_review_service.py` | Đọc snapshot tổng hợp, điểm khuyết tài nguyên, candidate |
| **Sửa đổi kịch bản** | `services/director_revision_service.py`| Tiếp nhận revision, audit trail, tái tạo tối thiểu an toàn |
| **API Routers** | `routers/voice_projects.py` | REST API dự án, revisions, review, reproduce |
| | `routers/voice_workflows.py` | REST API quy trình workflow, step execution, next action |
| **Giao diện WebUI** | `webui/js/director-console.js` | Director Console (Điều khiển 25 Phase). Panel "Tạo bản thu mới" có 2 chế độ: dán kịch bản có sẵn, hoặc "Tạo từ ý tưởng" (nhúng lại luồng 2-gate `/api/v1/projects/*` bên dưới để tự sinh kịch bản trước khi vào workflow). |
| **MCP Tools** | `mcp_adapter/voice_project_tools.py` | 35+ công cụ MCP điều phối từ xa cho AI IDE |
| **Kiểm thử** | `tests/test_voice_orchestration_phase24.py`| Test xác định authoritative next-action |
| | `tests/test_director_phase16.py` | Test snapshot review, audit revisions, reproduce |
| | `tests/test_story_analyzer.py` | Test phân tích beat kịch bản |

---

## 3. Vòng lặp Điều phối 25 Bước (25-Phase Production Cycle)

```
[Kịch bản nguồn (Immutable)]
       │
       ▼
Phase 1-3: [Story Analysis] ──► [Sound Direction] ──► [VoicePlan Generation]
       │
       ▼
Phase 4-6: [Resource Requirements] ──► [Asset Ingest & Binding] ──► [Pronunciation Bible]
       │
       ▼
Phase 7-10: [Per-Beat Rendering] ──► [3-Layer Voice QC] ──► [Candidate Selection]
       │
       ▼
Phase 11-13: [Gate: Narration Acceptance] ──► (Dừng chờ Human duyệt hoặc sửa Revisions)
       │
       ▼
Phase 14-16: [MixPlan Building] ──► [Multi-Track Audio Mixing] ──► [Mastering LUFS]
       │
       ▼
Phase 17-20: [Delivery Package Export] ──► [Lineage Audit] ──► [Health & Diagnostics]
       │
       ▼
Phase 21-25: [Real-Runtime Validation] ──► [Authoritative Next-Action Governance]
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Kịch bản nguồn là bất biến (Source Script is Immutable)**: Không sửa đổi tệp kịch bản gốc. Mọi thay đổi phát âm, ngắt nghỉ, cường độ phải đi qua cơ chế `DirectorRevision` được lưu vào `revision-history.yaml`.
2. **Cổng người duyệt (Human Gates) là bắt buộc**: Khi `next_action()` trả về trạng thái yêu cầu con người duyệt (`requires_human=True`), workflow bắt buộc phải dừng lại và chờ lệnh từ người dùng. AI không được tự ý giả lập chấp thuận.
3. **Tái tạo tối thiểu (Minimum-Safe Reproduction)**: Khi người dùng sửa timing hoặc phát âm của một beat, chỉ render lại beat bị sửa và mix lại; tuyệt đối không render lại toàn bộ các beat không liên quan.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_voice_orchestration_phase24.py tests/test_director_phase16.py
```
