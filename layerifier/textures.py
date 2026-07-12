from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageTk = None


def canonical_block_name(block: str) -> str:
    parts = block.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return f"minecraft:{block}"


class TextureSource:
    def __init__(self) -> None:
        self.image: Any = None
        self.mapping: dict[str, tuple[int, int, int, int]] = {}
        self.files: dict[str, Path] = {}
        self.model_texture_aliases: dict[str, list[str]] = {}
        self.tk_cache: dict[tuple[str, int], Any] = {}
        self.pil_cache: dict[tuple[str, int], Any] = {}
        self.source_description = "built-in generated tiles"

    @property
    def loaded(self) -> bool:
        return self.image is not None or bool(self.files)

    def clear(self) -> None:
        self.image = None
        self.mapping.clear()
        self.files.clear()
        self.model_texture_aliases.clear()
        self.tk_cache.clear()
        self.pil_cache.clear()
        self.source_description = "built-in generated tiles"

    def load(self, path: Path) -> int:
        if Image is None:
            raise RuntimeError("Pillow is required for texture loading. Install with: python -m pip install -r requirements.txt")
        if path.is_dir():
            return self.load_folder(path)
        if path.suffix.lower() == ".json":
            return self.load_json(path)
        raise RuntimeError("Choose a texture folder, a Minecraft atlases/blocks.json file, or a custom atlas JSON file")

    def load_json(self, json_path: Path) -> int:
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        image_value = spec.get("image")
        if image_value:
            image_path = Path(image_value)
            if not image_path.is_absolute():
                image_path = json_path.parent / image_path
            if image_path.is_file():
                return self.load_custom_atlas(json_path, spec, image_path)
        folders = self.folders_from_minecraft_atlas(json_path, spec)
        if folders:
            return self.load_folders(folders, f"Minecraft texture atlas {json_path.name}")
        folder = find_block_texture_folder(json_path)
        if folder:
            return self.load_folder(folder)
        raise RuntimeError("Could not resolve this JSON to textures. For Minecraft jars, choose assets/minecraft/atlases/blocks.json or assets/minecraft/textures/block.")

    def load_custom_atlas(self, json_path: Path, spec: dict[str, Any], image_path: Path) -> int:
        tile_size = int(spec.get("tile_size", 16))
        image = Image.open(image_path).convert("RGBA")
        mapping: dict[str, tuple[int, int, int, int]] = {}
        for block, box in spec.get("blocks", {}).items():
            if not isinstance(box, list):
                continue
            if len(box) == 2:
                x, y = int(box[0]) * tile_size, int(box[1]) * tile_size
                mapping[canonical_block_name(block)] = (x, y, x + tile_size, y + tile_size)
            elif len(box) == 4:
                x, y, w, h = map(int, box)
                mapping[canonical_block_name(block)] = (x, y, x + w, y + h)
        self.clear()
        self.image = image
        self.mapping = mapping
        self.source_description = f"custom atlas {json_path.name}"
        return len(mapping)

    def folders_from_minecraft_atlas(self, json_path: Path, spec: dict[str, Any]) -> list[Path]:
        minecraft_root = find_minecraft_asset_root(json_path)
        if minecraft_root is None:
            return []
        folders: list[Path] = []
        for source in spec.get("sources", []):
            if not isinstance(source, dict):
                continue
            if source.get("type") == "directory" and source.get("source"):
                candidate = minecraft_root / "textures" / str(source["source"])
                if candidate.is_dir():
                    folders.append(candidate)
        return folders

    def load_folder(self, folder: Path) -> int:
        resolved = find_block_texture_folder(folder) or folder
        return self.load_folders([resolved], f"texture folder {resolved}")

    def load_folders(self, folders: list[Path], description: str) -> int:
        files: dict[str, Path] = {}
        texture_folders = texture_folders_with_items(folders)
        for folder, kind in texture_folders:
            for png in folder.rglob("*.png"):
                rel = png.relative_to(folder).with_suffix("").as_posix()
                if kind == "item":
                    names = {f"minecraft:item/{rel}", f"minecraft:item/{png.stem}"}
                else:
                    names = {png.stem, rel, f"minecraft:{png.stem}", f"minecraft:{rel}"}
                    if rel.startswith("block/"):
                        names.add("minecraft:" + rel.removeprefix("block/"))
                for name in names:
                    files.setdefault(canonical_block_name(name), png)
        self.clear()
        self.files = files
        self.model_texture_aliases = load_model_texture_aliases(folders)
        self.source_description = description
        return len(files)

    def texture_candidates(self, block: str) -> list[str]:
        name = canonical_block_name(block)
        namespace, block_name = name.split(":", 1)
        candidates = []
        if prefer_item_texture(block_name):
            candidates.extend(item_texture_candidates(namespace, block_name))
        candidates.append(name)
        candidates.extend(self.model_texture_aliases.get(name, []))
        candidates.extend(heuristic_texture_aliases(name))
        normalized: list[str] = []
        for candidate in candidates:
            if "#" in candidate:
                continue
            candidate = canonical_block_name(candidate)
            normalized.append(candidate)
            ns, path = candidate.split(":", 1)
            if path.startswith("item/"):
                continue
            if path.startswith("block/"):
                normalized.append(f"{ns}:{path.removeprefix('block/')}")
            else:
                normalized.append(f"{ns}:block/{path}")
        result = []
        for candidate in normalized:
            if candidate not in result:
                result.append(candidate)
        return result

    def pil_tile(self, block: str, size: int) -> Any | None:
        if Image is None:
            return None
        key = (canonical_block_name(block), size)
        if key in self.pil_cache:
            return self.pil_cache[key]
        tile = None
        if self.image is not None:
            for candidate in self.texture_candidates(block):
                box = self.mapping.get(candidate)
                if box:
                    tile = self.image.crop(box).resize((size, size), Image.Resampling.NEAREST)
                    break
        else:
            for candidate in self.texture_candidates(block):
                if candidate in self.files:
                    try:
                        tile = load_texture_image(self.files[candidate]).resize((size, size), Image.Resampling.NEAREST)
                    except Exception:
                        tile = None
                    break
        self.pil_cache[key] = tile
        return tile

    def tk_tile(self, block: str, size: int) -> Any | None:
        if ImageTk is None:
            return None
        key = (canonical_block_name(block), size)
        if key not in self.tk_cache:
            tile = self.pil_tile(block, size)
            self.tk_cache[key] = ImageTk.PhotoImage(tile) if tile else None
        return self.tk_cache[key]


