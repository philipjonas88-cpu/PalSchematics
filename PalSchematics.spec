# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build.

    .venv\\Scripts\\pyinstaller.exe PalSchematics.spec

Produces dist/PalSchematics.exe -- one file, no Python needed.

oo2core_9_win64.dll is intentionally NOT bundled: it is Palworld's own
redistributable and belongs to the game, not to this project. The app looks for
it next to the .exe and explains where to find it if it is missing.
"""

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("palschematics/data", "palschematics/data")],
    hiddenimports=["palworld_save_tools"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PIL", "numpy", "pytest"],  # build-time only, keeps the exe small
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PalSchematics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="palschematics/data/app.ico",
)
