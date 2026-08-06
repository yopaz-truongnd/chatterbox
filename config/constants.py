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

import os
from pathlib import Path

# Đường dẫn file và thư mục xuất mặc định
PRESETS_FILE = Path("voice_presets.json")
DEFAULT_EXPORT_DIR = os.path.expanduser("~/Downloads")
MAX_CHUNK_CHARS = 400

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

# Danh sách ngôn ngữ đa ngữ
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
