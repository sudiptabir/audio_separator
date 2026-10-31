# Audio Stem Separator

A desktop app that splits a song into separate instrument tracks (stems) and lets
you audition each one inside the app — no external audio player needed.

Powered by [Demucs](https://github.com/facebookresearch/demucs) (`htdemucs_6s`),
which separates audio into **6 stems**:

- Vocals
- Drums
- Bass
- Guitar
- Piano
- Other (synths, strings, FX, and everything else)

> **Note on synths / FX:** No open model isolates synths or sound effects as their
> own labeled stem. Those sounds land in the **Other** stem. Vocals, drums, bass,
> and guitar come out as clean dedicated tracks.

## Features

- Drag-and-drop or browse to load `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`
- One-click separation (runs in the background, UI stays responsive)
- Built-in mixer:
  - Synchronized master transport (play all stems together)
  - Per-stem play, volume, mute, and solo
  - Seek bar with time display
- Stems exported as `.wav` into an output folder you can open with one click

## Requirements

- Python 3.9–3.12
- ~2 GB free disk (PyTorch + model download on first run)
- No GPU required (runs on CPU). A GPU speeds things up a lot if present.

## Setup

```powershell
# From the project folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install PyTorch (CPU build) first, then the rest
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.main
```

On the first separation, Demucs downloads the `htdemucs_6s` model
(~300 MB). This happens once.

## How it works

1. `app/separator.py` wraps Demucs and runs it in a worker thread.
2. `app/player.py` manages synchronized playback of the stems using Qt's
   `QMediaPlayer` / `QAudioOutput`.
3. `app/main.py` wires up the GUI (load file -> separate -> mix/play -> export).

## Building a Windows installer

The app can be packaged into a standalone installer (`AudioStemSeparator-Setup.exe`)
that end users can run without installing Python.

### Prerequisites

1. All app dependencies installed in your active Python (see Setup above).
2. PyInstaller:

   ```powershell
   python -m pip install -r requirements-build.txt
   ```

3. [Inno Setup 6](https://jrsoftware.org/isdl.php) (for the final installer step).

### Build

```powershell
.\build_installer.ps1
```

This runs two stages:

1. **PyInstaller** bundles the app into `dist\AudioStemSeparator\` as a standalone
   folder containing `AudioStemSeparator.exe` and all dependencies.
2. **Inno Setup** wraps that folder into `Output\AudioStemSeparator-Setup.exe` with
   Start Menu and optional desktop shortcuts plus an uninstaller.

If Inno Setup isn't found, the script still produces the standalone app at
`dist\AudioStemSeparator\AudioStemSeparator.exe` and tells you how to finish the
installer step.

### Notes

- The bundle is large (torch + PySide6 are ~1.5-2 GB unpacked). The installer
  itself is typically several hundred MB.
- The `htdemucs_6s` model is **not** bundled; it downloads once on the first
  separation and is cached in the user's profile.
- The install is per-user by default (no admin needed). Edit `installer.iss`
  (`PrivilegesRequired=admin`) for a machine-wide install.
