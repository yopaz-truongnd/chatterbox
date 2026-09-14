# Domain 04: Audio Engineering — Mix, Master & Packaging

Tài liệu hướng dẫn hậu kỳ âm thanh đa track, xây dựng timeline MixPlan, thuật toán trộn sóng thuần Python, chuẩn hóa âm lượng theo chuẩn phát sóng (LUFS/EBU R128) và đóng gói xuất bản.

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - **Dựng Timeline Đa Track (`MixPlanBuilder`)**:
    - Ghép nối các đoạn lồng tiếng (Voice Clips) theo đúng thứ tự nhịp truyện và khoảng lặng.
    - Định vị các clip nhạc nền (Ambience/BGM) và hiệu ứng âm thanh (SFX) theo vị trí tương đối (offset, loop, fade-in, fade-out, ducking).
  - **Bộ trộn sóng thuần Python (`wave_audio_mixer.py`)**:
    - Xử lý mảng dữ liệu âm thanh 16-bit / 24-bit PCM WAV.
    - Áp dụng kỹ thuật Crossfade mượt mà giữa các đoạn thoại.
    - Tự động hạ âm lượng nhạc nền khi có tiếng thoại (Audio Ducking).
  - **Làm chủ âm thanh động (`audio_mastering.py`)**:
    - Đo lường và chuẩn hóa âm lượng tích hợp theo chuẩn quốc tế ITU-R BS.1770 / EBU R128 (mặc định -19 LUFS hoặc cấu hình trong `rules/mastering.yaml`).
    - Bộ giới hạn đỉnh mềm (Soft-Knee True Peak Limiter, ngưỡng -1.0 dBTP) chống vỡ tiếng hoàn toàn mà không làm méo âm sắc.
  - **Đóng gói xuất bản (`audio_export.py`)**:
    - Xuất tệp deliverable `FINAL.wav`.
    - Sinh `export-manifest.yaml` chứa mã băm SHA-256 của từng file để đảm bảo tính toàn vẹn (lineage integrity).
- **KHÔNG thuộc phạm vi**:
  - Quyết định nghệ thuật chọn nhạc nào (thuộc `03-voice-director-workflow` và `05-resources`).
  - Sinh tiếng bằng mô hình học sâu (thuộc `01-tts-and-models`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Dựng Timeline** | `services/mix_plan_builder.py` | Tính toán timeline mili-giây cho Voice, SFX, Ambience |
| **Hợp đồng Mix/Master** | `services/audio_mix_models.py` | Model dữ liệu cho MixPlan, VoiceClip, SFXClip, ExportManifest |
| **Giao thức thực thi** | `services/audio_mix_execution.py` | Abstract Execution Protocol cho Mixing engine |
| **Bộ trộn sóng** | `services/wave_audio_mixer.py` | Bộ trộn sóng PCM đa track thuần Python, ducking, crossfade |
| **Mastering LUFS** | `services/audio_mastering.py` | Đo LUFS tích hợp, gain normalization, soft-knee limiter |
| **Đóng gói & Hash** | `services/audio_export.py` | Ghi tệp cuối cùng, tính SHA-256 byte-level, manifest |
| **Cấu hình chuẩn** | `rules/mixing.yaml`, `rules/mastering.yaml` | Cấu hình mức dB ducking, target LUFS, limiter knee |
| **API Endpoints** | `routers/voice_workflows.py` | Endpoint `/prepare-mix`, `/mix`, `/master`, `/export` |
| **Kiểm thử** | `tests/test_mix_plan_builder.py` | Test tính toán thời lượng và vị trí clip |
| | `tests/test_wave_audio_mixer.py` | Test trộn sóng, ducking, crossfade |
| | `tests/test_audio_mastering.py` | Test chuẩn hóa LUFS và peak limiter |
| | `tests/test_audio_export.py` | Test tính toàn vẹn SHA-256 manifest |

---

## 3. Luồng Xử lý Hậu kỳ (Audio Mastering Pipeline)

```
[Các tệp Voice Beats (.wav)] + [SFX & Ambience (.wav)]
                         │
                         ▼
             [services/mix_plan_builder.py]
             (Tính toán Start Time, Duration, Fade, Ducking)
                         │
                         ▼
             [services/wave_audio_mixer.py]
             (Trộn các track thành 1 luồng âm thanh phẳng, Sample Rate 24kHz)
                         │
                         ▼
             [services/audio_mastering.py]
             (Đo ITU-R BS.1770 LUFS ──► Gain Normalize ──► Soft-Knee Peak Limiter -1 dBTP)
                         │
                         ▼
             [services/audio_export.py]
             (Lưu FINAL.wav ──► Tính SHA-256 ──► Xuất export-manifest.yaml)
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Bảo toàn Hash SHA-256 Độc lập Nền tảng**: Quá trình xuất audio và manifest phải dùng `newline=""` để không bị chuyển đổi CRLF trên Windows làm sai lệch mã băm.
2. **Không nén Clipping cứng (No Hard Clipping)**: Mọi âm thanh xuất xưởng phải đi qua soft-knee limiter để đảm bảo đỉnh tín hiệu không bao giờ vượt ngưỡng 0 dBFS gây rè loa.
3. **Pure Python Fallback**: Toàn bộ thuật toán mix/master có thể chạy độc lập với Python và NumPy/SciPy/PyTorch mà không bắt buộc phải có `ffmpeg` ngoại vi.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_mix_plan_builder.py tests/test_wave_audio_mixer.py tests/test_audio_mastering.py tests/test_audio_export.py
```
