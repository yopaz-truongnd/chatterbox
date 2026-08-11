# Kiến trúc và luồng hoạt động Chatterbox TTS Studio

Tài liệu này mô tả cấu hình, thành phần, model, entrypoint và luồng xử lý hiện tại của toàn bộ dự án. Tài liệu cài đặt từng bước nằm trong `SETUP_GUIDE.md`; hướng dẫn chọn model nằm trong `MODELS_GUIDE.md`.

## 1. Tổng quan

Dự án cung cấp ba cách chạy độc lập:

| Chế độ | Entrypoint | Launcher | Địa chỉ | Mục đích |
| --- | --- | --- | --- | --- |
| Desktop GUI | `main.py` | `run_chatterbox_gui.sh` | Cửa sổ Tkinter | Studio đầy đủ trên desktop |
| Web UI | `web_app.py` | `run_chatterbox_web.sh` | `127.0.0.1:7860` | Giao diện Gradio tiếng Việt |
| Local API | `api_app.py` | `run_chatterbox_api.sh` | `127.0.0.1:8000` | Tích hợp script và ứng dụng khác |

Ba chế độ là ba process riêng. Nếu chạy đồng thời, mỗi process có model cache trong RAM riêng và làm tăng mức sử dụng RAM. Trên máy CPU/RAM hạn chế, chỉ nên chạy một chế độ tại một thời điểm.

## 2. Cấu trúc thư mục

```text
chatterbox/
├── api_app.py                 # FastAPI, queue, model cache RAM và endpoints
├── web_app.py                 # Gradio Web UI hợp nhất
├── main.py                    # Desktop GUI entrypoint
├── core/
│   └── chatterbox_engine.py   # Engine dùng bởi Desktop GUI
├── ui/
│   ├── main_window.py         # Cửa sổ chính Tkinter
│   ├── tabs/                  # TTS, multilingual, VC, batch, history, settings
│   └── components/            # Audio player và waveform
├── config/
│   ├── constants.py           # Theme, tags, preset và danh sách ngôn ngữ
│   ├── settings.py            # Default settings và SettingsManager
│   └── settings.json          # Cấu hình local, không commit
├── src/chatterbox/
│   ├── tts.py                 # Standard 500M
│   ├── tts_turbo.py           # Turbo 350M và Nano 110M
│   ├── mtl_tts.py             # Multilingual
│   └── vc.py                  # Voice Conversion
├── models/                    # Hugging Face Hub cache của project
├── utils/                     # Logging, audio, threading, text và file helpers
├── run_chatterbox_gui.sh
├── run_chatterbox_web.sh
└── run_chatterbox_api.sh
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

Desktop GUI đọc `model_cache_dir` từ `config/settings.json`. Web UI hiện đọc settings để hiển thị/lưu nhưng các hàm `from_pretrained()` phụ thuộc biến Hugging Face của process. Không nên giả định thay đổi Settings trong một process sẽ đổi cache của process khác đang chạy.

## 5. Cấu hình chung

Cấu hình mặc định nằm trong `config/settings.py`; giá trị local được ghi vào `config/settings.json`.

| Key | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `export_dir` | `~/Downloads` | Thư mục xuất WAV |
| `model_cache_dir` | thư mục `models` cấu hình | Cache model cho Desktop |
| `language` | `🇻🇳 Tiếng Việt` | Ngôn ngữ giao diện |
| `device` | `auto` | Tự chọn CUDA hoặc CPU |
| `default_startup_model` | Standard 500M | Model mặc định Desktop |
| `max_chunk_chars` | `4000` | Giới hạn chia đoạn Desktop |
| `auto_unload_models` | `false` | Desktop tự clear model cũ khi đổi model |
| `cpu_threads_limit` | tối đa 4 | Số CPU thread Desktop |
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

## 7. Luồng Web UI

```text
run_chatterbox_web.sh
    → kích hoạt venv
    → web_app.py
    → Gradio Blocks tại 127.0.0.1:7860
    → model được lazy-load theo tab đầu tiên sử dụng
    → generate TTS / multilingual / VC
    → Gradio trả audio waveform cho trình duyệt
```

Web UI gồm bốn tab:

- TTS Studio: giao diện tiếng Việt, sinh tiếng Anh.
- Multilingual TTS: chọn ngôn ngữ checkpoint hỗ trợ.
- Voice Conversion: upload source và target voice.
- Settings: cấu hình local và ngôn ngữ giao diện.

Web UI và API không chia sẻ object model trong RAM, kể cả khi chạy trên cùng máy.

## 8. Luồng FastAPI

### 8.1 Khởi động

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

### 8.2 Vòng đời job

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
```

