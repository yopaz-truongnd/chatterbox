# Kiến trúc và luồng hoạt động Chatterbox TTS Studio

Tài liệu này mô tả cấu hình, thành phần, model, entrypoint và luồng xử lý hiện tại của toàn bộ dự án. Tài liệu cài đặt từng bước nằm trong `SETUP_GUIDE.md`; hướng dẫn chọn model nằm trong `MODELS_GUIDE.md`.

## 1. Tổng quan

Dự án cung cấp các phương thức chạy linh hoạt:

| Chế độ | Entrypoint | Launcher | Địa chỉ | Mục đích |
| --- | --- | --- | --- | --- |
| **Material 3 Web Studio & API** | `api_app.py` | `run_chatterbox_api.sh` | `http://127.0.0.1:8000/` | Web GUI Material Design 3 đầy đủ tính năng + REST API v1 |
| **Desktop GUI** | `main.py` | `run_chatterbox_gui.sh` | Cửa sổ Tkinter | Studio offline nguyên bản trên desktop |

Local API và Web Studio được tích hợp chung trên nền FastAPI, cung cấp giao diện Material Design 3 trực quan kèm đầy đủ các RESTful API endpoints tại `/api/v1/` và Swagger UI tại `/docs`.

## 2. Cấu trúc thư mục
 
```text
chatterbox/
├── src/chatterbox/            # Core model architectures & single source of truth version.py
│   ├── version.py             # __version__ = "1.4.0", APP_NAME
│   ├── tts.py                 # Standard 500M
│   ├── tts_turbo.py           # Turbo 350M và Nano 110M
│   ├── mtl_tts.py             # Multilingual V3/V2
│   └── vc.py                  # Voice Conversion
├── services/                  # Application Services dùng chung cho cả Web, API & Desktop
│   ├── exceptions.py          # Domain exceptions (InferenceError, ModelNotFoundError,...)
│   ├── model_registry.py      # Nguồn MODEL_REGISTRY duy nhất (specs, sizes, capabilities, cache)
│   ├── model_runtime.py       # Quản lý vòng đời nạp/cache/giải phóng model trong RAM/VRAM
│   ├── synthesis.py           # Pipeline sinh audio chuẩn hóa tham số, chia text, set seed
│   ├── script_parser.py       # Bộ phân tích kịch bản độc lập (CSV, Markdown, SRT/VTT, Delimiter, Regex)
│   ├── batch_export.py        # Đóng gói và xuất phụ đề SRT/VTT, ZIP atomic archive, timeline merge
│   ├── audio.py               # Xử lý âm thanh, loudness normalization, ducking, conversion
│   ├── batch_runner.py        # Điều phối batch & long-text kèm cơ chế Resume sau restart
│   ├── job_manager.py         # Quản lý hàng đợi job bất đồng bộ, telemetry, SSE stream
│   └── critic.py              # Đánh giá ngữ điệu & speech feedback
├── routers/                   # HTTP Boundary (FastAPI Routers)
│   ├── system.py              # Health, diagnostics, models preflight, settings & benchmarks
│   ├── tts.py                 # TTS endpoints (single, batch, long-text, multilingual, VC)
│   ├── jobs.py                # Job query, cancellation, resumption, SSE events, audio/zip download
│   └── critic.py              # Speech evaluation API
├── character_api.py           # Voice Character store + Zip export/import portability
├── ui/                        # Tkinter Desktop Boundary (Widgets & Event handlers)
│   ├── main_window.py
│   ├── tabs/                  # batch_tab, tts_tab, character_tab, history_tab, mtl_tab, vc_tab
│   └── components/
├── core/
│   └── chatterbox_engine.py   # Desktop engine ủy quyền trực tiếp sang ModelRuntime & Synthesis
├── webui/                     # Material Design 3 Web GUI
├── tests/                     # Test suite (86+ unit & real model smoke tests)
├── api_app.py                 # FastAPI server entrypoint
└── main.py                    # Desktop GUI entrypoint
```

## 3. Model và mục đích sử dụng

