"""Settings Manager - Quản lý cài đặt dự án Chatterbox TTS Studio (Desktop & API).

Định nghĩa schema cấu hình thống nhất, mapping nhãn model và lưu trữ đa nền tảng.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from utils.logger import logger

PROJECT_DIR = Path(__file__).resolve().parents[1]

cpu_count = os.cpu_count() or 4
default_cpu_threads = max(1, min(4, cpu_count - 2 if cpu_count > 2 else cpu_count))

# Canonical Unified Settings Schema
DEFAULT_SETTINGS = {
    # Thiết bị & Model
    "device": "auto",                    # "auto", "cuda", "mps", "cpu"
    "default_model": "auto",             # "auto", "nano", "turbo", "standard", "multilingual"
    "cpu_threads": default_cpu_threads,  # Số luồng CPU
    "retention_days": 3,                 # TTL tự động dọn dẹp job SQLite

    # Đường dẫn & Xuất file
    "export_dir": os.path.expanduser("~/Downloads"),
    "model_cache_dir": str(PROJECT_DIR / "models"),
    "auto_open_export_dir": True,
    "audio_format": "wav",               # "wav", "mp3", "flac", "ogg"

    # Giao diện & Trải nghiệm
    "language": "🇻🇳 Tiếng Việt",
    "dark_mode": False,
    "custom_accent_color": "",
    "desktop_notifications": True,
    "confirm_delete_history": True,

    # Tối ưu hóa phần cứng Desktop
    "max_chunk_chars": 4000,
    "auto_unload_models": False,
    "process_priority": "low",           # "low" hoặc "normal"
    "max_vram_fraction": 80,
    "force_gc_after_gen": True,
    "max_batch_workers": 2,
}

# Bidirectional Model Mapping for Desktop UI (Derived directly from MODEL_REGISTRY)
from services.model_registry import MODEL_REGISTRY, resolve_model_id

_REGISTRY_LABELS = {
    "nano": "⚡ Chatterbox Nano (110M - Light/CPU)",
    "turbo": "🚀 Chatterbox Turbo (350M - Fast)",
    "standard": "🎙️ Chatterbox Standard (500M)",
    "multilingual": "🌐 Multilingual V3 (500M)",
}

MODEL_TO_LABEL = {
    "auto": "✨ Tự động theo cấu hình máy (Auto)",
    **{k: _REGISTRY_LABELS.get(k, spec.display_name) for k, spec in MODEL_REGISTRY.items() if k != "voice-conversion"},
}

LABEL_TO_MODEL = {label: model for model, label in MODEL_TO_LABEL.items()}
for model_key, spec in MODEL_REGISTRY.items():
    LABEL_TO_MODEL[model_key] = model_key
    LABEL_TO_MODEL[spec.name] = model_key
    LABEL_TO_MODEL[spec.display_name] = model_key
    for alias in spec.aliases:
        LABEL_TO_MODEL[alias] = model_key
LABEL_TO_MODEL["auto"] = "auto"

LEGACY_KEY_ALIASES = {
    "device_preference": "device",
    "default_startup_model": "default_model",
    "cpu_threads_limit": "cpu_threads",
}


def get_default_settings_file() -> Path:
    """Get the platform-safe settings file location with auto-migration."""
    env_path = os.getenv("CHATTERBOX_SETTINGS_FILE")
    if env_path:
        return Path(env_path)

    try:
        from utils.platform_tools import get_default_data_dir
        platform_data_dir = get_default_data_dir()
    except Exception:
        platform_data_dir = PROJECT_DIR / "data"

    platform_settings_file = platform_data_dir / "settings.json"
    legacy_settings_file = PROJECT_DIR / "config" / "settings.json"

    # One-time migration from legacy repo config/settings.json
    if not platform_settings_file.exists() and legacy_settings_file.exists():
        try:
            platform_data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_settings_file, platform_settings_file)
            logger.info("Đã di chuyển cài đặt từ %s sang %s", legacy_settings_file, platform_settings_file)
        except Exception as exc:
            logger.warning("Không thể di chuyển cài đặt sang %s: %s", platform_settings_file, exc)
            return legacy_settings_file

    return platform_settings_file


def migrate_settings(raw_dict: dict) -> dict:
    """Migrate legacy configuration keys to the canonical schema."""
    migrated = raw_dict.copy()

    # 1. Alias migrations
    for legacy_key, canonical_key in LEGACY_KEY_ALIASES.items():
        if legacy_key in migrated and canonical_key not in migrated:
            migrated[canonical_key] = migrated.pop(legacy_key)

    # 2. Legacy model names to canonical strings
    if "default_model" in migrated and isinstance(migrated["default_model"], str):
        val = migrated["default_model"]
        migrated["default_model"] = LABEL_TO_MODEL.get(val, val)

    if "default_startup_model" in migrated and isinstance(migrated["default_startup_model"], str):
        val = migrated.pop("default_startup_model")
        if "default_model" not in migrated:
            migrated["default_model"] = LABEL_TO_MODEL.get(val, "auto")

    return migrated


class SettingsManager:
    def __init__(self, filepath: Path | str | None = None):
        self.filepath = Path(filepath) if filepath is not None else get_default_settings_file()
        self.settings = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self) -> None:
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    migrated = migrate_settings(data)
                    self.settings.update(migrated)
                logger.info("Đã tải cài đặt từ %s", self.filepath)
            except Exception as e:
                logger.error("Lỗi khi nạp settings.json: %s", e)
        else:
            self.save()

    def save(self) -> None:
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            logger.info("Đã lưu cài đặt vào %s", self.filepath)
        except Exception as e:
            logger.error("Lỗi khi lưu settings.json: %s", e)

    def get(self, key: str, default=None):
        canonical_key = LEGACY_KEY_ALIASES.get(key, key)
        if canonical_key in self.settings:
            return self.settings[canonical_key]
        if key in self.settings:
            return self.settings[key]
        return default if default is not None else DEFAULT_SETTINGS.get(canonical_key, DEFAULT_SETTINGS.get(key))

    def set(self, key: str, value) -> None:
        canonical_key = LEGACY_KEY_ALIASES.get(key, key)
        if canonical_key == "default_model" and isinstance(value, str):
            value = LABEL_TO_MODEL.get(value, value)
        self.settings[canonical_key] = value

    def __getitem__(self, key: str):
        return self.get(key)

    def __setitem__(self, key: str, value):
        self.set(key, value)

    def reset_defaults(self) -> None:
        self.settings = DEFAULT_SETTINGS.copy()
        self.save()


# Singleton instance for easy import across the project
settings_manager = SettingsManager()
