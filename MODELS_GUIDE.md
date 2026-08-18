# 📚 Hướng dẫn Chi tiết & Phân loại các Mô hình Chatterbox TTS

Tài liệu này cung cấp thông tin chi tiết, thông số kỹ thuật, tính năng nổi bật và cách chọn mô hình phù hợp nhất cho từng nhu cầu sử dụng trong ứng dụng **Chatterbox TTS Studio**.

---

## 📊 Bảng So sánh Tổng quan các Model

| Tên Mô hình | Kích thước | Ngôn ngữ | Tốc độ & Bộ nhớ | Tính năng Nổi bật | Phù hợp với nhu cầu |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Chatterbox Standard (500M)** | **500M** | Tiếng Anh | Trung bình (Yêu cầu GPU/CPU) | • Voice cloning chất lượng cao<br>• Tinh chỉnh **Exaggeration** & **CFG Weight** | Đọc sách nói (Audiobooks), diễn thuyết, báo chí, tài liệu dài |
| **Chatterbox Turbo (350M)** | **350M** | Tiếng Anh | **Siêu nhanh** (1-step decoder) | • **ĐỘC QUYỀN Paralinguistic Tags** (`[laugh]`, `[cough]`...)<br>• Tiết kiệm VRAM | Voice Agents thời gian thực, Chatbot thoại, lồng tiếng kịch |
| **Chatterbox Nano (110M)** | **110M** | Tiếng Anh | **Cực nhẹ** (3x realtime trên 8 CPU cores) | • Hỗ trợ đầy đủ **Paralinguistic Tags**<br>• Tối ưu riêng cho CPU | Máy không có GPU NVIDIA, chạy trực tiếp trên laptop/CPU |
| **Chatterbox Multilingual V3** | **500M** | **23+ Ngôn ngữ** | Trung bình | • Voice cloning đa ngôn ngữ<br>• Giảm hiện tượng lặp từ/ảo giác | Ứng dụng toàn cầu, dịch thuật & phát âm đa ngôn ngữ |

---

## 🔍 Chi tiết từng Mô hình & Cách tối ưu

### 1. 📌 Chatterbox Standard (500M)
* **Mô tả:** Mô hình tiêu chuẩn ban đầu trong họ Chatterbox. Tối ưu cho chất lượng âm thanh trung thực và khả năng sao chép giọng nói mẫu (Zero-shot Voice Cloning).
* **Mẹo tối ưu cảm xúc & nhấn nhá:**
  * **Exaggeration (Độ biểu cảm):** Chỉnh lên `0.9` – `1.3` để giọng đọc lên trầm xuống bổng, nhấn giọng kịch tính.
  * **CFG Weight (Bám sát văn bản):** Giảm xuống `0.3` – `0.5` để giọng đọc uốn nắn tự do, bay bổng hơn.
  * **File giọng mẫu (`ref_audio`):** Chọn file mẫu 5s–10s có thái độ vui vẻ / hào hứng ➔ AI sẽ sao chép cả thái độ đó vào câu đọc mới.
* **Code mẫu Python:**
  ```python
  from chatterbox.tts import ChatterboxTTS
  import torchaudio as ta

  model = ChatterboxTTS.from_pretrained(device="cuda") # hoặc "mps" / "cpu"
  wav = model.generate("Hello world, welcome to Chatterbox!", exaggeration=0.8, cfg_weight=0.5)
  ta.save("output_standard.wav", wav, model.sr)
  ```

---

### 2. ⚡ Chatterbox Turbo (350M - Fast)
* **Mô tả:** Mô hình thế hệ mới tối ưu cho độ trễ thấp và tốc độ xử lý tức thì (sub-200ms).
* **Tính năng ĐỘC QUYỀN: Paralinguistic Tags (Âm thanh biểu cảm phi ngôn ngữ):**
  Hỗ trợ chèn các thẻ âm thanh sinh học thật vào câu nói:
  * `[laugh]`: Tiếng cười lớn
  * `[chuckle]`: Tiếng cười khẽ / cười mỉm
  * `[sigh]`: Tiếng thở dài
  * `[gasp]`: Tiếng hít vào ngạc nhiên
  * `[cough]`: Tiếng ho
  * `[groan]`: Tiếng than vãn
  * `[sniff]`: Tiếng sụt sịt
  * `[clear throat]`: Tiếng e hèm
  * `[shush]`: Tiếng suỵt
  * `[whisper]`: Giọng nói thì thầm
  * `[yawn]`: Tiếng ngáp
* **Code mẫu Python:**
  ```python
  from chatterbox.tts_turbo import ChatterboxTurboTTS
  import torchaudio as ta

  model = ChatterboxTurboTTS.from_pretrained(device="cuda") # hoặc "mps" / "cpu"
  text = "Hi there [chuckle], I am calling back about your order [cough], is now a good time?"
  wav = model.generate(text, audio_prompt_path="sample_ref.wav")
  ta.save("output_turbo.wav", wav, model.sr)
  ```

---

### 3. 🍃 Chatterbox Nano (110M - Light/CPU)
* **Mô tả:** Mô hình siêu nhỏ gọn dành cho các thiết bị máy tính cá nhân hoặc máy chủ không có card đồ họa NVIDIA. Chạy nhanh gấp 3 lần thời gian thực trên CPU 8 nhân.
* **Đặc điểm:** Thừa hưởng toàn bộ kiến trúc và **hỗ trợ đầy đủ các thẻ biểu cảm Paralinguistic Tags** như bản Turbo.
* **Code mẫu Python:**
  ```python
  from chatterbox.tts_turbo import ChatterboxTurboTTS
  import torchaudio as ta

  # Nạp mô hình Nano bằng cờ nano=True
  model = ChatterboxTurboTTS.from_pretrained(device="cpu", nano=True)
  wav = model.generate("Hello there [laugh]!", audio_prompt_path="sample_ref.wav")
  ta.save("output_nano.wav", wav, model.sr)
  ```

---

### 4. 🌐 Chatterbox Multilingual V3 (500M)
* **Mô tả:** Mô hình đa ngôn ngữ thế hệ V3 hỗ trợ trên 23 ngôn ngữ (Anh, Pháp, Đức, Tây Ban Nha, Trung, Nhật, Hàn,...).
* **Ứng dụng:** Chuyển đổi ngôn ngữ giọng nói, bản ngữ hóa nội dung video / phim ảnh.

---

## 💡 Hướng dẫn Nhanh: Khi nào nên chọn Model nào?

1. **Nếu bạn muốn âm thanh biểu cảm có tiếng cười `[laugh]`, tiếng ho `[cough]`, tiếng thở dài:**
   👉 Chọn **Chatterbox Turbo (350M)** (có GPU) hoặc **Chatterbox Nano (110M)** (chạy CPU).

2. **Nếu bạn muốn đọc tài liệu, sách nói dài, cần chỉnh Exaggeration / CFG nhấn nhá mượt mà:**
   👉 Chọn **Chatterbox Standard (500M)**.

3. **Nếu máy bạn KHÔNG CÓ card đồ họa NVIDIA (Chỉ có CPU):**
   👉 Chọn **Chatterbox Nano (110M)** để có tốc độ xử lý mượt mà nhất.
