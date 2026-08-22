# Chatterbox Workspace Context

Repository routing map nằm tại `docs/agent-map.md`.

Trước khi đọc implementation:

1. Phân loại task theo routing map.
2. Đọc primary files của đúng nhóm tính năng.
3. Chỉ mở secondary files khi symbol hoặc hành vi đi qua trách nhiệm của chúng.
4. Dùng symbol search trước khi mở lại file đã đọc.
5. Không đặt business logic trong router, MCP adapter hoặc UI.
6. Chạy focused tests được ánh xạ trong routing map trước full suite.

English là ưu tiên sản phẩm hiện tại; không xóa hoặc làm hỏng khả năng multilingual.