| Tên API | Model | Kích thước | Ngôn ngữ | Ghi chú |
| --- | --- | ---: | --- | --- |
| `turbo` | Chatterbox Turbo | 350M | English | Model mặc định của API, hỗ trợ paralinguistic tags |
| `nano` | Chatterbox Nano | 110M | English | Nhẹ nhất, phù hợp CPU |
| `standard` | Chatterbox Standard | 500M | English | Có CFG và exaggeration, nặng hơn Turbo |
| `multilingual` | Chatterbox Multilingual | 500M | Danh sách từ `/api/v1/languages` | Không hỗ trợ tiếng Việt trong checkpoint hiện tại |
| `voice-conversion` | Chatterbox VC | — | Audio-to-audio | Chuyển nội dung audio sang giọng mục tiêu |

Ngôn ngữ giao diện tiếng Việt và ngôn ngữ sinh âm thanh là hai khái niệm tách biệt. API `/api/v1/tts` sinh tiếng Anh bằng Turbo mặc định.

## 4. Model cache trên ổ đĩa

Local API luôn dùng thư mục `models/` nằm cạnh `api_app.py`:

```python
PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")
```

`run_chatterbox_api.sh` cũng đặt:

```bash
export HF_HUB_CACHE="$PWD/models"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
```

Hệ quả:

- API không dùng cache mặc định `~/.cache/huggingface/hub`.
- API chạy offline mặc định và không tự tải Internet.
- Nếu model thiếu file, job sẽ thất bại thay vì tự download.
- Cho phép download model thiếu bằng `HF_HUB_OFFLINE=0 ./run_chatterbox_api.sh`.
- Di chuyển project sang đường dẫn khác vẫn dùng đúng thư mục `<project>/models`.

Desktop GUI đọc `model_cache_dir` từ `config/settings.json`; Local API luôn khóa cache vào `<project>/models`. Không nên giả định thay đổi Settings của Desktop sẽ đổi cache của API đang chạy.

## 5. Cấu hình chung

Cấu hình mặc định nằm trong `config/settings.py`; giá trị local được ghi vào `config/settings.json`.

| Key | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `export_dir` | `~/Downloads` | Thư mục xuất WAV |
| `model_cache_dir` | thư mục `models` cấu hình | Cache model cho Desktop |
| `language` | `🇻🇳 Tiếng Việt` | Ngôn ngữ giao diện |
| `device` | `auto` | Tự chọn CUDA, MPS hoặc CPU |
| `default_model` | `auto` (hoặc nano/turbo/standard) | Model mặc định khi khởi động |
| `max_chunk_chars` | `4000` | Giới hạn chia đoạn Desktop |
| `auto_unload_models` | `false` | Desktop tự clear model cũ khi đổi model |
| `cpu_threads` | tối đa 4 | Số CPU thread Desktop/API |
| `process_priority` | `low` | Giảm ưu tiên process Desktop |
| `max_vram_fraction` | `80` | Phần trăm VRAM tối đa nếu có CUDA |
| `force_gc_after_gen` | `true` | Thu gom bộ nhớ sau sinh audio |
| `max_batch_workers` | `2` | Số worker batch Desktop |

FastAPI có chính sách tài nguyên riêng:

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `CHATTERBOX_API_CPU_THREADS` | `2` | Số CPU thread PyTorch |
| `CHATTERBOX_API_DATA_DIR` | `/tmp/chatterbox-api` | File upload tạm và WAV kết quả |
| `CHATTERBOX_API_MAX_UPLOAD_BYTES` | `20971520` | Upload tối đa 20 MB |
| `HF_HUB_OFFLINE` | `1` từ launcher | Không truy cập Hugging Face Hub |

API đặt interop thread bằng `1`, chạy một audio job tại một thời điểm và không yêu cầu API key vì chỉ bind vào localhost.

## 6. Luồng Desktop GUI

