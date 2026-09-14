# Domain 05: Real-Time Events, Long-Polling & Observability

Tài liệu hướng dẫn hệ thống sự kiện thời gian thực (Real-time Event Stream), cơ chế Long-Polling 0% CPU, quản lý thông báo, giám sát sức khỏe (Health Check) và tạo gói chẩn đoán (Diagnostics Bundle).

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - **In-Memory Ring Buffer Event Bus (`services/event_bus.py`)**:
    - Bộ đệm vòng 500 sự kiện an toàn đa luồng (`threading.Lock`, `collections.deque`).
    - Cơ chế **Zero-CPU Condition Long-Polling** sử dụng `threading.Condition.wait()` thay vì vòng lặp `while...sleep` gây nóng máy / tốn tài nguyên.
    - Cấp phát ID tăng dần và định danh khởi động server (`server_boot_id`) để đồng bộ trạng thái khi server reboot.
    - Cung cấp API dọn dẹp bộ nhớ: `DELETE /api/v1/events` (xóa toàn cục hoặc xóa theo `project_id`).
  - **Lưu vết sự kiện chuyên sâu (`services/production_event_store.py`)**:
    - Ghi sự kiện dạng append-only `events.jsonl` theo từng dự án / series.
    - Tự động xoay vòng file (auto-rotate) khi vượt quá 1000 sự kiện, chống hỏng file (corruption-tolerant).
  - **Giám sát sức khỏe (`services/production_health_service.py`)**:
    - Tổng hợp trạng thái dự án, độ mới của artifact (freshness), các tác vụ đang chạy, mức sử dụng RAM/CPU.
  - **Gói chẩn đoán an toàn (`services/diagnostics_service.py`)**:
    - Tạo bundle chẩn đoán dạng JSON/ZIP: Tự động ẩn danh đường dẫn tuyệt đối (path sanitization) và lọc bỏ token/mật khẩu nhạy cảm (secret redaction).
- **KHÔNG thuộc phạm vi**:
  - Hiển thị HTML panel (thuộc `06-webui-and-mcp`).
  - Trộn âm thanh (thuộc `04-audio-engineering`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Event Bus cốt lõi** | `services/event_bus.py` | Ring buffer in-memory, thread-safe condition wait, boot_id |
| **Sản xuất sự kiện** | `services/job_manager.py` | Phát sinh sự kiện render, auto_fixing, completed, progress |
| | `services/project_planner.py` | Phát sinh sự kiện requirements_ready, script_ready, approved |
| **Lưu vết file JSONL**| `services/production_event_store.py`| File lock `events.jsonl` per-project, auto-rotate 1000 ev |
| **Sức khỏe hệ thống** | `services/production_health_service.py` | Tổng hợp RAM, CPU, Disk, trạng thái tác vụ |
| **Gói chẩn đoán** | `services/diagnostics_service.py` | Thu thập log, redact token bí mật, xuất chẩn đoán |
| **Khả năng Runtime** | `services/local_runtime_service.py` | Quét cache model, GPU/CPU, kiểm tra dung lượng ổ đĩa |
| **API Routers** | `routers/events.py` | `GET /api/v1/events`, `DELETE /api/v1/events` |
| | `routers/voice_health.py` | Endpoint `/health`, `/events`, `/diagnostics` |
| | `routers/voice_runtime.py`| Endpoint `/capabilities`, `/preflight` |
| **Giao diện WebUI** | `webui/js/notifications.js` | Dropdown chuông thông báo, xóa tin, lưu `localStorage` |
| | `webui/js/main.js` | Hàm `checkSystemHealth` định kỳ 15s |
| **Kiểm thử** | `tests/test_project_workflow.py` | Test EventBus ring-buffer, long polling, DELETE events |
| | `tests/test_production_events.py` | Test lưu vết file JSONL, khóa tệp, auto-rotate |
| | `tests/test_production_health.py` | Test tổng hợp sức khỏe project/series |
| | `tests/test_diagnostics_bundle.py`| Test redact bí mật và kiểm tra bundle chẩn đoán |

---

## 3. Luồng Sự kiện Thời gian thực (Real-time Event Flow)

```
[Job / Service Action] ──► event_bus.emit(type, project_id, status, progress, data)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       [In-Memory Ring Buffer (500)]    [Project events.jsonl]
                    │                             │
                    ▼                             ▼
    [threading.Condition.notify_all()]   [Append with file lock]
                    │
                    ▼ (Wakes up zero-CPU wait)
   [GET /api/v1/events?after_id=X&wait=20]
                    │
                    ▼ (HTTP 200 JSON Stream)
   [webui/js/notifications.js]
   (Lọc event > cleared_id ──► Lưu localStorage ──► Toast + Bật chuông notifications_active)
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Zero CPU Idle Wait**: Mọi endpoint chờ sự kiện bắt buộc phải dùng `condition.wait(timeout=remaining)`. Tuyệt đối không dùng vòng lặp `while True: sleep(0.1)` gây lãng phí CPU.
2. **Khởi động lại Server an toàn**: Khi server khởi động lại hoặc buffer bị xóa, `server_boot_id` mới sẽ được trả về để các client web/MCP tự động đồng bộ lại từ `id = 0`, không bị kẹt ở ID cũ trong quá khứ.
3. **Bảo mật trong Gói chẩn đoán (Sanitization Guarantee)**: Mọi báo cáo diagnostics xuất ra không bao giờ được chứa API key, token bí mật hay đường dẫn tuyệt đối của máy tính cá nhân.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_project_workflow.py tests/test_production_events.py tests/test_diagnostics_bundle.py
```
