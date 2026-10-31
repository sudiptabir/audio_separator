# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Audio Stem Separator.

torch, torchaudio, and demucs load many modules and data files dynamically, so
we explicitly collect them. Build with:

    pyinstaller AudioStemSeparator.spec --noconfirm
"""

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
)

datas = []
binaries = []
hiddenimports = []


def _add_all(pkg):
    """Collect a package's data, binaries, and submodules."""
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Packages that ship data files / C extensions / dynamically imported modules.
for pkg in (
    "demucs",
    "torchaudio",
    "julius",
    "openunmix",
    "soundfile",
    "imageio_ffmpeg",
):
    try:
        _add_all(pkg)
    except Exception as exc:  # noqa: BLE001 - keep building even if one is absent
        print(f"[spec] skipping {pkg}: {exc}")

# torch is huge; collect_all can choke. Pull data + submodules more selectively.
try:
    datas += collect_data_files("torch")
    hiddenimports += collect_submodules("torch")
except Exception as exc:  # noqa: BLE001
    print(f"[spec] torch collect warning: {exc}")

# Explicit extras that hooks sometimes miss.
hiddenimports += [
    "app",
    "app.main",
    "app.player",
    "app.separator",
    "app.ffmpeg_setup",
    "numpy",
    "soundfile",
    "sphn",
    "lameenc",
    "einops",
    "huggingface_hub",
    "PySide6.QtMultimedia",
]

block_cipher = None

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim some weight: we don't use these.
        "tkinter",
        "matplotlib",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AudioStemSeparator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AudioStemSeparator",
)
