"""Audio Stem Separator - desktop GUI entry point."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Make bundled ffmpeg available before anything else imports audio libs.
from app.ffmpeg_setup import ensure_ffmpeg_on_path

ensure_ffmpeg_on_path()

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.player import MixerPlayer, StemChannel
from app.separator import (
    STEM_LABELS,
    SUPPORTED_EXTENSIONS,
    SeparationController,
    default_output_root,
)


def format_time(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class StemRow(QFrame):
    """A mixer row for a single stem: label, play state, volume, mute, solo."""

    def __init__(self, channel: StemChannel, on_solo_changed, parent=None):
        super().__init__(parent)
        self._channel = channel
        self._on_solo_changed = on_solo_changed

        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)

        label = QLabel(STEM_LABELS.get(channel.name, channel.name.title()))
        label.setMinimumWidth(150)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)

        self.mute_btn = QPushButton("Mute")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedWidth(70)
        self.mute_btn.toggled.connect(self._on_mute)
        layout.addWidget(self.mute_btn)

        self.solo_btn = QPushButton("Solo")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedWidth(70)
        self.solo_btn.toggled.connect(self._on_solo)
        layout.addWidget(self.solo_btn)

        layout.addWidget(QLabel("Vol"))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(160)
        self.vol.valueChanged.connect(self._on_volume)
        layout.addWidget(self.vol)

        layout.addStretch(1)

    def _on_mute(self, checked: bool) -> None:
        self._channel.set_muted(checked)

    def _on_solo(self, checked: bool) -> None:
        self._channel.set_soloed(checked)
        self._on_solo_changed()

    def _on_volume(self, value: int) -> None:
        self._channel.set_volume(value / 100.0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Stem Separator")
        self.resize(720, 560)
        self.setAcceptDrops(True)

        self._input_path: str | None = None
        self._output_root = default_output_root()
        self._stem_paths: dict[str, str] = {}
        self._seeking = False

        self.mixer = MixerPlayer(self)
        self.mixer.positionChanged.connect(self._on_position)
        self.mixer.durationChanged.connect(self._on_duration)
        self.mixer.stateChanged.connect(self._on_play_state)

        self.separator = SeparationController(self)
        self.separator.progress.connect(self._on_progress)
        self.separator.finished.connect(self._on_separation_done)
        self.separator.error.connect(self._on_separation_error)

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Audio Stem Separator")
        tf = QFont()
        tf.setPointSize(16)
        tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        # --- file selection row ---
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file loaded. Drop an audio file here or browse.")
        self.file_label.setWordWrap(True)
        file_row.addWidget(self.file_label, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self.browse_btn)
        root.addLayout(file_row)

        # --- separate controls ---
        action_row = QHBoxLayout()
        self.separate_btn = QPushButton("Separate")
        self.separate_btn.setEnabled(False)
        self.separate_btn.clicked.connect(self._start_separation)
        action_row.addWidget(self.separate_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.separator.cancel)
        action_row.addWidget(self.cancel_btn)

        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        action_row.addWidget(self.open_folder_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Idle")
        root.addWidget(self.progress)

        # --- master transport ---
        transport = QHBoxLayout()
        self.play_btn = QPushButton("Play all")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.mixer.toggle)
        transport.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.mixer.stop)
        transport.addWidget(self.stop_btn)

        self.time_label = QLabel("00:00 / 00:00")
        transport.addWidget(self.time_label)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.sliderPressed.connect(self._seek_start)
        self.seek.sliderReleased.connect(self._seek_end)
        transport.addWidget(self.seek, 1)
        root.addLayout(transport)

        # --- stem rows container ---
        self.stems_container = QVBoxLayout()
        self.stems_container.setSpacing(6)
        stems_wrapper = QWidget()
        stems_wrapper.setLayout(self.stems_container)
        root.addWidget(stems_wrapper, 1)

        hint = QLabel(
            "Tip: synths, strings, and sound effects are grouped into the "
            "\"Other\" stem — no model isolates them separately."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        root.addWidget(hint)

    # ------------------------------------------------------------- file load
    def dragEnterEvent(self, event):  # noqa: N802 (Qt signature)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802 (Qt signature)
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        self._load_file(path)

    def _browse(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an audio file", "", f"Audio files ({exts})"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            QMessageBox.warning(
                self,
                "Unsupported file",
                f"'{ext}' is not a supported audio format.\n"
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )
            return
        self._input_path = path
        self.file_label.setText(f"Loaded: {path}")
        self.separate_btn.setEnabled(True)

    # ----------------------------------------------------------- separation
    def _start_separation(self) -> None:
        if not self._input_path or self.separator.is_running:
            return
        self.mixer.clear()
        self._clear_stem_rows()
        self.separate_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.seek.setEnabled(False)
        self.progress.setValue(0)
        self.separator.start(self._input_path, self._output_root)

    def _on_progress(self, pct: int, message: str) -> None:
        if pct < 0:
            self.progress.setRange(0, 0)  # indeterminate / busy
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
        self.progress.setFormat(message)

    def _on_separation_done(self, stems: dict) -> None:
        self._stem_paths = stems
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Separation complete.")
        self._restore_controls_after_run()
        self.open_folder_btn.setEnabled(True)

        # Load into the mixer and build rows in the canonical stem order.
        ordered = {
            name: stems[name] for name in STEM_LABELS if name in stems
        }
        for name in stems:  # include any unexpected extras at the end
            ordered.setdefault(name, stems[name])

        self.mixer.load(ordered)
        for channel in self.mixer.channels():
            row = StemRow(channel, self._refresh_solo, self)
            self.stems_container.addWidget(row)
        self.mixer.refresh_solo_state()

        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.seek.setEnabled(True)

    def _on_separation_error(self, message: str) -> None:
        self._restore_controls_after_run()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Error")
        QMessageBox.critical(self, "Separation failed", message)

    def _restore_controls_after_run(self) -> None:
        self.separate_btn.setEnabled(self._input_path is not None)
        self.browse_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    # -------------------------------------------------------------- playback
    def _refresh_solo(self) -> None:
        self.mixer.refresh_solo_state()

    def _on_position(self, ms: int) -> None:
        if not self._seeking:
            self.seek.setValue(ms)
        self.time_label.setText(
            f"{format_time(ms)} / {format_time(self.mixer.duration())}"
        )

    def _on_duration(self, ms: int) -> None:
        self.seek.setRange(0, ms)
        self.time_label.setText(
            f"{format_time(self.mixer.position())} / {format_time(ms)}"
        )

    def _on_play_state(self, playing: bool) -> None:
        self.play_btn.setText("Pause" if playing else "Play all")

    def _seek_start(self) -> None:
        self._seeking = True

    def _seek_end(self) -> None:
        self._seeking = False
        self.mixer.seek(self.seek.value())

    # ---------------------------------------------------------------- misc
    def _clear_stem_rows(self) -> None:
        while self.stems_container.count():
            item = self.stems_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_output_folder(self) -> None:
        if not self._stem_paths:
            folder = self._output_root
        else:
            folder = str(Path(next(iter(self._stem_paths.values()))).parent)
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except OSError as exc:
            QMessageBox.warning(self, "Could not open folder", str(exc))

    def closeEvent(self, event):  # noqa: N802 (Qt signature)
        self.mixer.clear()
        if self.separator.is_running:
            self.separator.cancel()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Audio Stem Separator")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