```text
run_chatterbox_gui.sh
    → main.py
    → đọc config/settings.json
    → đặt HF_HOME và HF_HUB_CACHE
    → tạo ChatterboxEngine
    → tạo MainWindow và các tab
    → người dùng chọn model / nhập text / audio mẫu
    → UI chạy engine trong background thread
    → engine load hoặc tái sử dụng model
    → chia text theo max_chunk_chars
    → model.generate() từng đoạn
    → ghép tensor audio
    → lưu WAV và cleanup memory
    → audio player / history
```

`ChatterboxEngine` dùng lock nội bộ khi load model. Nếu `auto_unload_models=true`, engine clear model cũ khi chuyển sang model khác.

## 7. Luồng FastAPI

### 7.1 Khởi động

```text
run_chatterbox_api.sh
    → cd vào project
    → kích hoạt venv
    → khóa HF_HUB_CACHE=<project>/models
    → bật offline mặc định
    → uvicorn api_app:app trên 127.0.0.1:8000
    → tạo một background worker
```

Model chưa được load khi server vừa khởi động. Lần gọi job đầu tiên hoặc endpoint preload mới đọc model từ ổ đĩa vào RAM.

### 7.2 Vòng đời job

```text
POST endpoint
    → validate text và tham số
    → lưu upload vào /tmp/chatterbox-api/inputs
    → tạo job status=queued
    → đưa job_id vào queue
    → trả HTTP 202

Background worker
    → lấy một job
    → status=processing
    → giữ execution_lock
    → clear model khác khỏi RAM nếu cần
    → load model yêu cầu từ project/models
    → chạy inference
    → lưu /tmp/chatterbox-api/outputs/<job_id>.wav
    → status=completed hoặc failed
    → xóa upload tạm
    → gc.collect() và clear CUDA cache rỗng
```

Queue chỉ có một worker nhằm tránh nhiều model/job tranh chấp CPU, RAM hoặc VRAM. Khi job mới cần model khác, API đặt tất cả model cũ thành `None`, cleanup RAM, rồi mới load model mới. Tại mọi thời điểm API chỉ chủ động cache tối đa một model.

Cleanup sau job không unload model đang active. Nó chỉ thu hồi object tạm và CUDA cache không còn tham chiếu; job kế tiếp có thể chờ thêm một khoảng ngắn nhưng không bị thay đổi dữ liệu.

Trạng thái job:

```text
queued → processing → completed
                    ↘ failed
                    ↘ cancelled
```

Toàn bộ thông tin trạng thái job, metadata, tiến trình và benchmark được lưu bền vững vào SQLite (`jobs.db`) qua `JobStore`. Khi server khởi động lại:
- Các job bị treo ở trạng thái `queued` hoặc `processing` được tự động chuyển thành `failed` kèm thông báo lý do rõ ràng.
- Các job batch hoặc long-text bị gián đoạn có thể tiếp tục xử lý từ dòng còn thiếu qua `POST /api/v1/jobs/{job_id}/resume` mà không cần tổng hợp lại các dòng đã hoàn thành.
- Tiến trình sinh audio có thể được theo dõi trực tiếp theo thời gian thực qua kênh Server-Sent Events (SSE) tại `/api/v1/jobs/{job_id}/events`.
- Dữ liệu job cũ và file tạm được tự động dọn dẹp theo thời gian lưu trữ TTL (`retention_days`).

## 8. Danh sách API

Swagger UI: `http://127.0.0.1:8000/docs`.

