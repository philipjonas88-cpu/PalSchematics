# Building PalSchematics from source

This document exists so anyone — including a mod host's review team — can
reproduce the published `PalSchematics.exe` from the source in this repository
and confirm it does nothing beyond what it claims.

## What the program does

It opens a Palworld save file (`Level.sav`), adds schematic items to a chosen
player's inventory, and writes the file back. It makes **no network requests at
runtime**, reads nothing outside the save folder you point it at, and writes
nothing except that save file and its `.bak` backup.

The only build-time network access is `tools/build_data.py`, which refreshes the
bundled catalog from paldb.cc. It is not part of the shipped program.

## Requirements

- Windows
- Python 3.10 or newer
- `oo2core_9_win64.dll` from your own Palworld install
  (`Steam\steamapps\common\Palworld\Pal\Binaries\Win64\`).
  Palworld 1.0 saves are Oodle-compressed and need the game's own runtime to
  unpack. It is Pocketpair's file, so it is **not** included in this repository
  or in any release.

## Run from source (no executable involved)

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy "<Palworld>\Pal\Binaries\Win64\oo2core_9_win64.dll" .
.venv\Scripts\python.exe main.py
```

`Run PalSchematics.bat` does exactly this and is the recommended route for
anyone who would rather not run a packed executable.

Runtime dependency, in full: `palworld_save_tools==0.24.0` (MIT). Nothing else —
the GUI is stock `tkinter`, and icons are pre-converted to PNG at build time so
no image library is needed at runtime.

## Build the executable

```
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\pyinstaller.exe PalSchematics.spec
```

Output: `dist\PalSchematics.exe`.

If a scanner objects to the single-file build (PyInstaller's onefile bootloader
unpacks to a temp directory at startup, which some heuristics dislike), build a
one-directory version instead — same program, no self-extraction:

```
.venv\Scripts\pyinstaller.exe --noconfirm --windowed --name PalSchematics ^
    --icon palschematics/data/app.ico ^
    --add-data "palschematics/data;palschematics/data" ^
    main.py
```

Output: `dist\PalSchematics\PalSchematics.exe` plus its support files.

## Verifying it

```
.venv\Scripts\python.exe tools\gui_smoke.py
.venv\Scripts\python.exe tools\selftest.py "path\to\a COPY of Level.sav"
```

`gui_smoke.py` builds the entire UI and drives it without opening a window.
`selftest.py` runs the catalog, save round-trip, safety-policy and write paths
end to end, finishing with a proof that removing the added items reproduces the
original save byte for byte. **It writes to the file you give it — use a copy.**

## Regenerating the catalog

```
.venv\Scripts\python.exe -m pip install pillow
.venv\Scripts\python.exe tools\build_data.py
```

Rescrapes <https://paldb.cc/en/Schematic>, rewrites
`palschematics/data/schematics.json`, and downloads any icons not already
present. Safe to re-run; it keeps what it has.
