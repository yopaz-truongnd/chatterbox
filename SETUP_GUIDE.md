# Hướng dẫn Cài đặt & Khởi chạy Chatterbox TTS Studio

Tài liệu ghi nhớ tóm tắt các bước thiết lập môi trường Python, cài đặt thư viện và khởi chạy dự án **Chatterbox TTS** trên Linux và macOS.

## Cài đặt nhanh trên macOS (Apple Silicon)

```bash
brew install python@3.11
/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
./run_chatterbox_gui.sh
```

Ứng dụng tự ưu tiên Metal (`mps`) trên Apple Silicon và chuyển về CPU nếu MPS không khả dụng. Có thể ép API dùng thiết bị cụ thể bằng `CHATTERBOX_DEVICE=mps ./run_chatterbox_api.sh`.

---

## 1. Yêu cầu Tiền đề (Prerequisites)

Cài đặt các gói phụ thuộc hệ thống cần thiết cho Python Virtual Environment và Giao diện GUI Tkinter:

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk git
```

---

## 2. Thiết lập Môi trường ảo (Virtual Environment)

Do Linux (Python 3.12+) bảo vệ môi trường hệ thống (chính sách PEP 668 `externally-managed-environment`), cần tạo một môi trường ảo riêng cho dự án:

```bash
# 1. Truy cập thư mục dự án
cd /var/www/chatterbox

# 2. Tạo môi trường ảo có tên 'venv'
python3 -m venv venv

# 3. Kích hoạt môi trường ảo (BẮT BUỘC trước mỗi lần làm việc)
source venv/bin/activate
```

> **Lưu ý:** Khi kích hoạt thành công, đầu dòng lệnh Terminal sẽ hiển thị tiền tố `(venv)`.

---

## 3. Cài đặt Thư viện Phụ thuộc (Dependencies)

### 💡 Lưu ý cho máy KHÔNG có GPU NVIDIA (Chỉ chạy CPU)
Mặc định `pip install torch` sẽ tải phiên bản PyTorch kèm thư viện NVIDIA CUDA rất nặng (~2-3 GB). Đối với máy chỉ có CPU:

```bash
# Nâng cấp pip
pip install --upgrade pip

# Cài đặt PyTorch phiên bản CPU-Only (Nhẹ hơn rất nhiều, chỉ ~200MB - 300MB)
pip install torch torchaudio pygame --index-url https://download.pytorch.org/whl/cpu

# Cài đặt các thư viện còn lại của dự án
pip install -e .
```

---

### 🎮 Cho máy CÓ GPU NVIDIA (Chạy CUDA)
```bash
pip install --upgrade pip
pip install -e .
```

---

## 4. Các Chế độ Khởi chạy Dự án

### 🟢 Chế độ 1: Desktop GUI (Tkinter Studio)
Dành cho giao diện cửa sổ ứng dụng máy tính:

```bash
# Đảm bảo đã kích hoạt môi trường ảo:
source venv/bin/activate

# Chạy bằng script launcher:
chmod +x run_chatterbox_gui.sh
./run_chatterbox_gui.sh

# Hoặc chạy trực tiếp bằng Python:
python3 main.py
```

*Dự án sẽ tự động phát hiện không có GPU (`torch.cuda.is_available() == False`) và tự động chuyển sang chế độ CPU.*

---

### 🌐 Chế độ 2: Các Gradio Demo riêng lẻ

```bash
# 1. Chatterbox Turbo Web App (English, Siêu nhanh)
python3 gradio_tts_turbo_app.py

# 2. Multilingual Web App (Đa ngôn ngữ 23+ tiếng)
python3 multilingual_app.py

# 3. Voice Conversion Web App (Chuyển đổi giọng nói)
python3 gradio_vc_app.py
```

---

### ⚡ Chế độ 3: Python Script (CLI / Code mẫu)

```bash
python3 example_tts_turbo.py
```

---

## 5. Tóm tắt Lệnh Khởi chạy Nhanh (Cheat Sheet)

Mỗi lần khởi động máy hoặc mở Terminal mới:

- **Khởi chạy Giao diện Desktop GUI (Tkinter):**
```bash
cd /var/www/chatterbox
source venv/bin/activate
./run_chatterbox_gui.sh
```

---

## 6. FastAPI cho tích hợp ứng dụng

Khởi chạy API độc lập tại `http://127.0.0.1:8000`:

```bash
chmod +x run_chatterbox_api.sh
./run_chatterbox_api.sh
```

- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

Tạo job TTS tiếng Anh bằng Turbo 350M mặc định:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tts \
  -F 'text=Hello from the Chatterbox Turbo API.'
```

Có thể gửi thêm audio mẫu bằng `-F 'audio_prompt=@voice.wav'`. Response trả về `job_id`; dùng ID đó để kiểm tra trạng thái và tải WAV:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl -o output.wav http://127.0.0.1:8000/api/v1/jobs/JOB_ID/audio
```

### API mở rộng

