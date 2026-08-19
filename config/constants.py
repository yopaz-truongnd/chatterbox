"""
Hằng số cấu hình dự án Chatterbox TTS Studio
"""

from pathlib import Path

# Màu sắc giao diện (Material 3 High-Contrast Palette Tokens)
BG_COLOR = "#0E0C12"            # M3 Surface (Nền tối sâu tạo tương phản mạnh)
PANEL_BG = "#18151E"            # M3 Surface Container Low (Panel & Container chính)
PANEL2_BG = "#231F2A"           # M3 Surface Container High (Elevated Cards & Sections)
BORDER_COLOR = "#3F3A46"        # M3 Outline Variant (Viền phân cách rõ nét)
BORDER_FOCUS = "#D0BCFF"        # M3 Focus Ring (Tím sáng nổi bật)

# Text Tokens (Tương phản cao WCAG AAA)
TEXT_COLOR = "#FFFFFF"          # Văn bản chính: Trắng tinh thuần khiết (100% Contrast)
TEXT_DIM_COLOR = "#94A3B8"      # Văn bản phụ/nhãn: Xám sáng rõ nét (Slate-400)
TEXT_MUTED = "#64748B"          # Văn bản mờ/gợi ý (Slate-500)

# Accent & Semantic Tokens
ACCENT_COLOR = "#7C3AED"        # Màu nhấn chính tím sáng nổi bật (Violet 600)
ACCENT_LIGHT = "#D0BCFF"        # Màu tím sáng M3 Lavender (Chữ & Icon trên nền tối)
ACCENT_HOVER = "#6D28D9"        # Màu nhấn hover/active (Violet 700)
ACCENT2_COLOR = "#10B981"       # Trạng thái thành công (Emerald 500)
STATUS_DANGER = "#EF4444"       # Trạng thái lỗi/cảnh báo (Red 500)

# Tab Tokens (Phân biệt rõ ràng Tab Active vs Tab Inactive)
TAB_ACTIVE_BG = "#7C3AED"       # Nền Tab đang chọn: Tím sáng nổi bật
TAB_ACTIVE_FG = "#FFFFFF"       # Chữ Tab đang chọn: Trắng đậm
TAB_INACTIVE_BG = "#18151E"     # Nền Tab chưa chọn: Tối chìm
TAB_INACTIVE_FG = "#94A3B8"     # Chữ Tab chưa chọn: Xám dịu
TAB_HOVER_BG = "#2B2633"        # Nền Tab khi hover

# Button Tokens (Độ tương phản cao & trạng thái bấm rõ nét)
BUTTON_PRIMARY_BG = "#7C3AED"
BUTTON_PRIMARY_FG = "#FFFFFF"
BUTTON_PRIMARY_ACTIVE = "#6D28D9"
BUTTON_SECONDARY_BG = "#2B2633"
BUTTON_SECONDARY_FG = "#F1F5F9"
BUTTON_SECONDARY_ACTIVE = "#3D3648"
BUTTON_DANGER_BG = "#DC2626"
BUTTON_DANGER_FG = "#FFFFFF"
BUTTON_DANGER_ACTIVE = "#B91C1C"
BUTTON_DISABLED_BG = "#18151E"
BUTTON_DISABLED_FG = "#64748B"

import os
import sys
import tempfile
from pathlib import Path

UI_FONT = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
MONO_FONT = "SF Mono" if sys.platform == "darwin" else "Consolas"

# Thư mục tạm trong dự án dùng để lưu audio tạo ra thay vì vào hệ thống
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Thiết lập thư mục temp toàn cục cho tempfile của Python
tempfile.tempdir = str(TMP_DIR)

# Đường dẫn file và thư mục xuất mặc định
PRESETS_FILE = Path("voice_presets.json")
DEFAULT_EXPORT_DIR = os.path.expanduser("~/Downloads")
MAX_CHUNK_CHARS = 4000

# Paralinguistic tags
PARALINGUISTIC_TAGS = {
    "[laugh]": "Cười",
    "[chuckle]": "Cười khẽ",
    "[sigh]": "Thở dài",
    "[gasp]": "Hít vào ngạc nhiên",
    "[cough]": "Ho",
    "[groan]": "Than vãn",
    "[sniff]": "Sụt sịt",
    "[clear throat]": "E hèm",
    "[shush]": "Suỵt",
    "[whisper]": "Thì thầm",
    "[yawn]": "Ngáp"
}

# Các combo cấu hình nhanh
PRESET_COMBOS = [
    ("Đọc tin tức", 0.3, 0.7, 0.6),
    ("Kể chuyện", 0.8, 0.5, 0.85),
    ("Biểu cảm mạnh", 1.2, 0.5, 0.9),
    ("Thì thầm", 0.2, 0.8, 0.5)
]

# Ngôn ngữ giao diện
UI_LANGUAGES = {
    "vi": "🇻🇳 Tiếng Việt",
}

# Danh sách ngôn ngữ model Multilingual hỗ trợ
LANGUAGES_WITH_FLAGS = {
    "en": "🇬🇧 English",
    "es": "🇪🇸 Spanish",
    "fr": "🇫🇷 French",
    "de": "🇩🇪 German",
    "it": "🇮🇹 Italian",
    "ja": "🇯🇵 Japanese",
    "zh": "🇨🇳 Chinese",
    "ko": "🇰🇷 Korean",
    "ru": "🇷🇺 Russian",
    "ar": "🇸🇦 Arabic",
    "hi": "🇮🇳 Hindi",
    "pt": "🇵🇹 Portuguese",
    "nl": "🇳🇱 Dutch",
    "pl": "🇵🇱 Polish",
    "tr": "🇹🇷 Turkish",
    "sw": "🇰🇪 Swahili",
    "sv": "🇸🇪 Swedish",
    "da": "🇩🇰 Danish",
    "fi": "🇫🇮 Finnish",
    "el": "🇬🇷 Greek",
    "he": "🇮🇱 Hebrew",
    "ms": "🇲🇾 Malay",
    "no": "🇳🇴 Norwegian"
}
