---
name: voice-pipeline
description: Use when changing voice evaluation, silence trimming, normalization, auto-fix, re-evaluation, batch merge, quality reports, or publish events in Chatterbox.
---

# Voice Pipeline

Đọc theo thứ tự và dừng khi đã đủ context:

1. `services/audio.py`
2. `services/batch_runner.py`
3. `tests/test_project_workflow.py`

Chỉ đọc thêm:

- `inference_runner.py` khi hành vi phải chạy qua subprocess.
- `services/job_manager.py` khi thay đổi job phase hoặc event.
- `services/project_planner.py::sync_project_with_job` khi thay đổi metadata công khai của project.
- `tests/test_batch_studio_advanced.py` khi thay đổi merge, resume hoặc subprocess.

Giữ invariant:

```text
generate -> evaluate -> auto-fix at most once -> re-evaluate
         -> merge passing chunks -> publish
```

- Định nghĩa quality criteria và signal transformations một lần trong `services/audio.py`.
- In-process và subprocess phải gọi cùng logic dùng chung.
- Không merge segment vẫn fail sau re-evaluate, trừ khi policy công khai cho phép warning-only.
- Chỉ một component phát terminal completion event.
- Không thêm dependency cho các phép đo signal có thể thực hiện bằng Torch/Torchaudio hiện có.

Kiểm tra:

```bash
venv/bin/python -m unittest -v tests.test_project_workflow
./run_chatterbox_api.sh --test
```
