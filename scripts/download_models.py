"""Script to download and verify model checkpoints for Chatterbox TTS."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Enable online mode for downloading
os.environ["HF_HUB_CACHE"] = str(MODELS_DIR)
os.environ["HF_HUB_OFFLINE"] = "0"

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("❌ Lỗi: Chưa cài đặt thư viện 'huggingface_hub'. Vui lòng chạy: pip install huggingface_hub")
    sys.exit(1)

MODELS_CONFIG = {
    "nano": {
        "repo_id": "ResembleAI/chatterbox-nano",
        "patterns": ["*"],
        "name": "Chatterbox Nano (110M)",
    },
    "turbo": {
        "repo_id": "ResembleAI/chatterbox-turbo",
        "patterns": ["*"],
        "name": "Chatterbox Turbo (350M)",
    },
    "standard": {
        "repo_id": "ResembleAI/chatterbox",
        "patterns": ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"],
        "name": "Chatterbox Standard (500M)",
    },
    "multilingual": {
        "repo_id": "ResembleAI/chatterbox",
        "patterns": [
            "ve.safetensors",
            "ve.pt",
            "s3gen.safetensors",
            "s3gen.pt",
            "t3_mtl23ls_v2.safetensors",
            "t3_mtl23ls_v3.safetensors",
            "grapheme_mtl_merged_expanded_v1.json",
            "conds.pt",
            "Cangjie5_TC.json",
        ],
        "name": "Chatterbox Multilingual (500M - 23 Languages)",
    },
}


def download_model(model_key: str, token: str | None = None) -> bool:
    if model_key not in MODELS_CONFIG:
        print(f"❌ Mô hình không hợp lệ: '{model_key}'. Chọn một trong: {', '.join(MODELS_CONFIG.keys())} hoặc 'all'")
        return False

    cfg = MODELS_CONFIG[model_key]
    print(f"\n📦 Đang tải checkpoint cho {cfg['name']} từ repo '{cfg['repo_id']}'...")
    print(f"📁 Thư mục lưu: {MODELS_DIR}")
    print("⏳ Quá trình tải có thể mất vài phút tùy tốc độ mạng...")

    try:
        local_dir = snapshot_download(
            repo_id=cfg["repo_id"],
            repo_type="model",
            revision="main",
            allow_patterns=cfg["patterns"],
            token=token or os.getenv("HF_TOKEN"),
        )
        print(f"✅ Đã tải thành công {cfg['name']} vào:\n   {local_dir}\n")
        return True
    except Exception as e:
        print(f"❌ Lỗi khi tải mô hình {model_key}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Tải model weights cho Chatterbox TTS")
    parser.add_argument(
        "--model",
        default="multilingual",
        choices=list(MODELS_CONFIG.keys()) + ["all"],
        help="Mô hình cần tải (mặc định: multilingual)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Hugging Face User Access Token (tùy chọn)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  🚀 CHATTERBOX TTS — TẢI CHECKPOINTS TỪ HUGGING FACE")
    print("=" * 60)

    if args.model == "all":
        success = True
        for m in MODELS_CONFIG.keys():
            if not download_model(m, token=args.token):
                success = False
        if success:
            print("🎉 Toàn bộ các mô hình đã được tải sẵn sàng!")
    else:
        download_model(args.model, token=args.token)


if __name__ == "__main__":
    main()
