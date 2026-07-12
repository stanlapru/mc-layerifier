from __future__ import annotations

import gzip
import io
import struct
from typing import Any

try:
    import nbtlib
except Exception:  # pragma: no cover - the bundled reader remains as fallback.
    nbtlib = None


class NBTError(Exception):
    pass


class NBTReader:
    TAG_END = 0
    TAG_BYTE = 1
    TAG_SHORT = 2
    TAG_INT = 3
    TAG_LONG = 4
    TAG_FLOAT = 5
    TAG_DOUBLE = 6
    TAG_BYTE_ARRAY = 7
    TAG_STRING = 8
    TAG_LIST = 9
    TAG_COMPOUND = 10
    TAG_INT_ARRAY = 11
    TAG_LONG_ARRAY = 12

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    @classmethod
    def from_maybe_compressed(cls, data: bytes) -> dict[str, Any]:
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return cls(data).read_root()

    def read(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise NBTError("Unexpected end of NBT data")
        part = self.data[self.pos : self.pos + size]
        self.pos += size
        return part

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_i8(self) -> int:
        return struct.unpack(">b", self.read(1))[0]

    def read_i16(self) -> int:
        return struct.unpack(">h", self.read(2))[0]

    def read_i32(self) -> int:
        return struct.unpack(">i", self.read(4))[0]

    def read_i64(self) -> int:
        return struct.unpack(">q", self.read(8))[0]

    def read_string(self) -> str:
        length = struct.unpack(">H", self.read(2))[0]
        return self.read(length).decode("utf-8", errors="replace")

    def read_root(self) -> dict[str, Any]:
        tag_type = self.read_u8()
        if tag_type != self.TAG_COMPOUND:
            raise NBTError(f"Expected compound root, got tag {tag_type}")
        self.read_string()
        return self.read_payload(tag_type)

    def read_payload(self, tag_type: int) -> Any:
        if tag_type == self.TAG_BYTE:
            return self.read_i8()
        if tag_type == self.TAG_SHORT:
            return self.read_i16()
        if tag_type == self.TAG_INT:
            return self.read_i32()
        if tag_type == self.TAG_LONG:
            return self.read_i64()
        if tag_type == self.TAG_FLOAT:
            return struct.unpack(">f", self.read(4))[0]
        if tag_type == self.TAG_DOUBLE:
            return struct.unpack(">d", self.read(8))[0]
        if tag_type == self.TAG_BYTE_ARRAY:
            return self.read(self.read_i32())
        if tag_type == self.TAG_STRING:
            return self.read_string()
        if tag_type == self.TAG_LIST:
            child_type = self.read_u8()
            return [self.read_payload(child_type) for _ in range(self.read_i32())]
        if tag_type == self.TAG_COMPOUND:
            value: dict[str, Any] = {}
            while True:
                child_type = self.read_u8()
                if child_type == self.TAG_END:
                    return value
                value[self.read_string()] = self.read_payload(child_type)
        if tag_type == self.TAG_INT_ARRAY:
            return [self.read_i32() for _ in range(self.read_i32())]
        if tag_type == self.TAG_LONG_ARRAY:
            return [self.read_i64() for _ in range(self.read_i32())]
        raise NBTError(f"Unsupported NBT tag type {tag_type}")


def parse_nbt(data: bytes) -> dict[str, Any]:
    if nbtlib is not None:
        try:
            return nbtlib.File.parse(io.BytesIO(data))
        except Exception:
            pass
    return NBTReader(data).read_root()
