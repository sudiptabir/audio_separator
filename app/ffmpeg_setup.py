"""Make a bundled ffmpeg binary available on PATH.

Demucs (via torchaudio / audio decoding) and some format reads need ffmpeg.
Instead of asking the user to install it system-wide, we reuse the binary that
ships with the `imageio-ffmpeg` pip package and expose it on PATH for this
process (and any child processes we spawn).
"""

from __future__ import annotations

import os
from pathlib import Path


def ensure_ffmpeg_on_path() -> str | None:
    """Add the bundled ffmpeg to PATH for this process.

    Returns the directory containing ffmpeg if successful, otherwise None.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    exe_path = Path(exe)
    if not exe_path.exists():
        return None

    ffmpeg_dir = str(exe_path.parent)

    # imageio-ffmpeg names its binary something like `ffmpeg-win64-v4.x.exe`.
    # Many tools call plain `ffmpeg`, so provide a predictable copy named
    # `ffmpeg.exe` in a cache dir and put that on PATH.
    normalized_dir = _ensure_normalized_name(exe_path)
    search_dir = normalized_dir or ffmpeg_dir

    current_path = os.environ.get("PATH", "")
    if search_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = search_dir + os.pathsep + current_path

    # Also point tools that read this env var directly at the binary.
    os.environ.setdefault("FFMPEG_BINARY", exe)

    return search_dir


def _ensure_normalized_name(exe_path: Path) -> str | None:
    """Create a copy/symlink named `ffmpeg.exe` so plain `ffmpeg` resolves."""
    import shutil

    target_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if exe_path.name == target_name:
        return str(exe_path.parent)

    cache_dir = Path.home() / ".audioseparator" / "bin"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / target_name

    try:
        if not target.exists():
            shutil.copy2(exe_path, target)
        return str(cache_dir)
    except OSError:
        # Fall back to the original directory; PATH entry still helps some tools.
        return str(exe_path.parent)
