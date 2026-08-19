"""
Chatterbox TTS Studio - Material Design 3 Web Dashboard Runner
Khởi chạy Web Dashboard giao diện Google Material 3 trên trình duyệt
"""

import os
import sys
import webbrowser
import http.server
import socketserver
from pathlib import Path

PORT = 7860
PROJECT_DIR = Path(__file__).resolve().parent
WEBUI_DIR = PROJECT_DIR / "webui"

class DashboardHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.path = "/material_dashboard.html"
        return super().do_GET()

def run_server():
    os.chdir(WEBUI_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), DashboardHTTPHandler) as httpd:
        url = f"http://localhost:{PORT}/material_dashboard.html"
        print("=" * 65)
        print("🎨 CHATTERBOX TTS STUDIO — GOOGLE MATERIAL DESIGN 3 DASHBOARD")
        print("=" * 65)
        print(f"🚀 Server đang hoạt động tại: {url}")
        print("Nhấn Ctrl + C trong terminal để dừng server.")
        print("=" * 65)
        
        try:
            webbrowser.open(url)
        except Exception:
            pass
            
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nĐã dừng Material Dashboard Server.")

if __name__ == "__main__":
    run_server()
