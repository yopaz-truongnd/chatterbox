# Test Navigation

Đọc `../docs/agent-map.md` để chọn đúng test module.

- Project gates, events và voice quality pipeline: `test_project_workflow.py`.
- Batch parsing, merge, subprocess và export: `test_batch_studio_advanced.py`.
- REST API và job lifecycle: `test_api_app.py`.
- Character/reference voice: `test_character_api.py`.
- Model registry/runtime và shared services: `test_services_unified.py`.
- MCP protocol và tool mapping: `test_mcp_server.py`.
- Thêm test nhỏ nhất tái hiện regression; không nhân đôi cùng assertion ở nhiều suite.
- Sau focused test, chạy `./run_chatterbox_api.sh --test`.
