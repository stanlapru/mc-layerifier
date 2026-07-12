from __future__ import annotations

import gzip
import logging
import math
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .nbt import NBTError, parse_nbt


U64_MASK = (1 << 64) - 1

OLD_BLOCK_NAMES: dict[int, str] = {
    0: "minecraft:air", 1: "minecraft:stone", 2: "minecraft:grass_block", 3: "minecraft:dirt", 4: "minecraft:cobblestone",
    5: "minecraft:planks", 6: "minecraft:sapling", 7: "minecraft:bedrock", 8: "minecraft:water", 9: "minecraft:water",
    10: "minecraft:lava", 11: "minecraft:lava", 12: "minecraft:sand", 13: "minecraft:gravel", 14: "minecraft:gold_ore",
    15: "minecraft:iron_ore", 16: "minecraft:coal_ore", 17: "minecraft:log", 18: "minecraft:leaves", 19: "minecraft:sponge",
    20: "minecraft:glass", 21: "minecraft:lapis_ore", 22: "minecraft:lapis_block", 23: "minecraft:dispenser", 24: "minecraft:sandstone",
    25: "minecraft:noteblock", 26: "minecraft:bed", 27: "minecraft:golden_rail", 28: "minecraft:detector_rail", 29: "minecraft:sticky_piston",
    30: "minecraft:cobweb", 31: "minecraft:tallgrass", 32: "minecraft:dead_bush", 33: "minecraft:piston", 35: "minecraft:wool",
    37: "minecraft:dandelion", 38: "minecraft:poppy", 39: "minecraft:brown_mushroom", 40: "minecraft:red_mushroom", 41: "minecraft:gold_block",
    42: "minecraft:iron_block", 43: "minecraft:double_stone_slab", 44: "minecraft:stone_slab", 45: "minecraft:bricks", 46: "minecraft:tnt",
    47: "minecraft:bookshelf", 48: "minecraft:mossy_cobblestone", 49: "minecraft:obsidian", 50: "minecraft:torch", 51: "minecraft:fire",
    52: "minecraft:spawner", 53: "minecraft:oak_stairs", 54: "minecraft:chest", 55: "minecraft:redstone_wire", 56: "minecraft:diamond_ore",
    57: "minecraft:diamond_block", 58: "minecraft:crafting_table", 59: "minecraft:wheat", 60: "minecraft:farmland", 61: "minecraft:furnace",
    62: "minecraft:lit_furnace", 63: "minecraft:standing_sign", 64: "minecraft:wooden_door", 65: "minecraft:ladder", 66: "minecraft:rail",
    67: "minecraft:stone_stairs", 68: "minecraft:wall_sign", 69: "minecraft:lever", 70: "minecraft:stone_pressure_plate", 71: "minecraft:iron_door",
    72: "minecraft:wooden_pressure_plate", 73: "minecraft:redstone_ore", 74: "minecraft:lit_redstone_ore", 75: "minecraft:unlit_redstone_torch",
    76: "minecraft:redstone_torch", 77: "minecraft:stone_button", 78: "minecraft:snow_layer", 79: "minecraft:ice", 80: "minecraft:snow",
    81: "minecraft:cactus", 82: "minecraft:clay", 83: "minecraft:reeds", 84: "minecraft:jukebox", 85: "minecraft:fence",
    86: "minecraft:pumpkin", 87: "minecraft:netherrack", 88: "minecraft:soul_sand", 89: "minecraft:glowstone", 90: "minecraft:portal",
    91: "minecraft:lit_pumpkin", 95: "minecraft:stained_glass", 98: "minecraft:stonebrick", 101: "minecraft:iron_bars", 102: "minecraft:glass_pane",
    103: "minecraft:melon_block", 107: "minecraft:fence_gate", 108: "minecraft:brick_stairs", 109: "minecraft:stone_brick_stairs",
    112: "minecraft:nether_brick", 113: "minecraft:nether_brick_fence", 114: "minecraft:nether_brick_stairs", 121: "minecraft:end_stone",
    123: "minecraft:redstone_lamp", 125: "minecraft:double_wooden_slab", 126: "minecraft:wooden_slab", 129: "minecraft:emerald_ore",
    133: "minecraft:emerald_block", 152: "minecraft:redstone_block", 155: "minecraft:quartz_block", 156: "minecraft:quartz_stairs",
    159: "minecraft:stained_hardened_clay", 160: "minecraft:stained_glass_pane", 161: "minecraft:leaves2", 162: "minecraft:log2",
    168: "minecraft:prismarine", 169: "minecraft:sea_lantern", 172: "minecraft:hardened_clay", 173: "minecraft:coal_block",
    174: "minecraft:packed_ice", 179: "minecraft:red_sandstone", 180: "minecraft:red_sandstone_stairs", 181: "minecraft:double_stone_slab2",
    182: "minecraft:stone_slab2",
}


