"""Demucs-backed source separation, wrapped in a Qt worker thread.

The separation runs in a background QThread so the GUI stays responsive. Progress
is reported back through Qt signals.
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

# The 6-stem model. Stems it produces, in a sensible display order.
MODEL_NAME = "htdemucs_6s"
STEMS = ["vocals", "drums", "bass", "guitar", "piano", "other"]

# Friendly labels for the UI.
STEM_LABELS = {
    "vocals": "Vocals",
    "drums": "Drums",
    "bass": "Bass",
    "guitar": "Guitar",
    "piano": "Piano",
    "other": "Other (synths / FX)",
}

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}


class SeparationWorker(QObject):
    """Runs Demucs separation off the UI thread."""

    progress = Signal(int, str)        # percent (0-100, or -1 for indeterminate), message
    finished = Signal(dict)            # {stem_name: output_wav_path}
    error = Signal(str)                # error message

    def __init__(self, input_path: str, output_root: str):
        super().__init__()
        self._input_path = input_path
        self._output_root = output_root
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self._run_impl()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")

    def _run_impl(self) -> None:
        self.progress.emit(-1, "Loading model and audio...")

        import torch
        from demucs.apply import apply_model
        from demucs.audio import save_audio
        from demucs.pretrained import get_model

        input_path = Path(self._input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        self.progress.emit(-1, "Loading model (first run downloads it, ~1-2 min)...")
        model = get_model(MODEL_NAME)
        model.eval()

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)

        if self._cancelled:
            return

        self.progress.emit(-1, "Reading audio file...")

        # Load audio WITHOUT relying on a system ffmpeg/ffprobe install.
        # Demucs's own AudioFile shells out to ffmpeg, which may not be present.
        wav = _load_audio(
            str(input_path),
            target_sr=model.samplerate,
            target_channels=model.audio_channels,
        )
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)

        if self._cancelled:
            return

        self.progress.emit(
            0, f"Separating on {device.upper()} (CPU can take several minutes)..."
        )

        # Process the track in time segments so we can report real progress and
        # honor cancellation. Each segment is separated independently; Demucs
        # handles internal overlap within a segment.
        sample_rate = model.samplerate
        total_samples = wav.shape[-1]
        segment_seconds = 30
        segment_len = segment_seconds * sample_rate
        num_segments = max(1, (total_samples + segment_len - 1) // segment_len)

        segment_outputs = []
        with torch.no_grad():
            for seg_idx in range(num_segments):
                if self._cancelled:
                    return
                start = seg_idx * segment_len
                end = min(start + segment_len, total_samples)
                chunk = wav[:, start:end]

                out = apply_model(
                    model,
                    chunk[None],
                    device=device,
                    split=True,
                    overlap=0.25,
                    progress=False,
                )[0]
                segment_outputs.append(out)

                done = seg_idx + 1
                pct = int(done / num_segments * 100)
                self.progress.emit(
                    pct,
                    f"Separating... segment {done}/{num_segments}",
                )

        sources = torch.cat(segment_outputs, dim=-1)
        sources = sources * ref.std() + ref.mean()

        if self._cancelled:
            return

        # Build output folder: <output_root>/<input_stem>/
        out_dir = Path(self._output_root) / input_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        results: dict[str, str] = {}
        model_sources = list(model.sources)  # order of stems in the tensor

        total = len(model_sources)
        for idx, name in enumerate(model_sources):
            if self._cancelled:
                return
            pct = int((idx / max(total, 1)) * 100)
            self.progress.emit(pct, f"Saving {STEM_LABELS.get(name, name)}...")

            stem_tensor = sources[idx]
            out_path = out_dir / f"{name}.wav"
            save_audio(
                stem_tensor,
                str(out_path),
                samplerate=model.samplerate,
            )
            results[name] = str(out_path)

        self.progress.emit(100, "Done.")
        self.finished.emit(results)


class SeparationController(QObject):
    """Owns the worker thread lifecycle and re-emits its signals."""

    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: SeparationWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, input_path: str, output_root: str) -> None:
        if self.is_running:
            return

        self._thread = QThread()
        self._worker = SeparationWorker(input_path, output_root)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, results: dict) -> None:
        self.finished.emit(results)
        self._teardown()

    def _on_error(self, message: str) -> None:
        self.error.emit(message)
        self._teardown()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._worker = None


def _load_audio(path: str, target_sr: int, target_channels: int):
    """Load an audio file to a float32 tensor shaped (channels, samples).

    Tries backends in order of reliability on a machine with no system ffmpeg:
      1. torchaudio (uses soundfile / libsndfile for wav/flac/ogg, and ffmpeg
         only if its ffmpeg backend is available)
      2. soundfile directly
      3. Demucs's AudioFile (ffmpeg) as a last resort

    Resamples to target_sr and conforms to target_channels (mono->stereo by
    duplication, multi->target by averaging/truncation).
    """
    import torch

    wav, sr = _read_with_backends(path)

    # Conform channel count.
    wav = _conform_channels(wav, target_channels)

    # Resample if needed.
    if sr != target_sr:
        import torchaudio

        wav = torchaudio.functional.resample(wav, sr, target_sr)

    return wav.to(torch.float32)


# Formats libsndfile (soundfile) / torchaudio cannot reliably open without a
# system ffmpeg. For these we transcode to a temp wav using the bundled
# imageio-ffmpeg binary first.
_FFMPEG_REQUIRED_EXTS = {".mp3", ".m4a", ".aac", ".wma"}


def _read_with_backends(path: str):
    """Return (tensor[channels, samples], sample_rate) using the first backend
    that succeeds."""
    import torch

    ext = Path(path).suffix.lower()

    # Compressed formats: transcode to temp wav with bundled ffmpeg, then read.
    if ext in _FFMPEG_REQUIRED_EXTS:
        wav_path = _transcode_to_wav(path)
        if wav_path is not None:
            try:
                return _read_pcm_wav(wav_path)
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

    # 1) soundfile (native for wav/flac/ogg)
    try:
        return _read_pcm_wav(path)
    except Exception:  # noqa: BLE001 - fall through
        pass

    # 2) torchaudio
    try:
        import torchaudio

        wav, sr = torchaudio.load(path)  # shape: (channels, samples)
        return wav, sr
    except Exception:  # noqa: BLE001 - fall through to last resort
        pass

    # 3) Demucs AudioFile (needs system ffmpeg; last resort)
    from demucs.audio import AudioFile

    af = AudioFile(path)
    sr = int(af.samplerate())
    wav = af.read(streams=0, samplerate=sr)
    return wav, sr


def _read_pcm_wav(path: str):
    """Read a PCM audio file via soundfile -> (tensor[channels, samples], sr)."""
    import numpy as np
    import soundfile as sf
    import torch

    data, sr = sf.read(path, dtype="float32", always_2d=True)  # (samples, ch)
    tensor = torch.from_numpy(np.ascontiguousarray(data.T))  # (ch, samples)
    return tensor, sr


def _transcode_to_wav(path: str) -> str | None:
    """Transcode a compressed audio file to a temp 16-bit PCM wav using the
    bundled imageio-ffmpeg binary. Returns the temp wav path, or None on failure.
    """
    import subprocess
    import tempfile

    try:
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - ffmpeg not available
        return None

    fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="audioseparator_")
    os.close(fd)

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", path,
        "-acodec", "pcm_s16le",
        out_path,
    ]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        try:
            os.remove(out_path)
        except OSError:
            pass
        return None

    return out_path


def _conform_channels(wav, target_channels: int):
    """Make `wav` (channels, samples) have exactly target_channels."""
    channels = wav.shape[0]
    if channels == target_channels:
        return wav
    if channels == 1 and target_channels == 2:
        return wav.repeat(2, 1)
    if channels > target_channels:
        if target_channels == 1:
            return wav.mean(dim=0, keepdim=True)
        return wav[:target_channels]
    # Fewer channels than needed (and not the mono->stereo case): pad by repeat.
    reps = (target_channels + channels - 1) // channels
    return wav.repeat(reps, 1)[:target_channels]


def default_output_root() -> str:
    """Where separated stems are written by default."""
    root = Path.home() / "AudioSeparator" / "output"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)
