from __future__ import annotations

import json
import logging
from pathlib import Path

from .constants import GUI_LOCALE_DIR


DEFAULT_GUI_STRINGS: dict[str, str] = {
    "about.body": "A Java Edition world-layer viewer for player-built structures.\n\nIt reads level.dat-adjacent Anvil region files, displays one coordinate layer at a time, supports Minecraft texture folders, model-based texture aliases, localized block names, block exclusions, zooming, panning, and PNG export.\n\nMinecraft assets are not bundled; select textures from your own extracted Minecraft jar.",
    "about.close": "Close",
    "about.title": "About Minecraft Layerifier",
    "axis.label": "Layer axis",
    "bounds.max": "Max",
    "bounds.min": "Min",
    "bounds.name": "Name",
    "bounds.recent": "Recent",
    "bounds.title": "Inclusive Bounds",
    "button.apply_exclusions": "Apply Manual Exclusions",
    "button.choose_exclusions": "Choose Excluded Blocks",
    "button.copy_summary": "Copy Summary",
    "button.load_structure": "Load Structure",
    "button.load_texture_folder": "Load Texture Folder",
    "button.load_texture_json": "Load Texture JSON",
    "button.open_level": "Open level.dat",
    "button.open_recent": "Open Recent",
    "dialog.first_launch.body": "Essential setup:\n\n1. Open a Java Edition world by selecting its level.dat.\n2. Enter inclusive structure bounds and optionally name the structure.\n3. For best textures, select assets/minecraft/atlases/blocks.json or assets/minecraft/textures/block from an extracted Minecraft jar.\n4. Use Tools > Options to change theme, export paths, and application language.\n\nSettings, logs, exports, and localization files are stored in this project folder so the app can be packaged later.",
    "dialog.first_launch.title": "First Launch Setup",
    "exclusions.clear": "Clear Exclusions",
    "exclusions.close": "Close",
    "exclusions.excluded": "Excluded",
    "exclusions.id": "Block ID",
    "exclusions.name": "Name",
    "exclusions.search": "Search",
    "exclusions.title": "Block Exclusions",
    "exclusions.toggle": "Toggle Selected",
    "export.combined": "Combined PNG Grid",
    "export.individual": "Individual PNG Layers",
    "export.title": "Export",
    "label.exclusions": "Excluded blocks (comma-separated)",
    "label.recent_worlds": "Recent worlds",
    "menu.about": "About",
    "menu.open_log": "Open Log",
    "menu.options": "Options",
    "menu.set_export_folder": "Set Export Folder",
    "menu.tools": "Tools",
    "options.app_language": "App language",
    "options.block_label": "Block tooltip label",
    "options.cancel": "Cancel",
    "options.click_advance": "Click schematic advances layer",
    "options.combined_tile_size": "Combined export tile size",
    "options.default_textures": "Default textures",
    "options.export_folder": "Export folder",
    "options.export_tile_size": "Layer export tile size",
    "options.hover_tooltip": "Show hover tooltip",
    "options.save": "Save",
    "options.show_grid": "Show grid",
    "options.theme": "Theme",
    "options.title": "Options",
    "options.viewer_cell_size": "Viewer cell size",
    "options.zoom_step": "Mouse wheel zoom step",
    "status.no_structure": "No structure loaded",
    "status.select_world": "Select a level.dat file to begin",
    "status.export_folder_set": "Export folder saved",
    "status.summary_copied": "Block summary copied to clipboard",
    "summary.total_title": "Total visible blocks",
}


class GuiLocale:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self.strings = DEFAULT_GUI_STRINGS.copy()
        ensure_locale_files()
        self.load(language)

    def load(self, language: str) -> None:
        self.language = language
        self.strings = DEFAULT_GUI_STRINGS.copy()
        path = GUI_LOCALE_DIR / f"{language}.json"
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.strings.update({key: str(value) for key, value in data.items() if value})
        except Exception:
            logging.exception("Failed to load GUI localization %s", path)

    def t(self, key: str) -> str:
        return self.strings.get(key, DEFAULT_GUI_STRINGS.get(key, key))


def available_languages() -> list[str]:
    ensure_locale_files()
    values = [path.stem for path in GUI_LOCALE_DIR.glob("*.json") if path.stem != "template"]
    return sorted(values) or ["en"]


def ensure_locale_files() -> None:
    GUI_LOCALE_DIR.mkdir(parents=True, exist_ok=True)
    update_locale_file(GUI_LOCALE_DIR / "en.json", DEFAULT_GUI_STRINGS)
    write_json_if_missing(GUI_LOCALE_DIR / "ru.json", {})
    update_template(GUI_LOCALE_DIR / "template.json")


def write_json_if_missing(path: Path, data: dict[str, str]) -> None:
    if not path.exists():
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def update_locale_file(path: Path, defaults: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = {str(key): str(value) for key, value in data.items()}
    except Exception:
        logging.exception("Failed to read localization file %s", path)
    merged = defaults.copy()
    merged.update(existing)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def update_template(path: Path) -> None:
    existing: dict[str, str] = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = {str(key): str(value) for key, value in data.items()}
    except Exception:
        logging.exception("Failed to read localization template")
    merged = {key: existing.get(key, "") for key in sorted(DEFAULT_GUI_STRINGS)}
    for key, value in existing.items():
        if key not in merged:
            merged[key] = value
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
