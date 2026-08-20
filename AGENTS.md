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
