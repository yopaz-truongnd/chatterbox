# Domain 02: Batch Studio, Script Parsing & Dual-Critic QC

Tài liệu hướng dẫn xử lý kịch bản nhiều dòng, ghép âm thanh, sinh phụ đề SRT, và hệ thống kiểm định chất lượng 2 lớp (Signal QC + Whisper STT Critic).

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - Phân tích kịch bản nhiều dòng từ văn bản thô (.txt, .md, .srt) qua `services/script_parser.py`.
  - Điều phối render từng phân đoạn (segment) và tính toán khoảng lặng (pause duration).
  - **Kiểm định chất lượng 2 lớp (Dual-Critic QC)**:
    - **Lớp 1 - Tín hiệu (Signal QC)**: Phát hiện khoảng lặng thừa (silence), âm lượng RMS quá nhỏ/to, méo tiếng (clipping), Crest factor. Tự động sửa (`auto_fix_audio_signal`: cắt tỉa silence, chuẩn hóa RMS -19dB, limiter).
    - **Lớp 2 - Nội dung (Whisper STT Critic)**: Nhận dạng giọng nói (ASR), tính toán Word Error Rate (WER), phát hiện từ bị nuốt (dropped words), lặp từ (stutter), đo tốc độ đọc thực tế (WPM).
  - Đánh giá nhiều ứng viên (multi-candidate evaluation) và chọn phiên bản tốt nhất (60% Content + 40% Signal).
  - Ghép các đoạn đạt chuẩn (crossfade, ghép BGM ducking), xuất file WAV hoàn chỉnh, file phụ đề `.srt`, và file nén `.zip`.
- **KHÔNG thuộc phạm vi**:
  - Đạo diễn kịch bản 25 bước đa nhân vật (thuộc `03-voice-director-workflow`).
  - Hậu kỳ mastering LUFS chuyên nghiệp đa track (thuộc `04-audio-engineering`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Bộ điều phối Batch** | `services/batch_runner.py` | Quản lý tiến trình render từng dòng, retry, merge |
| **Phân tích kịch bản** | `services/script_parser.py` | Tách câu, nhận diện timestamp SRT, trích xuất pause |
| **Xử lý tín hiệu âm thanh** | `services/audio.py` | Đo lường tín hiệu, Trim silence, chuẩn hóa RMS, ghép audio |
| **Giám định nội dung** | `services/critic.py` | Whisper ASR, tính WER, phát hiện mất chữ, đo WPM |
| **Bộ chấm điểm ứng viên** | `services/audio_candidate_evaluator.py` | Unified QC Evaluator, tổng hợp điểm Signal + Content |
| **Đóng gói xuất bản** | `services/batch_export.py` | Tạo ZIP chứa từng dòng, merged WAV, SRT và manifest |
| **Chạy Subprocess** | `inference_runner.py` | Runner chạy cách ly ngoài tiến trình |
| **API Routers** | `routers/jobs.py`, `routers/critic.py` | Quản lý Job Batch và endpoint `/api/v1/critic/evaluate` |
| **Giao diện WebUI** | `webui/js/batch.js` | Tab 2: Batch Studio & Subtitles |
| **Kiểm thử** | `tests/test_batch_studio_advanced.py` | Test chức năng batch, pauses, SRT, ZIP |
| | `tests/test_audio_quality.py` | Test signal QC, auto-fix, resume |
| | `tests/test_audio_candidate_evaluator.py` | Test chấm điểm ứng viên, xếp hạng |

---

## 3. Luồng Xử lý Phân đoạn (Segment Invariant Pipeline)

```
[Kịch bản dòng i]
       │
       ▼
[Sinh âm thanh (1 hoặc 2 Candidate)]
       │
       ▼
[Kiểm tra Tensor]: tensor.numel() > 0 (Không được rỗng)
       │
       ▼
[Signal QC]: Silence, RMS, Clipping
       │
   Có lỗi? ──► [Auto-Fix]: Trim silence + Normalize -19dB RMS + Peak Limiter ──► [Re-evaluate]
       │
       ▼
[Whisper STT Critic]: Kiểm tra mất chữ / WER (Nếu Whisper khả dụng; nếu không, bỏ qua cảnh báo)
       │
   Đạt? ──► Chọn Candidate tốt nhất ──► Lưu WAV dòng i ──► Ghép vào dòng thành công
   Hỏng? ──► Retry với seed/temp mới (Tối đa 2 lần)
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Không coi Tensor rỗng là Completed**: Nếu sinh ra audio có độ dài bằng 0 hoặc rỗng, bắt buộc đánh dấu thất bại hoặc ném ngoại lệ QC.
2. **Khả năng thiếu Whisper**: Thư viện `openai-whisper` là tùy chọn. Khi không có Whisper, ghi nhận cảnh báo và tiếp tục dựa vào Signal QC, tuyệt đối không làm crash hoặc abort toàn bộ batch render.
3. **Phụ đề SRT đồng bộ chính xác**: Thời gian start/end trong file SRT phải khớp mili-giây với tổng thời lượng audio thực tế và pause giữa các câu.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_batch_studio_advanced.py tests/test_audio_quality.py tests/test_audio_candidate_evaluator.py
```