Turbo hoặc Nano (endpoint `/api/v1/tts` cũng mặc định Turbo):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tts/turbo \
  -F 'text=Hello [laugh], this is Chatterbox Turbo.' \
  -F 'model=turbo'
```

Multilingual:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tts/multilingual \
  -F 'text=Hello from the multilingual model.' \
  -F 'language_id=en'
```

Voice Conversion:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/voice-conversion \
  -F 'source_audio=@source.wav' \
  -F 'target_voice=@target.wav'
```

Quản lý model và job:

```bash
curl http://127.0.0.1:8000/api/v1/languages
curl http://127.0.0.1:8000/api/v1/models
curl -X POST http://127.0.0.1:8000/api/v1/models/turbo/load
curl -X DELETE http://127.0.0.1:8000/api/v1/models/turbo
curl 'http://127.0.0.1:8000/api/v1/jobs?status=completed'
curl -X DELETE http://127.0.0.1:8000/api/v1/jobs/JOB_ID
```

API chạy một job audio tại một thời điểm để tránh tranh chấp GPU/VRAM. Endpoint load model có thể mất thời gian ở lần đầu do tải checkpoint.

Chia văn bản thành các đoạn 200–500 ký tự mà không sửa, trim hay chuẩn hóa nội dung:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/text/split \
  -H 'Content-Type: application/json' \
  -d '{"text":"Your long original text...","min_chars":200,"max_chars":500}'
```

Nối `text` của toàn bộ `chunks` theo thứ tự sẽ khôi phục chính xác text ban đầu. Standard 500M vẫn có tại `POST /api/v1/tts/standard`. API dùng 2 CPU thread theo mặc định; có thể đổi bằng `CHATTERBOX_API_CPU_THREADS`. Khi load model mới, model đang giữ trong RAM sẽ được unload trước.

### Cache model của API

API dùng trực tiếp Hugging Face cache trong thư mục dự án `models/` và chạy offline mặc định, vì vậy model đã có sẽ không được tải lại từ Internet.

Nếu cần tải một model còn thiếu, cho phép kết nối trong lần chạy đó:

```bash
HF_HUB_OFFLINE=0 ./run_chatterbox_api.sh
```

---

## 7. Chạy Test

Test suite của Local API nằm tại `tests/test_api_app.py` và dùng `unittest` có sẵn trong Python:

```bash
cd /var/www/chatterbox
source venv/bin/activate
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Không cần chạy API trước khi test. FastAPI `TestClient` tự khởi tạo ứng dụng trong process test.

Test sử dụng model giả:

- Không download checkpoint từ Hugging Face.
- Không load Turbo, Nano, Standard hoặc Multilingual thật vào RAM.
- Không chạy inference thật.
- WAV nhỏ được tạo trong temporary directory và tự xóa sau test.

Kết quả thành công có dạng:

```text
Ran 16 tests in ...s

OK
```

Các nhóm hành vi được kiểm tra:

- Health, CPU thread và Turbo 350M mặc định.
- OpenAPI và danh sách endpoint.
- Chia text 200–500 ký tự, bảo toàn Unicode và whitespace.
- Queue, trạng thái `completed`/`failed` và tải WAV.
- Cleanup upload Voice Conversion.
- Chỉ giữ một model trong RAM khi chuyển model.
- Lọc và xóa completed job.
- Character JSON CRUD không chứa model.
- Reference audio tùy chọn: thêm, tải, thay và xóa.
- `character_id` áp dụng voice profile/reference và upload request được ưu tiên.

Xem mô tả chi tiết tại `PROJECT_ARCHITECTURE.md`, mục **Test suite**.

---

## 8. Character Voice Preset

Character lưu cấu hình voice độc lập model trong `data/characters.json`. Reference audio là tùy chọn và được quản lý riêng.

Tạo Character không có reference audio:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/characters \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"Sarah",
    "description":"Calm support voice",
    "language":"en",
    "tags":["female","calm"],
    "notes":"Neutral support style",
    "voice":{
      "expressiveness":0.5,
      "pace":0.5,
      "stability":0.7,
      "seed":12345
    }
  }'
```

Thêm hoặc thay reference audio:

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/characters/CHARACTER_ID/reference-audio \
  -F 'reference_audio=@voice.wav'
```

Sinh TTS bằng Character:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tts \
  -F 'text=Hello, how may I help you today?' \
  -F 'character_id=CHARACTER_ID'
```

Thứ tự ưu tiên audio: `audio_prompt` trong TTS request, reference audio Character, sau cùng là giọng mặc định model. Tham số TTS gửi trực tiếp ưu tiên hơn voice profile Character.

Các endpoint:

```text
POST   /api/v1/characters
GET    /api/v1/characters
GET    /api/v1/characters/{id}
PATCH  /api/v1/characters/{id}
DELETE /api/v1/characters/{id}
PUT    /api/v1/characters/{id}/reference-audio
GET    /api/v1/characters/{id}/reference-audio
DELETE /api/v1/characters/{id}/reference-audio
```
