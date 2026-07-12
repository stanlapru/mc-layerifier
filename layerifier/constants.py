from __future__ import annotations

import logging
import sys
from pathlib import Path


APP_NAME = "Minecraft Layerifier"
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
OLD_CONFIG_DIR = Path.home() / ".minecraft_layerifier"
CONFIG_PATH = CONFIG_DIR / "config.json"
OLD_CONFIG_PATH = OLD_CONFIG_DIR / "config.json"
LOG_PATH = CONFIG_DIR / "layerifier.log"
DEFAULT_EXPORT_ROOT = PROJECT_ROOT / "exports"
DEFAULT_TEXTURES_DIR = PROJECT_ROOT / "textures"
GUI_LOCALE_DIR = PROJECT_ROOT / "localizations"


def setup_logging() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
