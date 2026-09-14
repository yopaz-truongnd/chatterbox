# Domain 01: TTS Synthesis, Voice Cloning & Model Management

Tài liệu hướng dẫn sửa đổi và vận hành luồng sinh giọng nói đơn lẻ, clone giọng nói và quản lý vòng đời mô hình AI trong Chatterbox.

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - Nhận văn bản, tham số suy luận (`temperature`, `exaggeration`, `speed`, `cfg_scale`, `seed`).
  - Quản lý kho mẫu giọng nhân vật (`character_api.py`) và trích xuất embedding tham chiếu.
  - Quản lý tải và giữ mô hình trong bộ nhớ (`services/model_runtime.py`), tự động chọn model theo cấu hình RAM (`Nano 110M`, `Turbo 350M`, `Standard 500M`, `Multilingual 500M`).
  - Cách ly tiến trình suy luận (Subprocess inference isolation) để giải phóng VRAM/RAM khi cần.
- **KHÔNG thuộc phạm vi**:
  - Cắt ghép kịch bản hàng loạt (thuộc `02-batch-and-qc`).
  - Đạo diễn kịch bản nhiều nhân vật / Story Beat (thuộc `03-voice-director-workflow`).
  - Mix nhạc nền / Master LUFS (thuộc `04-audio-engineering`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Service cốt lõi** | `services/synthesis.py` | Chuẩn hóa tham số, điều phối sinh audio |
| **Service nạp model** | `services/model_runtime.py` | Quản lý vòng đời checkpoint, thread safety, device mapping |
| **Service danh mục** | `services/model_registry.py` | Kiểm tra cache mô hình trong `models/`, metadata model |
| **Cầu nối Subprocess** | `services/inference.py` | Chạy inference trong subprocess cách ly |
| **Kho nhân vật** | `character_api.py` | Quản lý CRUD nhân vật, metadata, audio mẫu |
| **API Routers** | `routers/tts.py` | Endpoint `/api/v1/tts`, `/synthesize`, `/models` |
| **Giao diện WebUI** | `webui/js/tts.js` | Tab 1: Sinh giọng nói nhanh |
| | `webui/js/characters.js` | Tab 3: Quản lý nhân vật & mẫu giọng |
| | `webui/js/vc.js` | Tab 4: Chuyển đổi giọng nói (Voice Conversion) |
| | `webui/js/multilingual.js` | Tab 2: TTS Đa ngôn ngữ |
| **Công cụ MCP** | `mcp_adapter/voice_tools.py` | `chatterbox_generate_tts`, `chatterbox_voice_conversion`, `chatterbox_list_characters`, `chatterbox_save_character` |
| **Kiểm thử** | `tests/test_api_app.py` | Test endpoint HTTP TTS |
| | `tests/test_character_api.py` | Test quản lý nhân vật |
| | `tests/test_services_unified.py` | Test pipeline synthesis |

---

## 3. Luồng Dữ liệu (Data Flow)

```
[User / WebUI / MCP]
        │
        ▼ (Text, VoiceRef, Params)
   [routers/tts.py]
        │
        ▼ (Validate & Normalize)
 [services/synthesis.py] ◄──► [character_api.py] (Load reference audio)
        │
        ▼ (Check cached model or load)
 [services/model_runtime.py] ◄──► [services/model_registry.py]
        │
        ▼ (In-process or isolated subprocess)
 [services/inference.py] ──► PyTorch Model Forward (Chatterbox Engine)
        │
        ▼ (WAV Tensor, Sample Rate 24kHz)
 [Audio Output (.wav)] ──► Response / Job Result
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Giới hạn luồng CPU**: Luôn tuân thủ `CHATTERBOX_API_CPU_THREADS` (mặc định 2 threads) qua `torch.set_num_threads()` để không làm treo hệ điều hành.
2. **Khuyên dùng Model theo phần cứng**:
   - Máy RAM ≤ 16GB: Mặc định khuyên dùng `nano` (110M).
   - Máy RAM > 16GB hoặc có GPU: Khuyên dùng `turbo` (350M).
3. **Mô hình Multilingual**: Nếu checkpoint chưa có trong `models/`, báo lỗi hướng dẫn chạy tải trọng số rõ ràng, không crash server.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_api_app.py tests/test_character_api.py
```