### System, Diagnostics & Benchmarks

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/health` hoặc `/api/v1/health` | Device, CPU threads, queue, loaded model & cache key |
| `GET` | `/api/v1/diagnostics` | Báo cáo chi tiết phần cứng, GPU, RAM, disk cache và CUDA toolkit |
| `GET` | `/api/v1/benchmarks` | Lịch sử hiệu năng tổng hợp âm thanh (RTF, tốc độ xử lý, thời gian) |
| `POST` | `/api/v1/text/split` | Chia text theo ranh giới hợp lý, bảo toàn nội dung tuyệt đối |

### Sinh, chuyển đổi và ghép nối audio

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `POST` | `/api/v1/tts` | Turbo 350M mặc định |
| `POST` | `/api/v1/tts/turbo` | Turbo hoặc Nano qua field `model` |
| `POST` | `/api/v1/tts/standard` | Standard 500M |
| `POST` | `/api/v1/tts/multilingual` | Multilingual V3/V2 |
| `POST` | `/api/v1/tts/batch` | Sinh audio kịch bản hàng loạt, xuất file lẻ, gộp WAV và SRT/VTT |
| `POST` | `/api/v1/tts/long-text` | Sinh văn bản dài với cơ chế chia đoạn thông minh và ghép timeline |
| `POST` | `/api/v1/voice-conversion` | Voice Conversion (Audio-to-audio) |
| `POST` | `/api/v1/audio/merge` | Ghép nhiều job audio thành 1 file kèm khoảng lặng và BGM |
| `POST` | `/api/v1/batch/merge` | Alias cho audio merge từ Batch Studio |

Các endpoint sinh audio trả HTTP `202 Accepted` cùng `job.id`. Endpoint merge trả `200 OK` cùng `audio_url` file ghép.

### Character API (Quản lý Nhân vật, Giọng mẫu & Portability)

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/characters` | Lấy danh sách tất cả các nhân vật |
| `POST` | `/api/v1/characters` | Tạo nhân vật mới (JSON hoặc multipart kèm file mẫu) |
| `GET` | `/api/v1/characters/{id}` | Xem chi tiết hồ sơ nhân vật |
| `PATCH` | `/api/v1/characters/{id}` | Cập nhật thông số hoặc đặt nhân vật mặc định (`is_default`) |
| `DELETE` | `/api/v1/characters/{id}` | Xóa nhân vật và file âm thanh mẫu liên quan |
| `GET` | `/api/v1/characters/{id}/reference-audio` | Tải/phát file âm thanh mẫu của nhân vật |
| `GET` | `/api/v1/characters/{id}/export` | Xuất nhân vật & audio mẫu ra gói ZIP di động |
| `POST` | `/api/v1/characters/import` | Nhập nhân vật từ gói ZIP di động |

### Model Management & Preflight Integrity

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/languages` | Danh sách ngôn ngữ Multilingual hỗ trợ |
| `GET` | `/api/v1/models` | Danh sách model, kích thước, tính năng và trạng thái nạp |
| `GET` | `/api/v1/models/preflight` | Kiểm tra tính toàn vẹn checkpoint của toàn bộ models trước khi chạy |
| `GET` | `/api/v1/models/{name}/preflight` | Kiểm tra tính toàn vẹn checkpoint của 1 model cụ thể |
| `POST` | `/api/v1/models/{name}/load` | Preload model vào RAM/VRAM với cache key phân biệt thiết bị |
| `DELETE` | `/api/v1/models/{name}` | Giải phóng model khỏi RAM/VRAM |
| `DELETE` | `/api/v1/models/{name}/disk` | Xóa hoàn toàn checkpoint của model khỏi ổ đĩa để giải phóng dung lượng |

Tên model hợp lệ: `standard`, `turbo`, `nano`, `multilingual`, `voice-conversion`.

### Job Lifecycle, SSE & Resumption

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/jobs` | Danh sách job; lọc bằng `?status=completed` |
| `GET` | `/api/v1/jobs/{job_id}` | Chi tiết trạng thái và thông số benchmark |
| `GET` | `/api/v1/jobs/{job_id}/events` | Server-Sent Events (SSE) stream tiến độ sinh thời gian thực |
| `POST` | `/api/v1/jobs/{job_id}/resume` | Tiếp tục sinh batch/long-text bị gián đoạn từ dòng còn thiếu |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Hủy job đang trong hàng đợi hoặc đang xử lý |
| `GET` | `/api/v1/jobs/{job_id}/audio` | Tải WAV khi completed |
| `GET` | `/api/v1/jobs/{job_id}/srt` | Tải phụ đề SRT |
| `GET` | `/api/v1/jobs/{job_id}/zip` | Tải gói ZIP xuất khẩu (chứa WAV tổng, WAV lẻ, SRT, manifest JSON) |
| `DELETE` | `/api/v1/jobs/{job_id}` | Xóa job và toàn bộ file audio kết quả |

