# Antigravity Agent Guidelines

## ✅ Quyền Chỉnh Sửa Mã Nguồn (Code Editing Permission)
- **Được phép chủ động**: Tự động tạo, chỉnh sửa mã nguồn, refactor, thêm test, và sửa lỗi trong phạm vi dự án này mà không cần hỏi xác nhận trước từng bước sửa code.

## ⚠️ Thao tác Ngoài Sửa Code Cần Xác Nhận (Non-Code Operations - STRICT CONFIRMATION)
1. **Lệnh Git (Tuyệt đối tuân thủ)**:
   - **TUYỆT ĐỐI KHÔNG** tự ý chạy bất kỳ lệnh `git` nào (`git commit`, `git push`, `git checkout`, `git add`, `git branch`, `git merge`, `git reset`, `git stash`,...) nếu chưa có yêu cầu hoặc xác nhận rõ ràng từ người dùng.
2. **Thao tác ngoài phạm vi sửa code**:
   - Mọi thao tác như xóa file/thư mục quan trọng, thay đổi cấu hình môi trường bên ngoài dự án, deploy, thao tác hệ thống nâng cao đều phải hỏi ý kiến và chờ người dùng xác nhận trước khi thực hiện.
3. **Quy trình sau khi hoàn thành sửa code**:
   - Chạy kiểm thử tự động (`./run_chatterbox_api.sh --test` hoặc `pytest`).
   - Báo cáo rõ ràng danh sách các file đã thay đổi/tạo mới.
   - Chờ người dùng duyệt và ra lệnh tiếp theo.

## Repository Navigation

- Trước khi đọc implementation, mở `docs/agent-map.md` và chọn nhóm tính năng nhỏ nhất phù hợp với yêu cầu.
- Đọc primary files trước; chỉ mở secondary files khi thay đổi thật sự vượt qua ranh giới trách nhiệm.
- Tìm symbol và caller bằng `rg` trước khi đọc toàn bộ file lớn.
- Không đọc lại file chưa thay đổi trong cùng một task, trừ khi cần kiểm tra một symbol hoặc caller cụ thể.
- Không đọc Desktop/Gradio khi task chỉ liên quan API, MCP hoặc project workflow.
- Không đọc implementation multilingual nếu thay đổi không liên quan language handling. English là ưu tiên hiện tại, nhưng phải giữ khả năng multilingual.
- Business logic nằm trong `services/`; router, MCP và UI chỉ validate, chuyển đổi hoặc trình bày dữ liệu.
