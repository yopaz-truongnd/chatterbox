# Test Navigation

Đọc `../docs/agent-map.md` để chọn đúng test module.

- Narration plan, Pronunciation dict, ASR critic & multi-candidate ranking: `test_narration_plan.py`.
- Audio signal QC, auto-fix, resume và phase progression: `test_audio_quality.py`.
- Two-gate project lifecycle, event bus và project sync: `test_project_workflow.py`.
- MCP stdio JSON-RPC protocol và tool catalog/execution: `test_mcp_server.py`.
- Batch parsing, audio merge, subprocess và export: `test_batch_studio_advanced.py`.
- REST API và job lifecycle: `test_api_app.py`.
- Character / voice reference management: `test_character_api.py`.
- Model registry/runtime và shared unified services: `test_services_unified.py`.
- Thêm test nhỏ nhất tái hiện regression; không nhân đôi cùng assertion ở nhiều suite.
- Sau focused test, chạy `./run_chatterbox_api.sh --test`.

