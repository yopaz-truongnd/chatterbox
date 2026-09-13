# Chatterbox Architecture & Platform Invariants

Tài liệu này định nghĩa các **quy tắc bất biến (Invariants)** bắt buộc phải tuân thủ trong toàn bộ codebase Chatterbox. Bất kỳ agent AI nào khi sửa code đều phải đọc và áp dụng các nguyên tắc này.

---

## 1. Ranh giới Phân tầng (Architectural Layering Invariants)

Hệ thống tuân thủ mô hình phân tầng nghiêm ngặt (Strict Layering):

```
┌─────────────────────────────────────────────────────────────┐
│                       Giao diện Ngoài                       │
│    WebUI (webui/)  │  MCP (mcp_adapter/)  │  CLI (voice_cli) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Layer (routers/)                     │
│   Chỉ Validate Pydantic, parse HTTP query, serialize JSON   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                Domain Logic Layer (services/)               │
│   TOÀN BỘ Business Logic, State Machine, Thuật toán, Audio   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Hạ tầng & Hệ điều hành (utils/)                │
│       File Lock, Atomic IO, Hardware Profiling, Process      │
└─────────────────────────────────────────────────────────────┘
```

### Quy tắc bất biến:
1. **`routers/` KHÔNG chứa Business Logic**:
   - Router chỉ nhận request, validate schema (Pydantic/Query), gọi service tương ứng và trả về response HTTP.
   - Không thực hiện tính toán âm thanh, không đọc ghi file trực tiếp trong router.
2. **`mcp_adapter/` chỉ là bộ chuyển tiếp giao thức (Protocol Adapter)**:
   - Các handler trong `mcp_adapter/` chỉ đóng vai trò dịch từ JSON-RPC stdio sang REST API client hoặc gọi service helper. Không sao chép logic từ service vào MCP.
3. **`webui/` là Vanilla JS, KHÔNG có Build Step**:
   - Không sử dụng Webpack, Vite, npm, hay React/Vue.
   - Toàn bộ giao diện phục vụ trực tiếp file tĩnh (`.html`, `.js`, `.css`).
   - Mọi thay đổi trong JS/CSS phải thêm chuỗi cache-busting (ví dụ: `?v=20260914-v27`) tại `webui/material_dashboard.html`.
4. **Single Source of Truth cho Trạng thái Dự án**:
   - Trạng thái kỹ thuật (Job render, tiến trình %, RAM) do `services/job_manager.py` sở hữu.
   - Trạng thái nghiệp vụ (Gate 1 requirements, Gate 2 script, Director Plan) do `services/project_planner.py` và `services/voice_project_service.py` sở hữu.
   - UI và MCP chỉ là Consumer đọc dữ liệu.

---

## 2. Quy chuẩn Tương thích Nền tảng (Cross-Platform Portability: Windows vs Linux)

Dự án hoạt động trên cả **Linux** (production server, Docker, Shell script) và **Windows** (nhà phát triển, PowerShell).

| Vấn đề kỹ thuật | Linux / POSIX | Windows | Quy tắc bất biến trong Chatterbox |
|---|---|---|---|
| **Khóa tệp độc quyền (File Lock)** | `fcntl.flock(fd, LOCK_EX)` | `msvcrt.locking(fd, LK_NBLCK, ...)` | **Luôn dùng** context manager `exclusive_file_lock` từ `services/file_lock.py`. Tuyệt đối không `import fcntl` trần. |
| **Đo lường RAM tiến trình** | `import resource; resource.getrusage()` | `ctypes.windll.psapi.GetProcessMemoryInfo()` | **Luôn dùng** hàm bọc `try...except ImportError` và fallback sang `ctypes` trên Windows (xem `services/production_validation_metrics.py`). |
| **Ký tự xuống dòng (Newlines)** | LF (`\n`) | CRLF (`\r\n`) | **Luôn dùng** `newline=""` hoặc mở file nhị phân khi tính toán mã băm SHA-256 (xem `services/atomic_io.py`). |
| **Console Encoding & Emojis** | UTF-8 mặc định | PowerShell mặc định `cp1252` | Tránh in trực tiếp emoji Unicode (như ❌, ✅, 🎙️) ra `sys.stdout` nếu không có cấu hình `sys.stdout.reconfigure(encoding='utf-8')`. |
| **Đường dẫn tệp (Paths)** | `/path/to/file` | `C:\path\to\file` | **Luôn dùng** `pathlib.Path` cho mọi thao tác đường dẫn. Chuyển sang chuỗi bằng `path.as_posix()` khi cần URL hoặc manifest. |

---

## 3. An toàn Dữ liệu & Ghi tệp Nguyên tử (Atomic I/O & Persistence)

1. **Ghi tệp an toàn (Atomic Write)**:
   - Không bao giờ ghi trực tiếp vào file dữ liệu chính (như `settings.json`, `.yaml`, `.wav`, `.db`).
   - Luôn ghi ra tệp tạm `.tmp` hoặc `.part`, flush, fsync, sau đó mới dùng `os.replace` để đổi tên đè vào tệp đích. Sử dụng `services/atomic_io.py`.
2. **Quản lý Đồng thời (Concurrency)**:
   - Mọi thao tác truy cập ring-buffer sự kiện (`LocalEventBus`) phải được bọc trong `with self._condition:`.
   - Mọi thao tác đọc ghi file trạng thái project phải qua `VoiceProjectStore` có kiểm tra stale data.

---

## 4. Kiểm thử Tự động & Quy trình Sau Khi Sửa Code

Mỗi khi sửa đổi mã nguồn:
1. **Xác định đúng bộ test hẹp nhất** trong bảng `docs/agent-map.md`.
2. **Chạy test xác thực ngay**:
   ```bash
   python -m unittest tests/test_tên_file.py
   ```
3. **Không tự ý chạy lệnh Git**:
   - Tuyệt đối không chạy `git commit`, `git push`, `git checkout` nếu người dùng chưa yêu cầu rõ ràng.
