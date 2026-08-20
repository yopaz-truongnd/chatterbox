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
# Cài đặt môi trường (chỉ lần đầu)
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Khởi chạy Web Studio & REST API Server
./run_chatterbox_api.sh

# Chạy kiểm thử tự động (37 unit tests)
./run_chatterbox_api.sh --test
```

### 🪟 Windows 10/11:
* **Cách 1:** Nhấp đúp chuột vào file **[`Run_Chatterbox_API.bat`](Run_Chatterbox_API.bat)**.
* **Cách 2:** Khởi chạy bằng PowerShell:
```powershell
.\run_chatterbox_api.ps1
```

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
| `GET` | `/api/v1/jobs/{id}` | Truy vấn trạng thái, tiến độ thực tế (0-100%) và telemetry benchmark của job. |
| `POST` | `/api/v1/jobs/{id}/cancel` | Hủy ngay lập tức job đang chờ hoặc đang xử lý. |
| `GET` | `/api/v1/jobs/{id}/audio` | Tải xuống file WAV kết quả chất lượng cao (24kHz Mono). |
| `GET` | `/api/v1/diagnostics` | Báo cáo chẩn đoán toàn diện: OS, GPU, VRAM, RAM, FFmpeg, Checkpoints. |
| `GET/POST`| `/api/v1/characters` | Quản lý danh sách nhân vật và cấu hình giọng mẫu. |
| `POST` | `/api/v1/audio/merge` | Ghép nhiều đoạn âm thanh từ các job trước đó thành một file duy nhất kèm BGM. |

---

## 📂 5. Cấu trúc Dự án

```text
chatterbox/
├── api_app.py                   # FastAPI Server entrypoint & Lifespan (<130 dòng)
├── services/
│   ├── inference.py             # Logic nạp model & sinh âm thanh chuẩn (Single Source of Truth)
│   ├── audio.py                 # Ghép nối khoảng lặng, xử lý WAV & hòa âm BGM
│   └── job_manager.py           # Quản lý hàng đợi, lifecycle của job & subprocess cô lập
├── routers/
│   ├── system.py                # Health, System Diagnostics, Settings & Models Status
│   ├── tts.py                   # TTS Standard, Turbo, Nano, Long-Text, Presets & VC
│   └── jobs.py                  # Tra cứu, Hủy job, Download audio & Merge batch
├── utils/
│   ├── platform_tools.py        # Tự nhận diện phần cứng Windows/macOS/Linux & thư mục lưu trữ
│   └── text_cleaner.py          # Làm sạch và phân tách văn bản thông minh
├── webui/
│   └── material_dashboard.html  # Giao diện Web GUI Material Design 3
├── run_chatterbox_api.sh        # Script khởi chạy & chạy test cho macOS / Linux
├── Run_Chatterbox_API.bat       # Script khởi chạy 1-click cho Windows
├── run_chatterbox_api.ps1       # Script PowerShell cho Windows
└── tests/                       # Bộ kiểm thử tích hợp (37 unit tests)
```

---

## 🧪 6. Chạy Kiểm thử (Unit Tests)

Kiểm thử toàn bộ hệ thống (được mock inference để chạy tức thì):

```bash
./run_chatterbox_api.sh --test
```
*Kết quả:* **37/37 tests passed trong ~0.5 giây**.

---

## 📜 7. Giấy phép (License)

Dự án phát triển dựa trên mô hình mã nguồn mở Chatterbox của Resemble AI theo giấy phép [MIT License](LICENSE).
