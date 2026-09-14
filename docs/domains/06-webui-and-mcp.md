# Domain 06: WebUI Dashboard & Model Context Protocol (MCP)

Tài liệu hướng dẫn giao diện Material 3 Web Studio và giao thức Model Context Protocol (MCP) tích hợp vào các IDE AI (Cursor, Windsurf, Claude Desktop, Antigravity).

---

## 1. Trách nhiệm & Phạm vi (Scope & Boundaries)

- **Trách nhiệm**:
  - **Material Design 3 Web Studio (`webui/`)**:
    - Giao diện người dùng thuần Vanilla JS, Tailwind CSS CDN (không Webpack, không Vite, không npm build).
    - Cấu trúc 6 Tabs điều khiển:
      1. Tab 1: Sinh giọng nói nhanh (`js/tts.js`).
      2. Tab 2: TTS Đa ngôn ngữ (`js/multilingual.js`).
      3. Tab 3: Nhân vật & Mẫu giọng (`js/characters.js`).
      4. Tab 4: Chuyển đổi giọng nói (`js/vc.js`).
      5. Tab 5: Dự án âm thanh cơ bản (`js/projects.js`).
      6. Tab 6: Bàn điều khiển Đạo diễn 25 Phase (`js/director-console.js`).
    - Phục vụ tệp tĩnh: Biểu tượng Favicon (`/favicon.ico`, `/favicon.svg`), Stylesheet (`css/styles.css`).
  - **Máy chủ MCP (Model Context Protocol - `mcp_server.py`)**:
    - Triển khai chuẩn giao thức JSON-RPC 2.0 qua Standard I/O (`stdio`).
    - Danh mục 76 công cụ cho AI Agent tương tác toàn diện từ mã nguồn (TTS, Voice Clone, Phân tích kịch bản, Render, Đạo diễn, Sức khỏe, Chẩn đoán).
    - Chuyển tiếp HTTP Request sang REST API cục bộ (`http://127.0.0.1:8000`).
- **KHÔNG thuộc phạm vi**:
  - Tính toán mô hình hoặc xử lý âm thanh trực tiếp (thuộc các domain `01` đến `04`).

---

## 2. Bản đồ Tệp (File Map)

| Thành phần | Đường dẫn tệp | Vai trò chính |
|---|---|---|
| **Server Chính** | `api_app.py` | Mount thư mục `/static`, phục vụ HTML và favicon |
| **HTML Giao diện** | `webui/material_dashboard.html` | Khung giao diện đơn trang (SPA), CDN Tailwind & Material Icons |
| **Favicon** | `webui/favicon.ico`, `webui/favicon.svg`| Biểu tượng Studio sắc nét đa kích thước |
| **Trạng thái Web** | `webui/js/state.js` | Biến toàn cục, quản lý cấu hình, tham số player |
| **Khởi động Web** | `webui/js/main.js` | Bootstrap sự kiện DOM, phím tắt (F1, Ctrl+Enter), Health check |
| **Controller Tabs**| `webui/js/tts.js`, `js/batch.js`, `js/characters.js`, `js/vc.js`, `js/director-console.js`, `js/notifications.js` |
| **MCP Server** | `mcp_server.py` | JSON-RPC 2.0 loop qua stdio, dispatch tool |
| **MCP Catalog** | `mcp_adapter/catalog.py` | Định nghĩa schema 76 công cụ JSON Schema |
| **MCP Handlers** | `mcp_adapter/voice_tools.py`, `project_tools.py`, `series_tools.py`, `health_tools.py`, `runtime_tools.py`, `asset_tools.py` |
| **Kiểm thử** | `tests/test_api_app.py` | Test mount static files, favicon, các route GET HTML |
| | `tests/test_mcp_server.py` | Test handshake JSON-RPC và 76 công cụ MCP |

---

## 3. Cấu hình Kết nối MCP trong IDE (IDE Configuration)

Thêm đoạn sau vào cấu hình MCP của Cursor / Windsurf / Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "chatterbox": {
      "command": "python",
      "args": ["E:/Project/chatterbox/mcp_server.py"],
      "env": {
        "CHATTERBOX_API_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

---

## 4. Các Quy tắc Bất biến (Invariants)

1. **Không có Build Step**: Mọi file trong `webui/` phải chạy được ngay trên trình duyệt mà không cần chạy lệnh compile hay bundle.
2. **Luôn dùng Cache-Busting**: Khi chỉnh sửa bất kỳ tệp JavaScript nào trong `webui/js/`, bắt buộc phải tăng số version query string tương ứng trong `webui/material_dashboard.html` (ví dụ: `notifications.js?v=20260914-v27`) để trình duyệt người dùng không tải file cũ từ cache.
3. **MCP không chứa Business Logic**: Mọi hàm handler trong `mcp_adapter/` chỉ đóng vai trò chuyển đổi JSON thành lời gọi HTTP hoặc gọi service, tuyệt đối không lặp lại logic tính toán.

---

## 5. Lệnh Kiểm thử Nhanh (Fast Verification)

```bash
python -m unittest tests/test_api_app.py tests/test_mcp_server.py
```
