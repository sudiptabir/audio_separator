"""Synchronized multi-stem playback using Qt's built-in media backend.

Each stem gets its own QMediaPlayer + QAudioOutput so volume, mute, and solo can
be controlled independently. A single "master" transport drives play/pause/seek
and keeps every stem aligned, so no external audio player is needed.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class StemChannel(QObject):
    """A single playable stem: one media player + audio output."""

    def __init__(self, name: str, file_path: str, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name
        self.file_path = file_path

        self._audio = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setSource(QUrl.fromLocalFile(file_path))

        self._volume = 1.0       # 0.0 - 1.0 user-set level
        self._muted = False
        self._soloed = False
        self._audio.setVolume(self._volume)

    # --- transport (driven by the MixerPlayer master) ---
    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def set_position(self, ms: int) -> None:
        self._player.setPosition(ms)

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    def media_player(self) -> QMediaPlayer:
        return self._player

    # --- mixer controls ---
    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._apply_effective_volume()

    def volume(self) -> float:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_effective_volume()

    def is_muted(self) -> bool:
        return self._muted

    def set_soloed(self, soloed: bool) -> None:
        self._soloed = soloed

    def is_soloed(self) -> bool:
        return self._soloed

    def apply_solo_state(self, any_soloed: bool) -> None:
        """Recompute audibility given whether *any* channel is soloed."""
        self._any_soloed = any_soloed
        self._apply_effective_volume()

    def _apply_effective_volume(self) -> None:
        any_soloed = getattr(self, "_any_soloed", False)
        audible = not self._muted
        if any_soloed and not self._soloed:
            audible = False
        self._audio.setVolume(self._volume if audible else 0.0)


class MixerPlayer(QObject):
    """Master transport that keeps all stem channels in sync."""

    positionChanged = Signal("qlonglong")   # ms
    durationChanged = Signal("qlonglong")   # ms
    stateChanged = Signal(bool)             # True = playing

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._channels: list[StemChannel] = []
        self._master: QMediaPlayer | None = None
        self._is_playing = False

    def load(self, stems: dict[str, str]) -> None:
        """Load a mapping of {stem_name: wav_path} into the mixer."""
        self.clear()
        for name, path in stems.items():
            channel = StemChannel(name, path, self)
            self._channels.append(channel)

        if self._channels:
            # Use the first channel as the clock source for position/duration.
            self._master = self._channels[0].media_player()
            # Route through slots: QMediaPlayer emits qlonglong, and we re-emit
            # as plain ints for the UI.
            self._master.positionChanged.connect(self._on_master_position)
            self._master.durationChanged.connect(self._on_master_duration)
            self._master.playbackStateChanged.connect(self._on_master_state)
            self._master.mediaStatusChanged.connect(self._on_media_status)

    def clear(self) -> None:
        self.stop()
        for channel in self._channels:
            channel.media_player().setSource(QUrl())
        self._channels.clear()
        self._master = None

    def channels(self) -> list[StemChannel]:
        return list(self._channels)

    def channel(self, name: str) -> StemChannel | None:
        for channel in self._channels:
            if channel.name == name:
                return channel
        return None

    # --- transport ---
    def play(self) -> None:
        if not self._channels:
            return
        # Nudge all channels to the master's position before playing, so they
        # start aligned even if one drifted.
        target = self._master.position() if self._master else 0
        for channel in self._channels:
            channel.set_position(target)
            channel.play()
        self._is_playing = True
        self.stateChanged.emit(True)

    def pause(self) -> None:
        for channel in self._channels:
            channel.pause()
        self._is_playing = False
        self.stateChanged.emit(False)

    def toggle(self) -> None:
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        for channel in self._channels:
            channel.stop()
        self._is_playing = False
        self.stateChanged.emit(False)

    def seek(self, ms: int) -> None:
        for channel in self._channels:
            channel.set_position(ms)

    def is_playing(self) -> bool:
        return self._is_playing

    def duration(self) -> int:
        return self._master.duration() if self._master else 0

    def position(self) -> int:
        return self._master.position() if self._master else 0

    # --- solo/mute coordination ---
    def refresh_solo_state(self) -> None:
        any_soloed = any(c.is_soloed() for c in self._channels)
        for channel in self._channels:
            channel.apply_solo_state(any_soloed)

    # --- internal ---
    def _on_master_position(self, ms) -> None:
        self.positionChanged.emit(int(ms))

    def _on_master_duration(self, ms) -> None:
        self.durationChanged.emit(int(ms))

    def _on_master_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        if playing != self._is_playing:
            self._is_playing = playing
            self.stateChanged.emit(playing)

    def _on_media_status(self, status) -> None:
        # When the track reaches the end, reset to the start for easy replay.
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()
            self.seek(0)
            self.positionChanged.emit(0)
