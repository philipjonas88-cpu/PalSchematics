"""Reading and writing Palworld 1.0 save files.

Palworld 1.0 compresses saves with Oodle and tags them ``PlM``; older saves use
zlib and are tagged ``PlZ``. This module reads both and -- importantly --
writes back in *whatever format the file already used*. Editors that always
emit PlZ do work in single player, but a dedicated server's Level.sav is
better left in the exact container the server itself produces.

The GVAS tree is decoded with a deliberately narrow custom-property policy:
only the character map is fully interpreted, everything else round-trips as
raw bytes. Item containers are then edited at the byte level (see
``inventory``). That keeps an untouched save byte-for-byte identical through a
load/save cycle, which the app asserts before it writes anything.

Oodle decoding needs the game's own runtime, ``oo2core_9_win64.dll``. It ships
with Palworld; PalSchematics looks for it next to the program.
"""
from __future__ import annotations

import ctypes
import datetime
import os
import shutil
import struct
import sys
import zlib

import palworld_save_tools.palsav as palsav
import palworld_save_tools.rawdata.character as character
from palworld_save_tools.archive import FArchiveReader, FArchiveWriter
from palworld_save_tools.gvas import GvasFile
from palworld_save_tools.paltypes import (
    PALWORLD_CUSTOM_PROPERTIES,
    PALWORLD_TYPE_HINTS,
)

CHAR_KEY = ".worldSaveData.CharacterSaveParameterMap.Value.RawData"
_HERE = os.path.dirname(os.path.abspath(__file__))
OODLE_DLL = "oo2core_9_win64.dll"


class SaveError(RuntimeError):
    """Anything that makes a save unreadable or unsafe to write."""


