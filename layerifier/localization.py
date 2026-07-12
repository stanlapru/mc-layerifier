from __future__ import annotations

import json
from pathlib import Path

from .textures import canonical_block_name, find_minecraft_asset_root


class BlockNames:
    def __init__(self) -> None:
        self.locale = "en_us"
        self.names: dict[str, str] = {}

    def load_from_path(self, path: Path, locale: str = "en_us") -> int:
        asset_root = find_minecraft_asset_root(path)
        if asset_root is None:
            return 0
        lang_path = asset_root / "lang" / f"{locale}.json"
        if not lang_path.is_file() and locale != "en_us":
            lang_path = asset_root / "lang" / "en_us.json"
        if not lang_path.is_file():
            return 0
        data = json.loads(lang_path.read_text(encoding="utf-8"))
        self.locale = locale
        self.names = {key: str(value) for key, value in data.items() if key.startswith("block.")}
        return len(self.names)

    def name_for(self, block: str) -> str:
        block = canonical_block_name(block)
        namespace, name = block.split(":", 1)
        key = f"block.{namespace}.{name.replace('/', '.')}"
        return self.names.get(key) or title_from_id(name)


def title_from_id(name: str) -> str:
    return name.rsplit("/", 1)[-1].replace("_", " ").title()
