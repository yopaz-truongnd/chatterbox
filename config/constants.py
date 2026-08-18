"""
Hằng số cấu hình dự án Chatterbox TTS Studio
"""

from pathlib import Path

# Màu sắc giao diện (Dark Slate Theme)
BG_COLOR = "#0c121c"
PANEL_BG = "#121b28"
PANEL2_BG = "#17222f"
BORDER_COLOR = "#223047"
TEXT_COLOR = "#dbe4f0"
TEXT_DIM_COLOR = "#7c8ba3"
ACCENT_COLOR = "#4f8cff"
ACCENT2_COLOR = "#35d0a4"

# Button states use darker active colors so light text keeps its contrast.
BUTTON_PRIMARY_BG = "#2563EB"
BUTTON_PRIMARY_ACTIVE = "#1D4ED8"
BUTTON_SECONDARY_ACTIVE = "#334155"
BUTTON_DANGER_BG = "#BE123C"
BUTTON_DANGER_ACTIVE = "#9F1239"
BUTTON_DISABLED_BG = "#263244"
BUTTON_DISABLED_FG = "#94A3B8"

import os
import sys
from pathlib import Path

UI_FONT = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
MONO_FONT = "SF Mono" if sys.platform == "darwin" else "Consolas"

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