def find_minecraft_asset_root(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if candidate.name == "minecraft" and (candidate / "textures").exists():
            return candidate
        nested = candidate / "assets" / "minecraft"
        if (nested / "textures").exists():
            return nested
    return None


def find_block_texture_folder(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    candidates = [current, current / "textures" / "block", current / "assets" / "minecraft" / "textures" / "block"]
    minecraft_root = find_minecraft_asset_root(path)
    if minecraft_root:
        candidates.append(minecraft_root / "textures" / "block")
    for parent in current.parents:
        candidates.append(parent / "textures" / "block")
        candidates.append(parent / "assets" / "minecraft" / "textures" / "block")
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.rglob("*.png")):
            return candidate
    return None


def texture_folders_with_items(folders: list[Path]) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    for folder in folders:
        kind = "item" if folder.name == "item" else "block"
        result.append((folder, kind))
        root = find_minecraft_asset_root(folder)
        item_folder = root / "textures" / "item" if root else None
        if item_folder and item_folder.is_dir() and all(item_folder != existing for existing, _kind in result):
            result.append((item_folder, "item"))
    return result


def load_texture_image(path: Path) -> Any:
    image = Image.open(path).convert("RGBA")
    if image.height > image.width and image.height % image.width == 0:
        image = image.crop((0, 0, image.width, image.width))
    return image


def load_model_texture_aliases(paths: list[Path]) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    roots = []
    for path in paths:
        root = find_minecraft_asset_root(path)
        if root and root not in roots:
            roots.append(root)
    for root in roots:
        blockstates = root / "blockstates"
        models = root / "models" / "block"
        if not blockstates.is_dir() or not models.is_dir():
            continue
        model_cache: dict[str, dict[str, str]] = {}
        for state_path in blockstates.glob("*.json"):
            block = f"minecraft:{state_path.stem}"
            model_names = blockstate_models(state_path)
            texture_names: list[str] = []
            for model_name in model_names[:12]:
                textures = resolve_model_textures(root, model_name, model_cache)
                for texture in choose_model_textures(textures):
                    if texture not in texture_names:
                        texture_names.append(texture)
            if texture_names:
                aliases[block] = texture_names
    return aliases


def blockstate_models(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    models: list[str] = []

    def add_model(value: Any) -> None:
        if isinstance(value, dict) and isinstance(value.get("model"), str):
            model = value["model"]
            if model not in models:
                models.append(model)
        elif isinstance(value, list):
            for item in value:
                add_model(item)

    variants = data.get("variants")
    if isinstance(variants, dict):
        for value in variants.values():
            add_model(value)
    multipart = data.get("multipart")
    if isinstance(multipart, list):
        for part in multipart:
            if isinstance(part, dict):
                add_model(part.get("apply"))
    return models


def resolve_model_textures(root: Path, model_name: str, cache: dict[str, dict[str, str]]) -> dict[str, str]:
    if model_name in cache:
        return cache[model_name]
    path_name = model_name.split(":", 1)[-1]
    if path_name.startswith("block/"):
        path_name = path_name.removeprefix("block/")
    model_path = root / "models" / "block" / f"{path_name}.json"
    textures: dict[str, str] = {}
    try:
        data = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        cache[model_name] = textures
        return textures
    parent = data.get("parent")
    if isinstance(parent, str):
        textures.update(resolve_model_textures(root, parent, cache))
    own = data.get("textures")
    if isinstance(own, dict):
        for key, value in own.items():
            textures[str(key)] = str(value)
    resolved: dict[str, str] = {}
    for key in textures:
        resolved[key] = resolve_texture_reference(textures, textures[key])
    cache[model_name] = resolved
    return resolved


def resolve_texture_reference(textures: dict[str, str], value: str) -> str:
    seen = set()
    while value.startswith("#") and value[1:] in textures and value not in seen:
        seen.add(value)
        value = textures[value[1:]]
    if ":" not in value:
        value = "minecraft:" + value
    return value


def choose_model_textures(textures: dict[str, str]) -> list[str]:
    preferred = ("top", "all", "texture", "side", "end", "particle", "bottom", "front")
    chosen: list[str] = []
    for key in preferred:
        value = textures.get(key)
        if value and not value.startswith("#") and value not in chosen:
            chosen.append(value)
    for value in textures.values():
        if value and not value.startswith("#") and value not in chosen:
            chosen.append(value)
    return chosen


def heuristic_texture_aliases(block: str) -> list[str]:
    namespace, name = canonical_block_name(block).split(":", 1)
    aliases: list[str] = []
    wood_types = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "bamboo", "crimson", "warped")
    for wood in wood_types:
        if name.startswith(wood + "_") and any(name.endswith(suffix) for suffix in ("_fence", "_fence_gate", "_stairs", "_slab", "_button", "_pressure_plate", "_door", "_trapdoor", "_sign", "_wall_sign", "_hanging_sign")):
            aliases.append(f"{namespace}:{wood}_planks")
    suffixes = ("_stairs", "_slab", "_wall", "_button", "_pressure_plate")
    for suffix in suffixes:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            aliases.append(f"{namespace}:{base}")
            aliases.append(f"{namespace}:{pluralize_base(base)}")
    if name.endswith("_fence") or name.endswith("_fence_gate"):
        base = name.removesuffix("_fence_gate").removesuffix("_fence")
        aliases.append(f"{namespace}:{base}_planks")
        aliases.append(f"{namespace}:{base}")
    if name.endswith("_wood"):
        aliases.append(f"{namespace}:{name.removesuffix('_wood')}_log")
    return aliases


def prefer_item_texture(block_name: str) -> bool:
    exact = {
        "torch", "wall_torch", "soul_torch", "soul_wall_torch", "redstone_torch", "redstone_wall_torch",
        "lantern", "soul_lantern", "redstone_comparator", "comparator", "redstone_repeater", "repeater",
        "lever", "tripwire_hook", "bell", "flower_pot", "decorated_pot", "chain", "end_rod",
    }
    suffixes = ("_candle", "_candle_cake", "_banner", "_wall_banner", "_head", "_wall_head", "_skull", "_wall_skull")
    return block_name in exact or any(block_name.endswith(suffix) for suffix in suffixes)


def item_texture_candidates(namespace: str, block_name: str) -> list[str]:
    aliases = [block_name]
    replacements = {
        "wall_torch": "torch",
        "soul_wall_torch": "soul_torch",
        "redstone_wall_torch": "redstone_torch",
        "redstone_comparator": "comparator",
        "redstone_repeater": "repeater",
    }
    aliases.append(replacements.get(block_name, block_name))
    for suffix in ("_wall_banner", "_wall_head", "_wall_skull"):
        if block_name.endswith(suffix):
            aliases.append(block_name.replace("_wall_", "_"))
    return [f"{namespace}:item/{alias}" for alias in dict.fromkeys(aliases)]


def pluralize_base(name: str) -> str:
    if name.endswith("brick"):
        return name + "s"
    if name.endswith("tile"):
        return name + "s"
    if name == "deepslate_brick":
        return "deepslate_bricks"
    if name == "stone_brick":
        return "stone_bricks"
    if name == "nether_brick":
        return "nether_bricks"
    return name


def block_color(block: str) -> str:
    known = {
        "minecraft:stone": "#777777", "minecraft:cobblestone": "#696969", "minecraft:dirt": "#7b5938",
        "minecraft:grass_block": "#5f9f3a", "minecraft:oak_planks": "#b58a4c", "minecraft:planks": "#b58a4c",
        "minecraft:sand": "#d8cb8d", "minecraft:gravel": "#888888", "minecraft:glass": "#a6d8df",
        "minecraft:water": "#315bd8", "minecraft:lava": "#e65a1a", "minecraft:bricks": "#9b4a37",
        "minecraft:brick_block": "#9b4a37", "minecraft:obsidian": "#191428", "minecraft:bedrock": "#444444",
        "minecraft:torch": "#f5d142", "minecraft:oak_log": "#73512f", "minecraft:log": "#73512f",
        "minecraft:oak_leaves": "#3f7f35", "minecraft:leaves": "#3f7f35", "minecraft:white_wool": "#eeeeee",
        "minecraft:wool": "#eeeeee",
    }
    block = canonical_block_name(block)
    if block in known:
        return known[block]
    seed = 0
    for ch in block:
        seed = (seed * 131 + ord(ch)) & 0xFFFFFF
    return f"#{80 + (seed & 0x7F):02x}{80 + ((seed >> 7) & 0x7F):02x}{80 + ((seed >> 14) & 0x7F):02x}"


def generated_tile(block: str, size: int) -> Any | None:
    if Image is None or ImageDraw is None:
        return None
    color = block_color(block)
    image = Image.new("RGBA", (size, size), color)
    draw = ImageDraw.Draw(image)
    shade = tuple(max(0, int(color[i : i + 2], 16) - 35) for i in (1, 3, 5)) + (255,)
    draw.line((0, 0, size - 1, 0), fill=(255, 255, 255, 70))
    draw.line((0, 0, 0, size - 1), fill=(255, 255, 255, 45))
    draw.line((size - 1, 0, size - 1, size - 1), fill=shade)
    draw.line((0, size - 1, size - 1, size - 1), fill=shade)
    if "glass" in block:
        draw.line((2, 2, size - 3, size - 3), fill=(230, 255, 255, 130))
    if "log" in block:
        draw.ellipse((size * 0.25, size * 0.25, size * 0.75, size * 0.75), outline=(70, 45, 25, 180))
    return image


def parse_exclusions(text: str) -> set[str]:
    values = set()
    for item in text.replace("\n", ",").split(","):
        name = item.strip()
        if name:
            values.add(canonical_block_name(name))
    return values
