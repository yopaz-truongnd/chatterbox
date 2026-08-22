# 🎙️ Chatterbox TTS Studio & REST API

[![PyTorch](https://img.shields.io/badge/PyTorch-2.6.0-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-v1.4.0-009688?logo=fastapi&logoColor=white)](http://localhost:8000/docs)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%2010%2B%20%7C%20Linux-blue)](https://github.com/resemble-ai/chatterbox)

Chatterbox TTS Studio là giải pháp tổng hợp giọng nói (Text-to-Speech), nhân bản giọng nói tức thì (Zero-Shot Voice Cloning) và chuyển đổi giọng nói (Voice Conversion) chạy hoàn toàn **Local Offline**, hỗ trợ đa nền tảng **macOS (Apple Silicon/Intel)**, **Windows 10/11** và **Linux**.

---

## ⚡ 1. Khởi động Nhanh (Quick Start)

### 🍎 macOS & 🐧 Linux:
```bash
# 1. Cài đặt môi trường (chỉ lần đầu)
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 2. Cài đặt các gói phụ thuộc (Khuyên dùng: .[all] hoặc .[api])
pip install -e ".[all]"      # Đầy đủ cả API, Web Studio và Desktop GUI
# pip install -e ".[api]"    # Hoặc chỉ cài Web Studio & REST API

# 3. Khởi chạy Web Studio & REST API Server
./run_chatterbox_api.sh

# 4. Chạy kiểm thử tự động (37 unit tests)
./run_chatterbox_api.sh --test
```

### 🪟 Windows 10/11:
```powershell
# Cài đặt môi trường trên PowerShell / Command Prompt
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[all]"      # hoặc pip install -e ".[api]"
```
* **Khởi chạy:** Nhấp đúp chuột vào file **[`Run_Chatterbox_API.bat`](Run_Chatterbox_API.bat)** hoặc chạy lệnh: `.\run_chatterbox_api.ps1`.

Sau khi khởi chạy, truy cập trình duyệt:
* 🎨 **Web GUI Studio:** [http://localhost:8000/](http://localhost:8000/)
* 📖 **Tài liệu API (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🌟 2. Tính năng Cốt lõi

* ⚡ **Tự động tối ưu tài nguyên:** Tự nhận diện phần cứng (Apple Metal MPS trên macOS, NVIDIA CUDA trên Windows/Linux hoặc CPU). Tự động chọn model **Nano (110M)** cho máy có RAM $\le 16\text{ GB}$ hoặc CPU để tránh tràn RAM (OOM).
* 🛡️ **Kiến trúc Cô lập Tiến trình (Isolated Subprocess):** Tác vụ sinh âm thanh chạy trong tiến trình riêng. Hạn chế tối đa crash server, hỗ trợ **hủy job (Cancel)** an toàn và giải phóng RAM ngay lập tức.
* 📖 **Nối Văn bản dài (Long-Text Batch):** Tự động phân tách văn bản lớn (sách, truyện, kịch bản) theo câu/dấu chấm, sinh tuần tự và ghép thành **1 file WAV duy nhất** kèm khoảng lặng tùy chỉnh và hòa âm nhạc nền (BGM).
* 💾 **Cơ sở dữ liệu SQLite & Tự động dọn dẹp:** Lưu trữ toàn bộ lịch sử job vào `jobs.db`, tự động phục hồi trạng thái sau khi restart server và tự xóa file cũ theo chính sách TTL (mặc định 3 ngày).
* 🎭 **Quản lý Nhân vật & Giọng mẫu:** Thư viện 6 giọng mẫu chuyên nghiệp (*MC Thời Sự, Kể Chuyện Đêm Khuya, Review Phim, Anime,...*) và công cụ tạo nhân vật kèm file audio tham chiếu tùy biến.
* 📊 **Đo lường Hiệu năng (Benchmark Telemetry):** Báo cáo chi tiết tốc độ sinh (`Realtime Factor - RTF`, tốc độ gấp X lần thời gian thực, thời gian nạp model và độ dài file âm thanh).
* 🎛️ **Preset Chất lượng:** 3 cấu hình nhanh: ⚡ *Siêu Nhanh (Fast)*, ⚖️ *Cân Bằng (Balanced)*, 🎭 *Biểu Cảm Cao (Expressive)*.

---

## 📦 3. Danh mục Model (Model Zoo)

| Model | Tham số | Ngôn ngữ | Đặc điểm nổi bật | Phù hợp nhất |
| :--- | :--- | :--- | :--- | :--- |
| **Chatterbox-Nano** | **110M** | Tiếng Anh / Đa dụng | Siêu nhẹ, chạy mượt trên CPU & RAM $\le 16\text{ GB}$, hỗ trợ thẻ cảm xúc `[laugh]`, `[whisper]`. | Máy cá nhân, Mac mini M1/M2, CPU-only. |
| **Chatterbox-Turbo** | **350M** | Tiếng Anh / Đa dụng | Tốc độ cao, biểu cảm mạnh, hỗ trợ đầy đủ 11 thẻ cảm xúc paralinguistic. | GPU NVIDIA $\ge 6\text{ GB}$ VRAM, Apple Silicon 32GB+. |
| **Chatterbox-Standard** | **500M** | Tiếng Anh | Tùy chỉnh sâu CFG Weight & Exaggeration. | Studio chuyên nghiệp, sản xuất âm thanh. |
| **Chatterbox-Multilingual V3** | **500M** | 23+ Ngôn ngữ | Giữ chuẩn ngữ điệu và giọng nói gốc qua nhiều ngôn ngữ. | Ứng dụng toàn cầu, đa ngôn ngữ. |

---

## 🔌 4. REST API Endpoints Chính

| Phương thức | Endpoint | Chức năng |
| :--- | :--- | :--- |
| `POST` | `/api/v1/tts` | Sinh âm thanh TTS cơ bản (Tự động chọn Nano hoặc Turbo theo cấu hình máy). |
| `POST` | `/api/v1/tts/long-text` | Sinh âm thanh cho văn bản dài, tự chia đoạn và xuất ra 1 file WAV hoàn chỉnh. |
| `POST` | `/api/v1/voice-conversion` | Chuyển đổi âm sắc từ file giọng gốc sang giọng mục tiêu (Voice Conversion). |
| `POST` | `/api/v1/projects/prepare` | Khởi tạo dự án âm thanh (Gate 1: Tự động trích xuất yêu cầu & hỏi 1 lượt). |
| `POST` | `/api/v1/projects/{id}/confirm-requirements` | Xác nhận yêu cầu (Gate 1) & tự động lập dàn ý, soạn kịch bản tiếng Anh. |
| `POST` | `/api/v1/projects/{id}/confirm-script` | Xác nhận và phê duyệt kịch bản (Gate 2) cho phép bước vào khâu Render. |
| `POST` | `/api/v1/projects/{id}/render` | High-Level Orchestration: Chia đoạn ngữ nghĩa, submit batch & hậu kỳ WAV. |
| `GET`  | `/api/v1/events` | Luồng sự kiện thời gian thực (Real-time Event Stream) với Condition Long-Polling (0% CPU). |
| `GET`  | `/api/v1/jobs/{id}` | Truy vấn trạng thái, tiến độ thực tế (0-100%) và telemetry benchmark của job. |
| `POST` | `/api/v1/jobs/{id}/cancel` | Hủy ngay lập tức job đang chờ hoặc đang xử lý. |
| `GET`  | `/api/v1/jobs/{id}/audio` | Tải xuống file WAV kết quả chất lượng cao (24kHz Mono). |
| `GET`  | `/api/v1/diagnostics` | Báo cáo chẩn đoán toàn diện: OS, GPU, VRAM, RAM, FFmpeg, Checkpoints. |
| `GET/POST`| `/api/v1/characters` | Quản lý danh sách nhân vật và cấu hình giọng mẫu. |
| `POST` | `/api/v1/audio/merge` | Ghép nhiều đoạn âm thanh từ các job trước đó thành một file duy nhất kèm BGM. |

---

## 🤖 5. Model Context Protocol (MCP) Server

Tích hợp sẵn stdio MCP Server tương thích tiêu chuẩn Claude Desktop, Google Antigravity & OpenAI Codex với **16 tools chuyên dụng**:
* `chatterbox_list_characters`, `chatterbox_generate_tts`, `chatterbox_get_job_status`, `chatterbox_download_audio`, `chatterbox_voice_conversion`, `chatterbox_evaluate_voice`
* `chatterbox_prepare_project`, `chatterbox_answer_project_questions`, `chatterbox_confirm_requirements`, `chatterbox_generate_script`, `chatterbox_confirm_script`, `chatterbox_confirm_project`, `chatterbox_render_project`, `chatterbox_get_project`, `chatterbox_list_projects`
* `chatterbox_get_events` (Long-polling real-time updates)

---

## 📂 6. Cấu trúc Dự án

```text
chatterbox/
├── api_app.py                   # FastAPI Server entrypoint & Lifespan
├── mcp_server.py                # Stdio MCP Server (16 tools) cho AI Agents
├── character_api.py             # Voice Character store & Zip export/import
├── job_store.py                 # SQLite Job Persistence & TTL Cleanup
├── inference_runner.py          # Isolated Subprocess Runner
├── main.py                      # Desktop GUI launcher wrapper
├── apps/                        # Giao diện ứng dụng
│   ├── desktop.py               # Tkinter Desktop GUI
│   ├── material_dashboard.py    # Static Material 3 Web runner
│   └── gradio/                  # Gradio Apps (tts, tts_turbo, voice_conversion, multilingual)
├── examples/                    # Code mẫu chạy độc lập
│   ├── tts.py, tts_nano.py, tts_turbo.py, voice_conversion.py, macos.py
├── scripts/                     # Scripts khởi chạy và tiện ích
│   ├── api/                     # run.sh, run.ps1, run.bat
│   ├── desktop/                 # run.sh, run.bat, run_silent.vbs
│   └── download_models.py       # Tải trước model offline
├── docs/                        # Tài liệu hướng dẫn & Kiến trúc
│   ├── architecture.md          # Sơ đồ kiến trúc & luồng hoạt động
│   ├── setup.md                 # Hướng dẫn cài đặt đa nền tảng
│   ├── models.md                # Danh mục model và hướng dẫn cấu hình phần cứng
│   └── assets/                  # Hình ảnh mô tả
├── services/                    # Application Business Logic
│   ├── event_bus.py             # In-memory Ring Buffer Event Bus & Condition Long-Polling
│   ├── project_planner.py       # Two-Gate confirmation, semantic segmentation & auto-fix
│   ├── inference.py             # Logic nạp model & sinh âm thanh chuẩn
│   ├── audio.py                 # Ghép nối khoảng lặng, loudness normalization & BGM
│   └── job_manager.py           # Quản lý hàng đợi, lifecycle của job & subprocess cô lập
├── routers/                     # FastAPI Endpoints
│   ├── events.py                # Long-polling event streaming router
│   ├── projects.py              # Two-Gate Audio Projects REST API
│   ├── system.py                # Health, Diagnostics, Settings & Models Status
│   ├── tts.py                   # TTS Single, Batch, Long-Text, Presets & VC
│   └── jobs.py                  # Tra cứu, Hủy job, Download audio & Merge batch
├── webui/                       # Material Design 3 Web GUI Frontend
│   ├── material_dashboard.html  # Dashboard Single Page App
│   ├── js/                      # Controllers: main, tts, batch, projects, notifications,...
│   └── css/styles.css           # Bảng phong cách giao diện
├── run_chatterbox_api.sh        # Launcher API macOS / Linux (Wrapper tương thích)
├── Run_Chatterbox_API.bat       # Launcher API Windows Batch (Wrapper tương thích)
├── run_chatterbox_api.ps1       # Launcher API Windows PowerShell (Wrapper tương thích)
├── run_chatterbox_gui.sh        # Launcher Desktop macOS / Linux (Wrapper tương thích)
├── Run_Chatterbox_GUI.bat       # Launcher Desktop Windows Batch (Wrapper tương thích)
└── tests/                       # Bộ kiểm thử tích hợp (108 unit tests)
```

---

## 🧪 7. Chạy Kiểm thử (Unit Tests)

Kiểm thử toàn bộ hệ thống (được mock inference để chạy tức thì):

```bash
./run_chatterbox_api.sh --test
```
*Kết quả:* **108/108 tests passed**.

---

## 📜 8. Giấy phép (License)

Dự án phát triển dựa trên mô hình mã nguồn mở Chatterbox của Resemble AI theo giấy phép [MIT License](LICENSE).
