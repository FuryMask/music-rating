"""Theme-colored waves driven by the selected player's process tree."""

import logging
import sys
from math import ceil
from threading import Event, Thread
from time import monotonic

from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import QWidget

from app.theme import ACCENT, themed_color
from app.ui.widgets.motion import reduced_motion

BLOCK_SIZE = 2048
BANDS = 28
SILENCE = (0.0,) * BANDS
FEATHER_LAYERS = 16
PCM_NOISE_FLOOR = 2  # WASAPI's PCM conversion can dither silence by one count.


class _PlayerLevels:
    def __init__(self, name, executables, package_family, package_executable) -> None:
        self._name = name
        self._executables = executables
        self._package_family = package_family
        self._package_executable = package_executable
        self.frame = (0.0, SILENCE)
        self.error = ""
        self._stop = Event()
        self._thread = Thread(target=self._read, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def _read(self) -> None:
        try:
            if sys.getwindowsversion().build < 20348:
                self.error = "Для волны нужна Windows со сборкой 20348 или новее."
                return
            import numpy as np
            from app.services import process_loopback

            self._capture(np, process_loopback)
        except ImportError as error:
            self.error = "Для волны обновите зависимости приложения из requirements.txt."
            logging.getLogger(__name__).warning("Process loopback dependency: %s", error)
        except (OSError, RuntimeError, ValueError, AttributeError) as error:
            self.error = f"Не удалось получить звук от плеера {self._name}."
            logging.getLogger(__name__).warning("Player loopback unavailable: %s", error)
        finally:
            self.frame = (0.0, SILENCE)

    def _capture(self, np, loopback) -> None:
        window = (np.hanning(BLOCK_SIZE) / 32768).astype(np.float32)[:, None]
        centers = np.geomspace(60, 9500, BANDS) * BLOCK_SIZE / loopback.SAMPLE_RATE
        bins = np.arange(BLOCK_SIZE // 2 + 1)
        block_bytes = BLOCK_SIZE * loopback.FRAME_BYTES
        deadline = monotonic() + 2
        while not self._stop.is_set():
            with loopback.find_process_tree(
                self._executables, package_family=self._package_family,
                package_executable=self._package_executable,
            ) as target:
                if target is not None:
                    pending = bytearray()
                    with loopback.capture_process_tree(*target, self._stop) as packets:
                        for packet in packets:
                            pending.extend(packet)
                            while len(pending) >= block_bytes:
                                frames = np.frombuffer(pending[:block_bytes], dtype="<i2").reshape(BLOCK_SIZE, -1)
                                del pending[:block_bytes]
                                levels = SILENCE
                                if frames.min() < -PCM_NOISE_FLOOR or frames.max() > PCM_NOISE_FLOOR:
                                    power = np.abs(np.fft.rfft(frames * window, axis=0)).max(axis=1)
                                    spectrum = np.interp(centers, bins, power)
                                    levels = tuple(np.clip((spectrum / 96) ** 0.60, 0, 1))
                                self.frame = monotonic(), levels
                    self.frame = (0.0, SILENCE)
                    deadline = monotonic() + 2
            if monotonic() >= deadline:
                raise RuntimeError(f"{self._name} process was not found")
            self._stop.wait(0.15)


class AudioWaves(QWidget):
    capture_error = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._playing = False
        self._capture = None
        self._levels = SILENCE
        self._source = None
        self._wave_image = QImage()
        self._image_key = None
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._update_frame)

    def set_source(self, name, executables, *, package_family="", package_executable="") -> None:
        self._source = (name, executables, package_family, package_executable)

    def set_playing(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        self._sync_capture()

    def _sync_capture(self) -> None:
        if self._should_capture():
            if self._capture is None:
                self.capture_error.emit("")
                self._capture = _PlayerLevels(*self._source)
            if not self._timer.isActive():
                self._timer.start()
        else:
            if self._capture is not None:
                self._capture.stop()
            if not self.isVisible():
                self._timer.stop()
                self._levels = SILENCE

    def _should_capture(self) -> bool:
        return (self._source is not None and self._playing and self.isVisible()
                and not reduced_motion() and sys.platform == "win32")

    def _update_frame(self) -> None:
        capture = self._capture
        if capture is not None and not capture.is_alive():
            self._capture = None
            if self._should_capture():
                if capture.stopping:
                    self._sync_capture()
                elif capture.error:
                    self.capture_error.emit(capture.error)
            capture = self._capture
        updated, levels = capture.frame if capture and not capture.stopping else (0.0, SILENCE)
        targets = levels if monotonic() - updated < 0.25 else SILENCE
        previous = self._levels
        self._levels = tuple(
            current + (target - current) * (0.56 if target > current else 0.22)
            for current, target in zip(self._levels, targets)
        )
        if max(self._levels) < 0.008 and capture is None:
            self._timer.stop()
            self._levels = SILENCE
        if self._levels != previous:
            self.update(self._wave_rect())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_capture()

    def hideEvent(self, event) -> None:
        self._sync_capture()
        super().hideEvent(event)

    def _wave_rect(self) -> QRect:
        height = ceil(self.height() * 0.42)
        return QRect(0, self.height() - height, self.width(), height)

    def _rasterize(self, rect: QRect, color: QColor) -> QImage:
        max_height = self.height() * 0.42
        step = self.width() / (BANDS - 1)
        levels = (self._levels[0], *self._levels, self._levels[-1])
        points = [
            QPointF(i * step, -max_height * (0.2 * left + 0.6 * center + 0.2 * right))
            for i, (left, center, right) in enumerate(zip(levels, levels[1:], levels[2:]))
        ]
        contour = QPainterPath(points[0])
        for point, following in zip(points[1:-1], points[2:]):
            contour.quadTo(point, (point + following) / 2)
        contour.lineTo(points[-1])
        reverse = contour.toReversed()
        image = QImage(rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        # Stacked translucent fills follow the actual contour, including low crests.
        color.setAlphaF(1 - 0.5 ** (1 / FEATHER_LAYERS))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.save()
        painter.translate(0, rect.height())
        for layer in range(FEATHER_LAYERS):
            inset = 0.16 * (layer + 0.5) / FEATHER_LAYERS
            band = QTransform.fromScale(1, 1 - inset).map(contour)
            band.connectPath(QTransform.fromScale(1, inset).map(reverse))
            band.closeSubpath()
            painter.fillPath(band, color)
        painter.restore()
        sides = QLinearGradient(0, 0, self.width(), 0)
        for at, alpha in ((0.0, 0), (0.06, 255), (0.94, 255), (1.0, 0)):
            sides.setColorAt(at, QColor(0, 0, 0, alpha))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(image.rect(), sides)
        painter.end()
        return image

    def paintEvent(self, event) -> None:
        if max(self._levels) < 0.008:
            return
        rect = self._wave_rect()
        if not event.rect().intersects(rect):
            return
        color = themed_color(ACCENT)
        key = (self.width(), self.height(), self._levels, color.rgb())
        if key != self._image_key:
            self._wave_image = self._rasterize(rect, color)
            self._image_key = key
        painter = QPainter(self)
        painter.drawImage(rect.topLeft(), self._wave_image)
