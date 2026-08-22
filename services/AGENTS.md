# Services Navigation

Đọc `../docs/agent-map.md` trước khi sửa service.

- Chỉ mở service sở hữu hành vi được yêu cầu và caller trực tiếp của nó.
- Audio/QC: bắt đầu từ `audio.py`.
- Batch ordering: bắt đầu từ `batch_runner.py`; chỉ mở `../inference_runner.py` khi cần subprocess parity.
- Job status/event: bắt đầu từ `job_manager.py`.
- Product gates/state: bắt đầu từ `project_planner.py`.
- Không đặt HTTP hoặc MCP response formatting trong services.
- Khi thay đổi logic dùng chung cho in-process và subprocess, triển khai một lần trong service dùng chung rồi gọi từ hai runner.
- Chạy test được ánh xạ trong `../docs/agent-map.md` sau khi sửa.