# --------------------------------------------------------------------------
# Oodle
# --------------------------------------------------------------------------
def _search_dirs() -> list[str]:
    """Where the Oodle runtime might sit.

    In a PyInstaller build the DLL is deliberately *not* bundled -- it belongs
    to the game -- so the folder holding the .exe is the important one. The
    unpacked bundle dir is checked too in case someone does bundle it.
    """
    dirs = [os.path.dirname(_HERE)]
    if getattr(sys, "frozen", False):
        dirs.insert(0, os.path.dirname(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(meipass)
    return dirs


def oodle_path() -> str:
    for d in _search_dirs():
        candidate = os.path.join(d, OODLE_DLL)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_search_dirs()[0], OODLE_DLL)


def have_oodle() -> bool:
    return os.path.exists(oodle_path())


_oodle = None


def _load_oodle():
    global _oodle
    if _oodle is None:
        if not have_oodle():
            raise SaveError(
                f"{OODLE_DLL} not found next to PalSchematics.\n\n"
                "Palworld 1.0 saves are Oodle-compressed and need the game's own\n"
                "runtime to unpack. Copy that file from your Palworld install\n"
                "(Palworld/Pal/Binaries/Win64/) into this program's folder."
            )
        _oodle = ctypes.WinDLL(oodle_path())
    return _oodle


def oodle_decompress(payload: bytes, raw_len: int) -> bytes:
    fn = _load_oodle().OodleLZ_Decompress
    fn.restype = ctypes.c_longlong
    fn.argtypes = [ctypes.c_char_p, ctypes.c_longlong,
                   ctypes.c_char_p, ctypes.c_longlong,
                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                   ctypes.c_void_p, ctypes.c_longlong,
                   ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_longlong, ctypes.c_int]
    out = ctypes.create_string_buffer(raw_len)
    n = fn(payload, len(payload), out, raw_len, 1, 0, 0,
           None, 0, None, None, None, 0, 3)
    if n != raw_len:
        raise SaveError(f"Oodle decompress returned {n}, expected {raw_len}")
    return out.raw[:n]


def oodle_compress(data: bytes) -> bytes:
    fn = _load_oodle().OodleLZ_Compress
    fn.restype = ctypes.c_longlong
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_longlong, ctypes.c_char_p,
                   ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_longlong]
    buf = ctypes.create_string_buffer(len(data) + 274 + len(data) // 4)
    n = fn(8, data, len(data), buf, 4, None, None, None, None, 0)  # Kraken, Normal
    if n <= 0:
        raise SaveError("Oodle compression failed")
    return buf.raw[:n]


# --------------------------------------------------------------------------
# Container format
# --------------------------------------------------------------------------
_orig_decompress = palsav.decompress_sav_to_gvas


def decompress(data: bytes) -> tuple[bytes, int, bytes]:
    """Return (gvas_bytes, save_type, magic)."""
    if len(data) < 12:
        raise SaveError("file is too small to be a Palworld save")
    magic = data[8:11]
    if magic == b"PlM":
        raw_len = struct.unpack("<I", data[0:4])[0]
        save_type = data[11]
        raw = oodle_decompress(data[12:], raw_len)
        if raw[:4] != b"GVAS":
            raise SaveError("decompressed payload is not a GVAS blob")
        return raw, save_type, magic
    if magic == b"PlZ":
        gvas, save_type = _orig_decompress(data)
        return gvas, save_type, magic
    raise SaveError(f"unrecognised save format (magic {magic!r})")


def compress(gvas_bytes: bytes, save_type: int, magic: bytes) -> bytes:
    """Re-wrap GVAS bytes in the same container the file arrived in."""
    if magic == b"PlM":
        payload = oodle_compress(gvas_bytes)
        if oodle_decompress(payload, len(gvas_bytes)) != gvas_bytes:
            raise SaveError("Oodle round-trip check failed -- refusing to write")
        return struct.pack("<II", len(gvas_bytes), len(payload)) + b"PlM" + bytes([save_type]) + payload
    once = zlib.compress(gvas_bytes)
    if save_type == 0x32:
        payload = zlib.compress(once)
    elif save_type == 0x31:
        payload = once
    else:
        raise SaveError(f"unknown PlZ save type {save_type:#x}")
    return struct.pack("<II", len(gvas_bytes), len(once)) + b"PlZ" + bytes([save_type]) + payload


# --------------------------------------------------------------------------
# Palworld 1.0 per-character rawdata (extra trailing bytes vs. older saves)
# --------------------------------------------------------------------------
def _decode_char_bytes(parent_reader, char_bytes):
    reader = parent_reader.internal_copy(bytes(char_bytes), debug=False)
    data = {
        "object": reader.properties_until_end(),
        "unknown_bytes": reader.byte_list(4),
        "group_id": reader.guid(),
    }
    trailer = bytearray()
    while not reader.eof():
        trailer += bytes(reader.byte_list(1))
    data["trailer_bytes"] = list(trailer)
    return data


def _encode_char_bytes(prop) -> bytes:
    writer = FArchiveWriter()
    writer.properties(prop["object"])
    writer.write(bytes(prop["unknown_bytes"]))
    writer.guid(prop["group_id"])
    writer.write(bytes(prop.get("trailer_bytes", [])))
    return writer.bytes()


character.decode_bytes = _decode_char_bytes
character.encode_bytes = _encode_char_bytes


# --------------------------------------------------------------------------
# SetProperty
#
# Palworld's later updates introduced set-typed world properties (the pal
# locker, for one: .worldSaveData.InLockerCharacterInstanceIDArray).
# palworld_save_tools 0.24 does not implement the type at all and aborts the
# whole parse, so a save from an updated server cannot be opened.
#
# We do not need to understand the contents -- nothing here edits them -- so
# the payload is carried through verbatim. The layout of a tagged SetProperty
# is: inner type (FString), optional guid, then `size` bytes of payload
# (removed-count u32, count u32, then the elements). Reading and writing that
# span unchanged keeps the file byte-for-byte identical, which the round-trip
# check then proves.
# --------------------------------------------------------------------------
_orig_reader_property = FArchiveReader.property
_orig_writer_property_inner = FArchiveWriter.property_inner


def _reader_property(self, type_name, size, path, nested_caller_path=""):
    if type_name == "SetProperty" and path not in self.custom_properties:
        return {
            "set_type": self.fstring(),
            "id": self.optional_guid(),
            "value": {"raw": list(self.read(size))},
            "type": "SetProperty",
        }
    return _orig_reader_property(self, type_name, size, path, nested_caller_path)


def _writer_property_inner(self, property_type, property):
    if property_type == "SetProperty" and "custom_type" not in property:
        self.fstring(property["set_type"])
        self.optional_guid(property.get("id", None))
        payload = bytes(property["value"]["raw"])
        self.write(payload)
        return len(payload)
    return _orig_writer_property_inner(self, property_type, property)


FArchiveReader.property = _reader_property
FArchiveWriter.property_inner = _writer_property_inner

CUSTOM = {CHAR_KEY: PALWORLD_CUSTOM_PROPERTIES[CHAR_KEY]}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
class Save:
    """A loaded .sav: the GVAS tree plus everything needed to write it back."""

    def __init__(self, path: str, gvas: GvasFile, save_type: int, magic: bytes,
                 original_gvas: bytes, mtime: float, size: int):
        self.path = path
        self.gvas = gvas
        self.save_type = save_type
        self.magic = magic
        self.original_gvas = original_gvas
        self.mtime = mtime
        self.size = size
        self.spent = False  # set once the tree has been encoded (see to_bytes)

    @classmethod
    def load(cls, path: str, custom=CUSTOM) -> "Save":
        st = os.stat(path)
        with open(path, "rb") as f:
            raw = f.read()
        gvas_bytes, save_type, magic = decompress(raw)
        try:
            gvas = GvasFile.read(gvas_bytes, PALWORLD_TYPE_HINTS, custom)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
            raise SaveError(f"could not parse {os.path.basename(path)}: {exc}") from exc
        return cls(path, gvas, save_type, magic, gvas_bytes, st.st_mtime, st.st_size)

    # -- safety ------------------------------------------------------------
    def verify_roundtrip(self, custom=CUSTOM) -> None:
        """Re-encode an unmodified copy and require an exact byte match.

        If this fails, this build cannot represent the save losslessly and must
        not write it. It is the single most important check in the program.

        The check runs on a *second, throwaway* parse of the same bytes, because
        palworld_save_tools' writer edits the tree in place as it encodes --
        running it over ``self.gvas`` would leave this object unusable. That
        costs another parse of a large save, which is why loading is slow.
        """
        scratch = GvasFile.read(self.original_gvas, PALWORLD_TYPE_HINTS, custom)
        if scratch.write(custom) != self.original_gvas:
            raise SaveError(
                "safety check failed: this save does not survive a load/save\n"
                "cycle byte-for-byte, so PalSchematics will not modify it.\n"
                "Please report the save version -- the format has probably changed."
            )

    def changed_on_disk(self) -> bool:
        """True if something wrote the file since we loaded it (e.g. a live server)."""
        try:
            st = os.stat(self.path)
        except OSError:
            return True
        return st.st_mtime != self.mtime or st.st_size != self.size

    # -- writing -----------------------------------------------------------
    def to_bytes(self, custom=CUSTOM) -> bytes:
        """Serialise the save. Consumes this object -- see ``spent``.

        Encoding rewrites decoded sub-structures back into raw bytes *inside*
        the tree, so the tree cannot be inspected or encoded again afterwards.
        Reload the file to keep working.
        """
        if self.spent:
            raise SaveError("this save has already been written; reload it before editing again")
        data = compress(self.gvas.write(custom), self.save_type, self.magic)
        self.spent = True
        return data

    @property
    def world(self):
        return self.gvas.properties["worldSaveData"]["value"]


def write_save(save: Save, *, backup: bool = True,
               expect: tuple[str, list[str]] | None = None) -> str | None:
    """Write ``save`` back to its own path as safely as this can be done.

    The order matters: build the new file beside the original, re-open it and
    confirm it parses *and* contains what we put in it, only then take a backup
    and swap it in with an atomic replace. A crash at any point leaves the
    original file intact.

    ``expect`` is ``(container_guid, [static_ids])`` to check for. Returns the
    backup path, or None if backups were switched off.
    """
    from .inventory import containers_by_guid

    if save.changed_on_disk():
        raise SaveError(
            "the save file changed on disk since it was opened -- the game or "
            "server is probably still running. Nothing was written.")

    tmp = save.path + ".palschematics.tmp"
    data = save.to_bytes()
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        check = Save.load(tmp)
        if expect:
            guid, codes = expect
            container = containers_by_guid(check).get(guid)
            if container is None:
                raise SaveError("verification failed: container missing from written file")
            present = {s.static_id for s in container.slots()}
            missing = [c for c in codes if c not in present]
            if missing:
                raise SaveError("verification failed: " + ", ".join(missing)
                                + " missing from the written file")
        backup_path = None
        if backup:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{save.path}.{stamp}.bak"
            shutil.copy2(save.path, backup_path)
        os.replace(tmp, save.path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    st = os.stat(save.path)
    save.mtime, save.size = st.st_mtime, st.st_size
    return backup_path
