"""Build the two distributable zips.

    python tools/make_release.py

    release/PalSchematics (exe).zip            - standalone build
    release/PalSchematics (no-exe source).zip  - pure Python, zero executables

Two files because some antivirus tools flag any PyInstaller executable purely
because of how it is packed; the source zip gives people a way around that
without asking them to trust a binary.

Neither zip contains oo2core_9_win64.dll - that is Palworld's file.
"""
from __future__ import annotations

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "release")

SOURCE_INCLUDE = [
    "main.py", "requirements.txt", "Run PalSchematics.bat", "README.md",
    "BUILDING.md", "LICENSE", "PalSchematics.spec",
]
SOURCE_TREES = ["palschematics", "tools"]
SKIP_DIRS = {"__pycache__", ".venv", "dist", "build", ".git", "release", "docs"}

READ_ME_FIRST = """\
PalSchematics {version}
=======================

BEFORE YOU START
----------------
1. Copy  oo2core_9_win64.dll  into this folder, from your Palworld install:

       Steam\\steamapps\\common\\Palworld\\Pal\\Binaries\\Win64\\

   Palworld 1.0 saves are Oodle-compressed and need the game's own runtime to
   unpack them. That file belongs to the game, so it is not included here.

2. CLOSE PALWORLD, or stop your dedicated server. A running server keeps the
   world in memory and will overwrite your changes on its next autosave.

3. Run PalSchematics.exe

USING IT
--------
File > Open Level.sav
    Single player:     %LOCALAPPDATA%\\Pal\\Saved\\SaveGames\\<id>\\<world>\\Level.sav
    Dedicated server:  Pal\\Saved\\SaveGames\\0\\<world>\\Level.sav

The Players folder must sit next to Level.sav - that is where inventories live.
Pick your character, tick the schematics you want, press Apply to save.

A timestamped .bak backup is written next to your save by default. If anything
looks wrong in game, close the game and copy the .bak back over Level.sav.

Source, build instructions and issues:
    https://github.com/philipjonas88-cpu/PalSchematics

MIT licensed. Fan-made tool, not affiliated with Pocketpair.
"""


def add_tree(zf: zipfile.ZipFile, tree: str, prefix: str = "") -> None:
    base = os.path.join(ROOT, tree)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith((".pyc", ".bak")):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, ROOT)
            zf.write(full, os.path.join(prefix, rel).replace("\\", "/"))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    version = "1.1"
    exe = os.path.join(ROOT, "dist", "PalSchematics.exe")

    if os.path.exists(exe):
        path = os.path.join(OUT, "PalSchematics (exe).zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, "PalSchematics/PalSchematics.exe")
            zf.writestr("PalSchematics/READ ME FIRST.txt",
                        READ_ME_FIRST.format(version=version))
            zf.write(os.path.join(ROOT, "LICENSE"), "PalSchematics/LICENSE")
        print(f"{path}  ({os.path.getsize(path) / 1048576:.1f} MB)")
    else:
        print("dist/PalSchematics.exe not built - skipping the exe zip")

    path = os.path.join(OUT, "PalSchematics (no-exe source).zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in SOURCE_INCLUDE:
            full = os.path.join(ROOT, name)
            if os.path.exists(full):
                zf.write(full, f"PalSchematics/{name}")
        for tree in SOURCE_TREES:
            add_tree(zf, tree, "PalSchematics")
        zf.writestr("PalSchematics/READ ME FIRST.txt",
                    READ_ME_FIRST.format(version=version)
                    .replace("Run PalSchematics.exe",
                             "Double-click 'Run PalSchematics.bat' (needs Python 3.10+)"))
    with zipfile.ZipFile(path) as zf:
        exes = [n for n in zf.namelist() if n.lower().endswith((".exe", ".dll"))]
    assert not exes, f"source zip must contain no binaries, found {exes}"
    print(f"{path}  ({os.path.getsize(path) / 1048576:.1f} MB, 0 executables)")


if __name__ == "__main__":
    main()