### Cài đặt và Hệ thống

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/settings` | Đọc cấu hình settings hiện tại |
| `POST` | `/api/v1/settings` | Cập nhật cấu hình settings |
| `POST` | `/api/v1/system/clean-tmp` | Dọn dẹp toàn bộ file tạm trong thư mục `tmp/` của dự án (bảo vệ CSDL) |

Không thể xóa job đang `queued` hoặc `processing`.

## 9. API chia văn bản

Request JSON:

```json
{
  "text": "Original English text...",
  "min_chars": 200,
  "max_chars": 500
}
```

Thuật toán:

1. Không trim hoặc chuẩn hóa input.
2. Ưu tiên cắt sau `.`, `!`, `?`, `;`, `:`, hoặc newline.
3. Nếu không có dấu câu phù hợp, cắt tại whitespace gần `max_chars` nhất.
4. Nếu không có whitespace, cắt cứng tại `max_chars`.
5. Đoạn cuối có thể ngắn hơn `min_chars`.

Mỗi chunk có `index`, `start`, `end`, `text`. Điều kiện luôn được kiểm thử:

```python
"".join(chunk["text"] for chunk in chunks) == original_text
```

## 10. Ví dụ flow client API

```bash
# 1. Tạo Turbo job
curl -X POST http://127.0.0.1:8000/api/v1/tts \
  -F 'text=Hello from the local Chatterbox Turbo API.'

# 2. Kiểm tra trạng thái
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID

# 3. Tải kết quả
curl -o output.wav \
  http://127.0.0.1:8000/api/v1/jobs/JOB_ID/audio
```

Client nên poll trạng thái với khoảng nghỉ hợp lý, ví dụ 1–3 giây, thay vì gọi liên tục.

## 11. Chính sách tài nguyên khuyến nghị

Máy local hiện chạy CPU nên cấu hình ưu tiên ổn định:

- Dùng Turbo 350M mặc định; chuyển Nano nếu máy vẫn lag.
- Giữ `CHATTERBOX_API_CPU_THREADS=2`.
- Chỉ chạy một trong Desktop, Web hoặc API khi inference.
- Chia text thành đoạn 200–500 ký tự.
- Không preload nhiều model; API tự clear model cũ.
- Theo dõi `free -h` và swap trước khi chạy Standard/Multilingual.
- Standard và Multilingual nặng hơn, có thể làm máy phản hồi chậm khi RAM thấp.

## 12. File tạm và dữ liệu tồn tại

| Dữ liệu | Vị trí | Vòng đời |
| --- | --- | --- |
| Upload API | `/tmp/chatterbox-api/inputs` | Xóa sau job |
| WAV API | `/tmp/chatterbox-api/outputs` | Xóa qua DELETE job hoặc thủ công |
| Job metadata | RAM process API | Mất khi restart |
| Model disk cache | `<project>/models` | Giữ giữa các lần restart |
| Model RAM cache | RAM process | Tối đa một model, mất khi restart |
| Desktop settings | `config/settings.json` | Giữ local, không commit |
| Desktop log | `chatterbox_studio.log` | Giữ local, không commit |

## 13. Giới hạn hiện tại

- API chỉ bind `127.0.0.1` và không có authentication.
- Job store chưa persistent.
- Queue nằm trong một process, không dùng Redis/Celery.
- Không có endpoint hủy job đang chạy.
- API chưa tự ghép WAV từ nhiều text chunk.
- Không có TTL tự động xóa output WAV.
- Multilingual checkpoint hiện không hỗ trợ tiếng Việt; tiếng Việt chỉ dùng cho giao diện.

Nếu cần public API hoặc nhiều máy client, cần bổ sung authentication, rate limit, CORS có giới hạn, persistent job store và reverse proxy trước khi bind ra mạng ngoài.

## 14. Kiểm tra vận hành

```bash
# API health
curl http://127.0.0.1:8000/health

