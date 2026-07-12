from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from .constants import CONFIG_DIR, CONFIG_PATH, DEFAULT_EXPORT_ROOT, DEFAULT_TEXTURES_DIR, OLD_CONFIG_PATH


DEFAULT_SETTINGS: dict[str, Any] = {
    "click_advance": False,
    "theme": "Dark",
    "show_grid": True,
    "show_hover_tooltip": True,
    "default_texture_path": str(DEFAULT_TEXTURES_DIR),
    "texture_sources": [],
    "export_root": str(DEFAULT_EXPORT_ROOT),
    "base_cell_size": 16,
    "export_tile_size": 16,
    "combined_tile_size": 12,
    "zoom_step": 1.15,
    "block_label_mode": "ID + Name",
    "language_code": "en_us",
    "app_language": "en",
}


def default_config() -> dict[str, Any]:
    return {"recents": [], "regions": {}, "first_launch_complete": False, "settings": deepcopy(DEFAULT_SETTINGS)}


def merged_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    if isinstance(config.get("settings"), dict):
        settings.update(config["settings"])
    return settings


def load_config() -> dict[str, Any]:
    try:
        migrate_old_config()
        if CONFIG_PATH.exists():
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                return default_config()
            config.setdefault("recents", [])
            config.setdefault("first_launch_complete", False)
            if not isinstance(config.get("regions"), dict):
                config["regions"] = {}
            else:
                config.setdefault("regions", {})
            config["settings"] = merged_settings(config)
            return config
    except Exception:
        logging.exception("Failed to read config")
    return default_config()


def migrate_old_config() -> None:
    if CONFIG_PATH.exists() or not OLD_CONFIG_PATH.exists():
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(OLD_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        logging.exception("Failed to migrate old config from %s", OLD_CONFIG_PATH)


def save_config(config: dict[str, Any]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except Exception:
        logging.exception("Failed to save config")


def as_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = fallback
    return max(minimum, min(maximum, number))


def as_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = fallback
    return max(minimum, min(maximum, number))
