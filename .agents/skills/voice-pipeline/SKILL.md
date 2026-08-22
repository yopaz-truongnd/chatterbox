---
name: voice-pipeline
description: Use when changing voice evaluation, silence trimming, normalization, auto-fix, re-evaluation, batch merge, quality reports, narration plan, speech critic, or publish events in Chatterbox.
---

# Storytelling & Voice Production Pipeline

Đọc theo thứ tự và dừng khi đã đủ context:

1. `services/narration_planner.py` — Lập Narration Plan và scan pronunciation candidates.
2. `services/audio.py` — Signal evaluation & auto-fix.
3. `services/critic.py` — Whisper ASR speech content critic.
4. `services/batch_runner.py` — Batch execution, multi-candidate ranking & adaptive retry.
5. `tests/test_narration_plan.py` & `tests/test_audio_quality.py` — Regression tests.

Chỉ đọc thêm:
- `inference_runner.py` khi hành vi phải chạy qua subprocess.
- `services/job_manager.py` khi thay đổi job phase hoặc event.
- `services/project_planner.py` khi thay đổi metadata hoặc confirmation gates của project.

## Invariant Xử Lý Segment

```text
[Generate Candidate(s)] -> [Signal QC + Whisper ASR Content Critic]
                        -> [Signal Auto-Fix nếu fixable] -> [Re-evaluate]
                        -> [Nếu lỗi: Adaptive Retry với new seed/temperature (tối đa 2 lần)]
                        -> [Rank & Chọn candidate tốt nhất] -> [Merge passing chunks] -> [Publish]
```

## Quy Tắc Model & Tham Số (Model-Aware Parameter Invariant)
- **Chatterbox Turbo**: Hỗ trợ các thẻ cảm xúc `[laugh]`, `[sigh]`, `[chuckle]`, `[whisper]`, `[gasp]`,... Tuyệt đối KHÔNG inject `cfg_weight`, `exaggeration`, `min_p` vì model Turbo bỏ qua các tham số này.
- **Chatterbox Standard**: Hỗ trợ tăng `exaggeration` và giảm `cfg_weight` cho các phân đoạn cao trào / kịch tính.
- **Chatterbox Nano**: Ưu tiên preview nhanh, an toàn RAM.
- **Local Isolation**: Chỉ nạp 1 model tại một thời điểm vào bộ nhớ; giải phóng model cũ trước khi nạp model mới.

## Quy Tắc Đánh Giá Kép (Dual Critic QC)
- **Signal QC (`services/audio.py`)**: Kiểm tra RMS loudness (-24dB đến -12dB), clipping peak (<= 0.98), khoảng lặng đầu/cuối, crest factor và thời lượng bất thường.
- **ASR Content Critic (`services/critic.py`)**: Whisper transcribe đối chiếu nguyên văn:
  - Bắt buộc hard-fail nếu thiếu từ quá nhiều (>35%) hoặc có từ lặp do ảo giác/nói lắp (`repeated_words`).
  - Đo tốc độ đọc thực tế (`actual_wpm`) so sánh với `target_wpm` trong Narration Plan.
- **Điểm xếp hạng kết hợp**: `Score = Content Score * 0.6 + Signal Score * 0.4`.

## Selective Multi-Candidate Strategy
- Sinh 2 candidates cho các phân đoạn: `role == "dialogue"`, `emotion in ("dramatic", "suspense")`, có từ điển phiên âm riêng (`pronunciation`), hoặc câu dài (>24 từ).
- Đoạn thông thường chỉ sinh 1 candidate duy nhất.
- Lưu trữ lịch sử `attempts` trong metadata kết quả từng dòng.

Kiểm tra:

```bash
venv/bin/python -m unittest -v tests/test_narration_plan.py tests/test_audio_quality.py tests/test_project_workflow.py
./run_chatterbox_api.sh --test
```

