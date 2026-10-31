"""Top-level entry point for the packaged app.

PyInstaller bundles from a script like this rather than `python -m app.main`.
Keeping it tiny: it just delegates to the real main().
"""

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