# Model cache project
du -sh models

# RAM và swap
free -h

# Process đang giữ port
ss -ltnp | rg ':7860|:8000'

# Kiểm tra Python và launcher
source venv/bin/activate
PYTHONPATH=src python3 -m py_compile api_app.py
bash -n run_chatterbox_api.sh
```

## 15. Test suite

Test API dùng `unittest`, FastAPI `TestClient` và model giả nên không tải checkpoint hoặc chạy inference thật.

```bash
source venv/bin/activate
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Bộ test hiện kiểm tra:

- Health và chính sách CPU/Turbo mặc định.
- OpenAPI có đầy đủ public endpoints.
- Chia text bảo toàn Unicode, whitespace và vị trí ký tự.
- Từ chối khoảng `min_chars`/`max_chars` không hợp lệ.
- Queue Turbo mặc định, hoàn thành job và tải WAV.
- Voice Conversion cleanup upload tạm.
- Inference lỗi chuyển job sang `failed`.
- Load model mới giải phóng model cũ nhưng cleanup nhẹ giữ model active.
- Lọc, tải và xóa completed job.
- Character JSON CRUD, PATCH voice từng phần và cấm field model.
- Reference audio tùy chọn và vòng đời file.
- `character_id` TTS, voice mapping, default character resolution và audio precedence.

## 16. Character Voice Preset & RESTful API

Character là voice preset độc lập model và được lưu dưới dạng JSON:

```text
data/characters.json
```

Reference audio là tùy chọn:

```text
data/characters/<character_id>/reference.<ext>
```

Character hỗ trợ cờ `is_default: true/false`. Khi một Character được đặt làm Mặc định, nếu TTS request hoặc GUI không truyền `character_id`, hệ thống sẽ tự động giải phóng voice profile và audio mẫu từ Character mặc định này.

### 5 API RESTful Chuẩn trong Swagger `/docs`:

1. `GET /api/v1/characters`: Lấy danh sách toàn bộ Character (bao gồm thuộc tính `is_default`).
2. `POST /api/v1/characters`: Tạo Character mới.
3. `GET /api/v1/characters/{character_id}`: Lấy chi tiết thông tin 1 Character.
4. `PATCH /api/v1/characters/{character_id}`: **Cập nhật đa năng** (Tên, Ngôn ngữ, Mô tả, Voice Profile, **Đặt/Bỏ Mặc định `is_default`**, và **Upload/Cập nhật file audio mẫu `reference_audio`**).
5. `DELETE /api/v1/characters/{character_id}`: Xóa Character.

Character không chấp nhận field `model`. Model vẫn được quyết định bởi endpoint TTS. Voice profile gồm:

- `expressiveness`: ánh xạ sang exaggeration cho Standard/Multilingual.
- `pace`: ánh xạ sang CFG weight cho Standard/Multilingual.
- `stability`: ánh xạ sang temperature cho các model TTS.
- `seed`: giữ kết quả sampling ổn định hơn.

Flow giải quyết giọng đọc (Voice Resolution):

```text
TTS request có character_id (hoặc tự động lấy Default Character khi character_id rỗng)
    → đọc Character JSON
    → lấy voice profile & reference audio nếu Character có
    → nếu request có audio_prompt thì ghi đè reference Character
    → nếu request có generation parameter thì ghi đè voice profile
    → tạo job queue như bình thường
```

Character không có reference vẫn sử dụng được; model dùng built-in voice cùng voice profile. Job response chỉ chứa `character_id` và effective parameters, không lộ đường dẫn reference audio trên filesystem.

### Tính năng Desktop GUI liên quan:
- **Tab Character**: Hỗ trợ chọn ngôn ngữ dropdown, nút "🔊 Nghe thử giọng" xem trước âm thanh trước khi tạo, nút "⭐ Đặt Mặc định" và Menu chuột phải (Context Menu).
- **TTS Studio & Batch Studio**: Thêm Checkbox "⭐ Sử dụng Character mặc định" tự động áp dụng thông số của Character mặc định khi được chọn.