@dataclass(frozen=True)
class Bounds:
    x1: int
    y1: int
    z1: int
    x2: int
    y2: int
    z2: int

    @classmethod
    def normalized(cls, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> "Bounds":
        return cls(min(x1, x2), min(y1, y2), min(z1, z2), max(x1, x2), max(y1, y2), max(z1, z2))

    def axis_range(self, axis: str) -> tuple[int, int]:
        if axis == "X":
            return self.x1, self.x2
        if axis == "Y":
            return self.y1, self.y2
        return self.z1, self.z2

    def descriptor(self) -> str:
        return f"X{self.x1}_{self.x2}_Y{self.y1}_{self.y2}_Z{self.z1}_{self.z2}"


class RegionFile:
    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("rb")
        self._locations = self._fh.read(4096)
        self._fh.read(4096)

    def close(self) -> None:
        self._fh.close()

    def read_chunk(self, chunk_x: int, chunk_z: int) -> dict[str, Any] | None:
        local_x = chunk_x % 32
        local_z = chunk_z % 32
        entry = self._locations[4 * (local_x + local_z * 32) : 4 * (local_x + local_z * 32) + 4]
        if len(entry) < 4:
            return None
        offset = int.from_bytes(entry[:3], "big")
        sectors = entry[3]
        if offset == 0 or sectors == 0:
            return None
        self._fh.seek(offset * 4096)
        length_bytes = self._fh.read(4)
        if len(length_bytes) != 4:
            return None
        length = int.from_bytes(length_bytes, "big")
        compression = self._fh.read(1)
        payload = self._fh.read(length - 1)
        if compression == b"\x01":
            raw = gzip.decompress(payload)
        elif compression == b"\x02":
            raw = zlib.decompress(payload)
        elif compression == b"\x03":
            raw = payload
        else:
            raise NBTError(f"Unsupported chunk compression {compression!r} in {self.path}")
        return parse_nbt(raw)


class MinecraftWorld:
    def __init__(self, level_dat: Path):
        self.level_dat = level_dat
        self.world_dir = level_dat.parent
        self.region_dir = self.world_dir / "region"
        if not self.region_dir.is_dir():
            raise FileNotFoundError(f"No region directory found next to {level_dat}")
        self.regions: dict[tuple[int, int], RegionFile] = {}
        self.chunks: dict[tuple[int, int], dict[str, Any] | None] = {}
        self.failed_chunks = 0

    def close(self) -> None:
        for region in self.regions.values():
            region.close()
        self.regions.clear()

    def region_for_chunk(self, chunk_x: int, chunk_z: int) -> RegionFile | None:
        region_x = math.floor(chunk_x / 32)
        region_z = math.floor(chunk_z / 32)
        key = (region_x, region_z)
        if key in self.regions:
            return self.regions[key]
        path = self.region_dir / f"r.{region_x}.{region_z}.mca"
        if not path.exists():
            return None
        self.regions[key] = RegionFile(path)
        return self.regions[key]

    def read_chunk(self, chunk_x: int, chunk_z: int) -> dict[str, Any] | None:
        key = (chunk_x, chunk_z)
        if key not in self.chunks:
            region = self.region_for_chunk(chunk_x, chunk_z)
            self.chunks[key] = region.read_chunk(chunk_x, chunk_z) if region else None
        return self.chunks[key]

    def load_blocks(self, bounds: Bounds, progress: Callable[[int, int], None] | None = None) -> dict[tuple[int, int, int], str]:
        blocks: dict[tuple[int, int, int], str] = {}
        self.failed_chunks = 0
        min_cx = math.floor(bounds.x1 / 16)
        max_cx = math.floor(bounds.x2 / 16)
        min_cz = math.floor(bounds.z1 / 16)
        max_cz = math.floor(bounds.z2 / 16)
        chunks = [(cx, cz) for cz in range(min_cz, max_cz + 1) for cx in range(min_cx, max_cx + 1)]
        for index, (chunk_x, chunk_z) in enumerate(chunks, start=1):
            if progress:
                progress(index, len(chunks))
            try:
                chunk = self.read_chunk(chunk_x, chunk_z)
                if chunk:
                    extract_chunk_blocks(chunk, bounds, blocks)
            except Exception:
                self.failed_chunks += 1
                logging.exception("Failed to read chunk %s,%s", chunk_x, chunk_z)
        return blocks


def nibble_at(data: bytes, index: int) -> int:
    value = data[index // 2]
    return value & 0x0F if index % 2 == 0 else (value >> 4) & 0x0F


def palette_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("Name") or entry.get("name") or "minecraft:air")
    return str(entry)


def unpack_palette_indices(longs: list[int], bits: int, count: int = 4096) -> list[int]:
    if longs is None or len(longs) == 0:
        return [0] * count
    bits = max(bits, 1)
    mask = (1 << bits) - 1
    values_per_long = max(1, 64 // bits)
    expected_padded = math.ceil(count / values_per_long)
    expected_compact = math.ceil(count * bits / 64)
    unsigned = [int(value) & U64_MASK for value in longs]
    indices: list[int] = []
    if len(longs) == expected_padded or len(longs) > expected_compact:
        for i in range(count):
            long_index = i // values_per_long
            shift = (i % values_per_long) * bits
            indices.append(((unsigned[long_index] >> shift) & mask) if long_index < len(unsigned) else 0)
        return indices
    for i in range(count):
        bit_index = i * bits
        long_index = bit_index // 64
        bit_offset = bit_index % 64
        if long_index >= len(unsigned):
            indices.append(0)
            continue
        value = unsigned[long_index] >> bit_offset
        if bit_offset + bits > 64 and long_index + 1 < len(unsigned):
            value |= unsigned[long_index + 1] << (64 - bit_offset)
        indices.append(value & mask)
    return indices


def chunk_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    level = chunk.get("Level")
    return level if isinstance(level, dict) else chunk


def extract_chunk_blocks(chunk: dict[str, Any], bounds: Bounds, out: dict[tuple[int, int, int], str]) -> None:
    payload = chunk_payload(chunk)
    chunk_x = int(payload.get("xPos", chunk.get("xPos", 0)))
    chunk_z = int(payload.get("zPos", chunk.get("zPos", 0)))
    sections = payload.get("sections") or payload.get("Sections") or []
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_y = int(section.get("Y", section.get("y", 0)))
        world_y_base = section_y * 16
        if world_y_base > bounds.y2 or world_y_base + 15 < bounds.y1:
            continue
        modern_states = section.get("block_states")
        if isinstance(modern_states, dict):
            extract_modern_section(modern_states, chunk_x, chunk_z, world_y_base, bounds, out)
        elif "Palette" in section or "BlockStates" in section:
            extract_modern_section(section, chunk_x, chunk_z, world_y_base, bounds, out)
        elif "Blocks" in section:
            extract_old_section(section, chunk_x, chunk_z, world_y_base, bounds, out)


def extract_modern_section(states: dict[str, Any], chunk_x: int, chunk_z: int, world_y_base: int, bounds: Bounds, out: dict[tuple[int, int, int], str]) -> None:
    palette = states.get("palette")
    if palette is None:
        palette = states.get("Palette")
    if palette is None or len(palette) == 0:
        return
    names = [palette_name(entry) for entry in palette]
    data = states.get("data")
    if data is None:
        data = states.get("BlockStates")
    if data is None:
        data = []
    indices = unpack_palette_indices(data, max(4, math.ceil(math.log2(max(1, len(names))))))
    for ly in range(16):
        y = world_y_base + ly
        if y < bounds.y1 or y > bounds.y2:
            continue
        for lz in range(16):
            z = chunk_z * 16 + lz
            if z < bounds.z1 or z > bounds.z2:
                continue
            for lx in range(16):
                x = chunk_x * 16 + lx
                if x < bounds.x1 or x > bounds.x2:
                    continue
                idx = (ly * 16 + lz) * 16 + lx
                palette_index = indices[idx]
                if palette_index < len(names) and names[palette_index] != "minecraft:air":
                    out[(x, y, z)] = names[palette_index]


def extract_old_section(section: dict[str, Any], chunk_x: int, chunk_z: int, world_y_base: int, bounds: Bounds, out: dict[tuple[int, int, int], str]) -> None:
    blocks = section.get("Blocks")
    if not isinstance(blocks, (bytes, bytearray)) or len(blocks) < 4096:
        return
    add = section.get("Add") if isinstance(section.get("Add"), (bytes, bytearray)) else None
    data = section.get("Data") if isinstance(section.get("Data"), (bytes, bytearray)) else None
    for ly in range(16):
        y = world_y_base + ly
        if y < bounds.y1 or y > bounds.y2:
            continue
        for lz in range(16):
            z = chunk_z * 16 + lz
            if z < bounds.z1 or z > bounds.z2:
                continue
            for lx in range(16):
                x = chunk_x * 16 + lx
                if x < bounds.x1 or x > bounds.x2:
                    continue
                idx = (ly * 16 + lz) * 16 + lx
                block_id = blocks[idx]
                if add:
                    block_id |= nibble_at(add, idx) << 8
                if block_id == 0:
                    continue
                meta = nibble_at(data, idx) if data else 0
                name = OLD_BLOCK_NAMES.get(block_id, f"minecraft:legacy_{block_id}")
                out[(x, y, z)] = f"{name}:{meta}" if meta else name
