# Hướng dẫn Cài đặt & Khởi chạy Chatterbox TTS Studio

Tài liệu ghi nhớ tóm tắt các bước thiết lập môi trường Python, cài đặt thư viện và khởi chạy dự án **Chatterbox TTS** trên Linux (Ubuntu / Debian).

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

### 🌐 Chế độ 2: Web Interface (Gradio App)
Dành cho việc trải nghiệm qua giao diện trình duyệt Web:

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

Mỗi lần khởi động máy hoặc mở Terminal mới để chạy Desktop GUI:

```bash
cd /var/www/chatterbox
source venv/bin/activate
./run_chatterbox_gui.sh
```