Job chỉ tồn tại trong RAM của process. Restart API sẽ mất danh sách job, nhưng các WAV cũ trong `CHATTERBOX_API_DATA_DIR/outputs` không tự động bị xóa.

## 9. Danh sách API

Swagger UI: `http://127.0.0.1:8000/docs`.

### System và text

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/health` | Device, CPU threads, queue và model đang load |
| `POST` | `/api/v1/text/split` | Chia text theo ranh giới hợp lý, bảo toàn nội dung tuyệt đối |

### Sinh và chuyển đổi audio

| Method | Endpoint | Model |
| --- | --- | --- |
| `POST` | `/api/v1/tts` | Turbo 350M mặc định |
| `POST` | `/api/v1/tts/turbo` | Turbo hoặc Nano qua field `model` |
| `POST` | `/api/v1/tts/standard` | Standard 500M |
| `POST` | `/api/v1/tts/multilingual` | Multilingual |
| `POST` | `/api/v1/voice-conversion` | Voice Conversion |

Các endpoint audio trả HTTP `202 Accepted` cùng `job.id`, không trả WAV ngay trong response đầu tiên.

### Model

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/languages` | Ngôn ngữ Multilingual hỗ trợ |
| `GET` | `/api/v1/models` | Model và trạng thái loaded |
| `POST` | `/api/v1/models/{name}/load` | Preload model; clear model khác trước |
| `DELETE` | `/api/v1/models/{name}` | Unload model khỏi RAM |

Tên model hợp lệ: `standard`, `turbo`, `nano`, `multilingual`, `voice-conversion`.

### Job

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/v1/jobs` | Danh sách job; lọc bằng `?status=completed` |
| `GET` | `/api/v1/jobs/{job_id}` | Chi tiết trạng thái |
| `GET` | `/api/v1/jobs/{job_id}/audio` | Tải WAV khi completed |
| `DELETE` | `/api/v1/jobs/{job_id}` | Xóa job terminal và WAV |

Không thể xóa job đang `queued` hoặc `processing`.

## 10. API chia văn bản

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

## 11. Ví dụ flow client API

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

## 12. Chính sách tài nguyên khuyến nghị

Máy local hiện chạy CPU nên cấu hình ưu tiên ổn định:

- Dùng Turbo 350M mặc định; chuyển Nano nếu máy vẫn lag.
- Giữ `CHATTERBOX_API_CPU_THREADS=2`.
- Chỉ chạy một trong Desktop, Web hoặc API khi inference.
- Chia text thành đoạn 200–500 ký tự.
- Không preload nhiều model; API tự clear model cũ.
- Theo dõi `free -h` và swap trước khi chạy Standard/Multilingual.
- Standard và Multilingual nặng hơn, có thể làm máy phản hồi chậm khi RAM thấp.

## 13. File tạm và dữ liệu tồn tại

| Dữ liệu | Vị trí | Vòng đời |
| --- | --- | --- |
| Upload API | `/tmp/chatterbox-api/inputs` | Xóa sau job |
| WAV API | `/tmp/chatterbox-api/outputs` | Xóa qua DELETE job hoặc thủ công |
| Job metadata | RAM process API | Mất khi restart |
| Model disk cache | `<project>/models` | Giữ giữa các lần restart |
| Model RAM cache | RAM process | Tối đa một model, mất khi restart |
| Desktop settings | `config/settings.json` | Giữ local, không commit |
| Desktop log | `chatterbox_studio.log` | Giữ local, không commit |

## 14. Giới hạn hiện tại

- API chỉ bind `127.0.0.1` và không có authentication.
- Job store chưa persistent.
- Queue nằm trong một process, không dùng Redis/Celery.
- Không có endpoint hủy job đang chạy.
- API chưa tự ghép WAV từ nhiều text chunk.
- Không có TTL tự động xóa output WAV.
- Web UI và API chưa dùng chung model service.
- Multilingual checkpoint hiện không hỗ trợ tiếng Việt; tiếng Việt chỉ dùng cho giao diện.

Nếu cần public API hoặc nhiều máy client, cần bổ sung authentication, rate limit, CORS có giới hạn, persistent job store và reverse proxy trước khi bind ra mạng ngoài.

## 15. Kiểm tra vận hành

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
PYTHONPATH=src python3 -m py_compile api_app.py web_app.py
bash -n run_chatterbox_api.sh
bash -n run_chatterbox_web.sh
```

## 16. Test suite

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
