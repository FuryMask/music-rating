"""Fullscreen listening view for the local rating wizard."""

from threading import Event
from time import monotonic

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QRunnable, QSignalBlocker, QSize, Qt, QThreadPool,
    QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QGraphicsEffect, QHBoxLayout, QLabel, QLineEdit, QSlider, QVBoxLayout, QWidget,
)

from app.services.desktop_autoplay import try_start_desktop_track
from app.services.desktop_launch import (
    keep_launch_in_background, last_input_tick, lock_foreground_for_launch, unlock_foreground_after_launch,
)
from app.services.desktop_playback import DesktopPlaybackError
from app.services.spotify import SpotifyError, resolve_album_id as resolve_spotify_album_id
from app.services.spotify_playback import (
    SPOTIFY_PACKAGE, SpotifyDesktopSession, launch_spotify_desktop,
    spotify_executable_paths, spotify_playback_tracks,
)
from app.services.yandex_music import (
    YandexMusicError, read_playback_album, request_playback_album, resolve_album_id,
)
from app.services.yandex_playback import (
    YandexDesktopSession, launch_yandex_desktop, match_album_tracks, yandex_executable_paths,
)
from app.store import STORE
from app.theme import saved_visualizer
from app.ui.widgets.audio_waves import AudioWaves
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import SmoothScrollArea, reduced_motion
from app.ui.widgets.player_status import PlayerStatus

SHOW_RATINGS_MS = 7000
PAUSE_MS = 3000
START_TIMEOUT = 8
AUTOPLAY_GRACE = 0.9
TRACK_CHANGE_GRACE = 0.8
COVER_SIZE = 200
TIMELINE_WIDTH = 320
REVEAL_MS = 550
IDLE_SECONDS = 5
IDLE_FADE_MS = 300
SEEK_TIMEOUT = 2
SEEK_TOLERANCE_MS = 750


def _format_time(milliseconds: int) -> str:
    minutes, seconds = divmod(milliseconds // 1000, 60)
    return f"{minutes}:{seconds:02d}"


class _PlayerReveal(QGraphicsEffect):
    """Animate a widget inside its layout bounds, with an independent idle fade."""

    def __init__(self, parent: QWidget, travel: QPoint = QPoint()) -> None:
        super().__init__(parent)
        self._travel = travel
        self._progress = self._opacity = 1.0

    def set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    def draw(self, painter) -> None:
        opacity = self._progress * self._opacity
        if opacity <= 0.0:
            return
        if opacity >= 1.0:
            self.drawSource(painter)
            return
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates, offset,
                                   QGraphicsEffect.PixmapPadMode.NoPad)
        painter.save()
        painter.setClipRect(self.sourceBoundingRect(), Qt.ClipOperation.IntersectClip)
        painter.setOpacity(painter.opacity() * opacity)
        painter.translate(self._travel * (1 - self._progress))
        painter.drawPixmap(offset, pixmap)
        painter.restore()


class _PlaybackSlider(QSlider):
    def _set_mouse_position(self, event) -> None:
        span = max(1, self.width() - 12)
        fraction = max(0.0, min(1.0, (event.position().x() - 6) / span))
        self.setSliderPosition(round(fraction * self.maximum()))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.setSliderDown(True)
        self._set_mouse_position(event)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self._set_mouse_position(event)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_mouse_position(event)
            self.setSliderDown(False)
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event) -> None:
        event.ignore()


class _MediaCall(QRunnable):
    def __init__(self, backend, track, command, report, *, seek_ms=None):
        super().__init__()
        self.backend, self.track, self.command, self.report = backend, track, command, report
        self.seek_ms = seek_ms

    def run(self) -> None:
        try:
            if self.command == "seek":
                snapshot, accepted = self.backend.read(self.track, self.command, seek_ms=self.seek_ms)
            else:
                snapshot, accepted = self.backend.read(self.track, self.command)
            error_text = ""
        except DesktopPlaybackError as error:
            snapshot, accepted, error_text = None, False, str(error)
        except (OSError, RuntimeError, TypeError, AttributeError):
            snapshot, accepted, error_text = None, False, "Не удалось получить состояние плеера."
        try:
            self.report(snapshot, accepted, error_text)
        except RuntimeError:
            pass


class ListenAndRatePage(QWidget):
    closed = Signal()
    completed = Signal()
    track_changed = Signal(int)
    _media_result = Signal(int, str, object, bool, str)
    _autoplay_result = Signal(int, object, bool)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("listenPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._backend = YandexDesktopSession()
        self._provider = "yandex"
        self._app_name = "Яндекс Музыка"
        self._reply = None
        self._busy = False
        self._pending_action = None
        self._cleanup = None
        self._generation = 0
        self._client_opened = False
        self._next_after = None
        self._autoplay_at = None
        self._autoplay_cancel = None
        self._waiting_to_open = False
        self._queue = []
        self._index = -1
        self._matched = False
        self._phase = "idle"
        self._duration_ms = self._position_ms = 0
        self._can_seek = False
        self._queued_seek = self._seek_target = None
        self._seek_deadline = 0.0
        self._seek_notice_until = 0.0
        self._rating_invalid = False
        self._ratings_requested = False
        self._rating_progress = 0.0
        self._idle = False
        self._idle_opacity = 1.0
        self._cursor = QPoint()
        self._last_activity = 0.0
        self._idle_widgets = []
        self._idle_effects = []
        self._was_maximized = False
        self._foreground_locked = False
        self._foreground_timer = QTimer(self, interval=75)
        self._foreground_timer.timeout.connect(self._check_foreground_guard)
        self._play_icon, self._pause_icon = line_icon("play"), line_icon("pause")
        self._poll = QTimer(self, interval=200)
        self._poll.timeout.connect(self._poll_player)
        self._media_result.connect(self._on_media_result, Qt.ConnectionType.QueuedConnection)
        self._autoplay_result.connect(self._on_autoplay_result, Qt.ConnectionType.QueuedConnection)
        self._waves = AudioWaves(self)
        self._waves.hide()
        self._cursor_timer = QTimer(self, interval=80)
        self._cursor_timer.timeout.connect(self._check_idle)
        self._idle_animation = self._animation(IDLE_FADE_MS, self._apply_idle_opacity)
        self._idle_animation.finished.connect(self._finish_idle_fade)
        self._build()
        self.hide()

    def _animation(self, duration: int, apply) -> QVariantAnimation:
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        animation.valueChanged.connect(apply)
        return animation

    def _add_idle_widget(self, widget: QWidget, *, travel: QPoint = QPoint()) -> _PlayerReveal:
        policy = widget.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        widget.setSizePolicy(policy)
        effect = _PlayerReveal(widget, travel)
        widget.setGraphicsEffect(effect)
        self._idle_effects.append(effect)
        self._idle_widgets.append(widget)
        return effect

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 20, 32, 24)
        root.setSpacing(8)
        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        top = QHBoxLayout()
        exit_button = self._button("close", "Вернуться к таблице оценок")
        exit_button.clicked.connect(self.closed.emit)
        top.addWidget(exit_button)
        top.addStretch()
        self.counter = QLabel(self)
        self.counter.setObjectName("stepHint")
        top.addWidget(self.counter)
        header_layout.addLayout(top)

        self.status = PlayerStatus(header)
        self.status.text_changed.connect(self._record_activity)
        header_layout.addWidget(self.status)
        self.wave_status = QLabel(header)
        self.wave_status.setObjectName("stepHint")
        self.wave_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wave_status.setWordWrap(True)
        self.wave_status.hide()
        self._waves.capture_error.connect(self._set_wave_error)
        header_layout.addWidget(self.wave_status)
        self.album_link = QLineEdit(self)
        self.album_link.setObjectName("listenAlbumLink")
        self.album_link.setPlaceholderText("Ссылка на альбом Яндекс Музыки")
        self.album_link.setAccessibleName("Ссылка на альбом Яндекс Музыки")
        self.album_link.setFixedWidth(350)
        self.album_link.returnPressed.connect(self._load_album)
        header_layout.addWidget(self.album_link, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.load_button = HoverButton("Подключить альбом", self)
        self.load_button.setObjectName("ghostButton")
        self.load_button.clicked.connect(lambda: self._load_album())
        header_layout.addWidget(self.load_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.retry_button = HoverButton("Открыть трек в Яндекс Музыке", self)
        self.retry_button.setObjectName("ghostButton")
        self.retry_button.clicked.connect(self._request_track)
        header_layout.addWidget(self.retry_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._add_idle_widget(header)
        root.addWidget(header)
        root.addStretch()

        metadata = QWidget(self)
        metadata_layout = QVBoxLayout(metadata)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(8)
        self.title_label = QLabel(metadata)
        self.title_label.setObjectName("listenTitle")
        self.artist_label = QLabel(metadata)
        self.artist_label.setObjectName("listenArtist")
        for label in (self.title_label, self.artist_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            metadata_layout.addWidget(label)
        self._text_reveal = _PlayerReveal(metadata, QPoint(0, 20))
        metadata.setGraphicsEffect(self._text_reveal)
        self._text_animation = self._animation(REVEAL_MS, self._text_reveal.set_progress)
        root.addWidget(metadata)

        cover_slot = QWidget(self)
        cover_slot.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.cover = CoverView(cover_slot, radius=20)
        self.cover.setGeometry(0, 0, COVER_SIZE, COVER_SIZE)
        self._cover_fade = _PlayerReveal(self.cover)
        self.cover.setGraphicsEffect(self._cover_fade)
        root.addWidget(cover_slot, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addStretch()

        self._rating_panel = QWidget(cover_slot)
        self._rating_panel.setGeometry(self.cover.geometry())
        panel_layout = QVBoxLayout(self._rating_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)
        panel_layout.addStretch(1)
        self.rating_area = SmoothScrollArea(self._rating_panel)
        self.rating_area.setObjectName("listenRatings")
        self.rating_area.setWidgetResizable(True)
        self.rating_area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self.rating_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rating_holder = QWidget()
        self.rating_layout = QVBoxLayout(self.rating_holder)
        self.rating_layout.setContentsMargins(0, 0, 10, 0)
        self.rating_layout.setSpacing(10)
        self.rating_area.setWidget(self.rating_holder)
        panel_layout.addWidget(self.rating_area)
        self.rating_error = QLabel(self._rating_panel)
        self.rating_error.setObjectName("errorHint")
        self.rating_error.setWordWrap(True)
        self.rating_error.hide()
        panel_layout.addWidget(self.rating_error)
        panel_layout.addStretch(1)
        self._rating_reveal = _PlayerReveal(self._rating_panel, QPoint(0, 20))
        self._rating_panel.setGraphicsEffect(self._rating_reveal)
        self._rating_reveal.set_progress(0.0)
        self._ratings_animation = self._animation(REVEAL_MS, self._apply_rating_progress)
        self._rating_panel.hide()

        root.addWidget(self._make_timeline(), alignment=Qt.AlignmentFlag.AlignHCenter)

        footer = QWidget(self)
        controls = QHBoxLayout(footer)
        controls.setContentsMargins(0, 0, 0, 0)
        self.fullscreen_button = self._button("fullscreen", "Полноэкранный режим")
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        controls.addWidget(self.fullscreen_button)
        controls.addStretch()
        self.pause_button = self._button("pause", "Приостановить или возобновить трек")
        self.pause_button.clicked.connect(self._toggle_play)
        self.next_button = self._button("arrow-right", "Дослушать трек и перейти дальше")
        self.next_button.clicked.connect(self._continue_tail)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.next_button)
        self._add_idle_widget(footer)
        root.addWidget(footer)

    def _make_timeline(self) -> QWidget:
        timeline = QWidget(self)
        timeline.setFixedWidth(TIMELINE_WIDTH)
        layout = QVBoxLayout(timeline)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.progress = _PlaybackSlider(Qt.Orientation.Horizontal, timeline)
        self.progress.setObjectName("listenProgress")
        self.progress.setTracking(False)
        self.progress.setSingleStep(5000)
        self.progress.setPageStep(10_000)
        self.progress.setAccessibleName("Перемотка трека")
        self.progress.sliderMoved.connect(self._preview_seek)
        self.progress.valueChanged.connect(self._request_seek)
        layout.addWidget(self.progress)
        time_labels = QWidget(timeline)
        times = QHBoxLayout(time_labels)
        times.setContentsMargins(0, 0, 0, 0)
        self.elapsed_time = QLabel(time_labels)
        self.total_time = QLabel(time_labels)
        self.elapsed_time.setAccessibleName("Прошло")
        self.total_time.setAccessibleName("Длительность трека")
        for label in (self.elapsed_time, self.total_time):
            label.setObjectName("stepHint")
        times.addWidget(self.elapsed_time)
        times.addStretch()
        times.addWidget(self.total_time)
        self._add_idle_widget(time_labels)
        layout.addWidget(time_labels)
        self._update_timeline(0, 0)
        return timeline

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._idle = False
        self._apply_idle_opacity(1.0)
        self._finish_idle_fade()
        self._sync_fullscreen_button()
        self._cursor = QCursor.pos()
        self._last_activity = monotonic()
        QApplication.instance().installEventFilter(self)
        self._cursor_timer.start()

    def hideEvent(self, event) -> None:
        self._cursor_timer.stop()
        self._idle_animation.stop()
        self.unsetCursor()
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.WindowStateChange and obj is self.window():
            self._sync_fullscreen_button()
        elif (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.KeyPress)
                and isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj))):
            self._record_activity()
        return super().eventFilter(obj, event)

    def _check_idle(self) -> None:
        cursor = QCursor.pos()
        if cursor != self._cursor:
            self._cursor = cursor
            self._record_activity()
        elif not self._idle and monotonic() - self._last_activity >= IDLE_SECONDS:
            self._set_idle(True)

    def _record_activity(self) -> None:
        self._last_activity = monotonic()
        if self._idle:
            self._set_idle(False)

    def _set_idle(self, idle: bool) -> None:
        self._idle = idle
        self._idle_animation.stop()
        target = 0.0 if idle else 1.0
        if not idle:
            self._finish_idle_fade()
        if reduced_motion() or target == self._idle_opacity:
            self._apply_idle_opacity(target)
            self._finish_idle_fade()
            return
        self._idle_animation.setStartValue(self._idle_opacity)
        self._idle_animation.setEndValue(target)
        self._idle_animation.start()

    def _apply_idle_opacity(self, opacity: float) -> None:
        self._idle_opacity = opacity
        for effect in self._idle_effects:
            effect.set_opacity(opacity)
        self._rating_reveal.set_opacity(opacity)
        self._sync_cover()

    def _finish_idle_fade(self) -> None:
        for widget in self._idle_widgets:
            widget.setVisible(not self._idle)
        self._rating_panel.setVisible(not self._idle and self._ratings_requested)
        if self._idle:
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.unsetCursor()

    def _sync_fullscreen_button(self) -> None:
        fullscreen = self.window().isFullScreen()
        self.fullscreen_button.setIcon(line_icon("windowed" if fullscreen else "fullscreen"))
        label = "Выйти из полноэкранного режима" if fullscreen else "Полноэкранный режим"
        self.fullscreen_button.setToolTip(label)
        self.fullscreen_button.setAccessibleName(label)

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            self.restore_windowed()
        else:
            self._was_maximized = window.isMaximized()
            window.setWindowState(window.windowState() | Qt.WindowState.WindowFullScreen)

    def restore_windowed(self) -> None:
        window = self.window()
        if window.isFullScreen():
            state = window.windowState() & ~(Qt.WindowState.WindowFullScreen | Qt.WindowState.WindowMaximized)
            if self._was_maximized:
                state |= Qt.WindowState.WindowMaximized
            window.setWindowState(state)

    def _set_wave_error(self, error: str) -> None:
        self.wave_status.setText(error)
        self.wave_status.setVisible(bool(error))

    def _layout_ratings(self) -> None:
        self.rating_area.setMaximumHeight(self.rating_layout.sizeHint().height())

    def _apply_rating_progress(self, progress: float) -> None:
        self._rating_progress = progress
        self._rating_reveal.set_progress(progress)
        self._sync_cover()

    def _sync_cover(self) -> None:
        opacity = 1 - self._rating_progress * self._idle_opacity
        self._cover_fade.set_opacity(opacity)
        self.cover.setVisible(opacity > 0)

    def _set_ratings_visible(self, visible: bool) -> None:
        if visible == self._ratings_requested:
            return
        self._ratings_requested = visible
        self._ratings_animation.stop()
        if visible:
            self._record_activity()
        self._rating_panel.setVisible(visible)
        if visible:
            self.rating_area.setEnabled(True)
            self._layout_ratings()
        target = float(visible)
        if reduced_motion() or target == self._rating_progress:
            self._apply_rating_progress(target)
            return
        self._ratings_animation.setStartValue(self._rating_progress)
        self._ratings_animation.setEndValue(target)
        self._ratings_animation.start()

    def _update_timeline(self, position: int, duration: int) -> None:
        position = max(0, min(position, duration) if duration > 0 else position)
        self._duration_ms, self._position_ms = duration, position
        if not self.progress.isSliderDown():
            pending = self._queued_seek if self._seek_target is None else self._seek_target
            shown = position if pending is None else pending
            with QSignalBlocker(self.progress):
                self.progress.setRange(0, duration)
                self.progress.setValue(shown)
            self.elapsed_time.setText(_format_time(shown))
        self.total_time.setText(_format_time(duration) if duration > 0 else "—:—")

    def _seek_limit(self, position: int) -> int:
        return min(position, max(0, self._duration_ms - PAUSE_MS))

    def _preview_seek(self, position: int) -> None:
        target = self._seek_limit(position)
        if target != position:
            with QSignalBlocker(self.progress):
                self.progress.setSliderPosition(target)
        self.elapsed_time.setText(_format_time(target))

    def _sync_seek_control(self) -> None:
        enabled = (
            self._can_seek and self._duration_ms > PAUSE_MS
            and self._phase in ("playing", "gate")
            and self._seek_target is None and self._queued_seek is None
        )
        self.progress.setEnabled(enabled)
        if enabled:
            hint = "Нажмите или перетащите ползунок. Финальные 3 секунды — через стрелку."
        elif self._phase == "tail":
            hint = "Перемотка недоступна во время финальных секунд."
        elif self._matched and not self._can_seek:
            hint = f"Плеер {self._app_name} не разрешает перемотку этого трека через Windows."
        else:
            hint = "Перемотка пока недоступна."
        self.progress.setToolTip(hint)

    def _request_seek(self, position: int) -> None:
        if not self.progress.isEnabled():
            return
        self._queued_seek = self._seek_limit(position)
        if self._phase == "gate":
            self.next_button.setEnabled(False)
        self._dispatch_seek()
        self._sync_seek_control()

    def _dispatch_seek(self) -> None:
        if self._queued_seek is None or self._busy:
            return
        target, self._queued_seek = self._queued_seek, None
        if self._phase not in ("playing", "gate") or not self._can_seek:
            self._update_timeline(self._position_ms, self._duration_ms)
            self._sync_seek_control()
            if self._phase == "gate":
                self.next_button.setEnabled(not self._rating_invalid)
            return
        if self._call("seek", seek_ms=target):
            self._seek_target = target
            self._seek_deadline = monotonic() + SEEK_TIMEOUT
            self._update_timeline(self._position_ms, self._duration_ms)

    def _reset_seek(self) -> None:
        self._can_seek = False
        self._queued_seek = self._seek_target = None
        self._seek_deadline = self._seek_notice_until = 0.0
        with QSignalBlocker(self.progress):
            self.progress.setSliderDown(False)
        self._sync_seek_control()

    def _seek_failed(self) -> None:
        self._seek_target = None
        self._seek_notice_until = monotonic() + 3
        self.status.setText("Плеер не подтвердил перемотку.")
        self._update_timeline(self._position_ms, self._duration_ms)
        self._sync_seek_control()
        if self._phase == "gate":
            self.next_button.setEnabled(not self._rating_invalid)

    def _button(self, icon: str, description: str) -> HoverButton:
        button = HoverButton(parent=self)
        button.setObjectName("listenControl")
        button.setFixedSize(42, 42)
        button.setIcon(line_icon(icon))
        button.setIconSize(QSize(20, 20))
        button.setToolTip(description)
        button.setAccessibleName(description)
        return button

    def start(self, album, provider: str = "yandex") -> None:
        self.stop()
        self._client_opened = False
        self._provider = provider
        if provider == "spotify":
            self._app_name = "Spotify"
            self._backend = SpotifyDesktopSession()
            self._waves.set_source(self._app_name, spotify_executable_paths(),
                                   package_family=SPOTIFY_PACKAGE, package_executable="Spotify.exe")
        else:
            self._app_name = "Яндекс Музыка"
            self._backend = YandexDesktopSession()
            self._waves.set_source(self._app_name, yandex_executable_paths())
        link_hint = f"Ссылка на альбом в «{self._app_name}»"
        self.album_link.setPlaceholderText(link_hint)
        self.album_link.setAccessibleName(link_hint)
        self.status.setText("")
        self._set_wave_error("")
        self._waves.setVisible(saved_visualizer() == "wave")
        self._album = album
        self._autoplay_album = album.title
        self._queue = []
        self._index = -1
        self.cover.set_placeholder(album.cover_letter, album.cover_color)
        path = STORE.resolve(album.cover_path)
        if path is not None:
            self.cover.set_photo(QPixmap(str(path)))
        self._show_track(0)
        source, _, album_id = album.source_id.partition(":")
        valid_id = album_id.isascii() and (
            album_id.isalnum() if provider == "spotify" else album_id.isdigit()
        )
        self.album_link.clear()
        if source == provider and valid_id:
            self._load_album(album_id=album_id)
        else:
            self._set_link_visible(True)
            self.status.setText(f"У этого альбома нет ссылки для «{self._app_name}».")
            self.album_link.setFocus()

    def _set_link_visible(self, visible: bool) -> None:
        self.album_link.setVisible(visible)
        self.load_button.setVisible(visible)

    def _load_album(self, *, album_id: str | None = None) -> None:
        if self._phase == "loading":
            return
        if self._provider == "spotify":
            generation = self._generation
            self._phase = "loading"
            try:
                album_id = album_id or resolve_spotify_album_id(self.album_link.text())
                if generation != self._generation:
                    return
                self._queue = spotify_playback_tracks(self._album, album_id)
            except (SpotifyError, DesktopPlaybackError) as error:
                if generation == self._generation:
                    self._set_link_visible(True)
                    self._fail(str(error), retry=False)
                return
            self.album_link.setText(f"https://open.spotify.com/album/{album_id}")
            self._set_link_visible(False)
            self._request_track()
            return
        try:
            if album_id is None:
                album_id = resolve_album_id(self.album_link.text())
            reply = request_playback_album(album_id)
        except YandexMusicError as error:
            self._set_link_visible(True)
            self._fail(str(error), retry=False)
            return
        self._album_id = album_id
        self.album_link.setText(f"https://music.yandex.ru/album/{album_id}")
        self._set_link_visible(False)
        self._phase = "loading"
        self.status.setText("Загружаем треклист Яндекс Музыки…")
        self._reply = reply
        reply.finished.connect(self._catalog_ready)

    def _catalog_ready(self) -> None:
        reply = self.sender()
        if reply is not self._reply:
            return
        self._reply = None
        try:
            catalog = read_playback_album(reply, self._album_id)
            self._queue = match_album_tracks(self._album, catalog)
            self._autoplay_album = catalog.title or self._album.title
        except YandexMusicError as error:
            self._set_link_visible(True)
            self._fail(str(error), retry=False)
            return
        self._request_track()

    def _show_track(self, index: int) -> None:
        self._waves.set_playing(False)
        self._reset_seek()
        self._index = index
        track = self._album.tracks[index]
        self.counter.setText(f"{self._app_name} · {index + 1} / {len(self._album.tracks)}")
        self._text_animation.stop()
        animate_text = not reduced_motion()
        self._text_reveal.set_progress(0.0 if animate_text else 1.0)
        self.title_label.setText(track.title)
        self.artist_label.setText(" · ".join(artist.name for artist in track.artists) or self._album.artists_text)
        if animate_text:
            self._text_animation.start()
        self._update_timeline(0, self._queue[index].duration_ms if self._queue else 0)
        self._matched = False
        self._playing = False
        self.pause_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._set_ratings_visible(False)
        self.track_changed.emit(index)

    def _request_track(self) -> None:
        if not self._queue:
            return
        self._cancel_autoplay()
        self._waves.set_playing(False)
        self._generation += 1
        self._pending_action = None
        self._reset_seek()
        self._matched = False
        self._phase = "waiting"
        self._deadline = monotonic() + START_TIMEOUT
        self._play_requested = False
        self._update_timeline(0, self._queue[self._index].duration_ms)
        self.pause_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self._set_ratings_visible(False)
        self.retry_button.hide()
        self._waiting_to_open = self._index == 0 and not self._client_opened
        self.status.setText(f"Ожидаем трек в «{self._app_name}»…")
        if self._index == 0:
            self._autoplay_at = monotonic()
        self._poll.start()
        self._poll_player()

    def _open_client(self) -> None:
        self._waiting_to_open = False
        self.status.setText(f"Открываем «{self._app_name}»…")
        self._start_foreground_guard()
        try:
            launch = launch_spotify_desktop if self._provider == "spotify" else launch_yandex_desktop
            # Both clients expose the individual Play buttons in the album's track list.
            launch(self._queue[0].uri.partition("/track/")[0])
        except (DesktopPlaybackError, YandexMusicError) as error:
            self._fail(str(error))
            return
        self._client_opened = True
        self._deadline = monotonic() + START_TIMEOUT
        self._autoplay_at = monotonic() + AUTOPLAY_GRACE

    def _start_autoplay(self, track) -> None:
        self._autoplay_at = None
        self._start_foreground_guard()
        cancelled = Event()
        self._autoplay_cancel = cancelled
        album = self._autoplay_album
        provider = self._provider
        preflight = self._waiting_to_open
        generation = self._generation
        report = self._autoplay_result.emit

        def start() -> None:
            invoked = try_start_desktop_track(provider, track, album, cancelled, wait_for_window=not preflight)
            if preflight and not cancelled.is_set():
                try:
                    report(generation, cancelled, invoked)
                except RuntimeError:
                    pass

        QThreadPool.globalInstance().start(start)

    def _on_autoplay_result(self, generation, cancelled, invoked: bool) -> None:
        if generation != self._generation or cancelled is not self._autoplay_cancel or cancelled.is_set():
            return
        self._autoplay_cancel = None
        if invoked:
            self._waiting_to_open = False
            self._client_opened = True
        else:
            self._open_client()

    def _cancel_autoplay(self) -> None:
        self._autoplay_at = None
        if self._autoplay_cancel is not None:
            self._autoplay_cancel.set()
            self._autoplay_cancel = None

    def _release_foreground_guard(self) -> None:
        if self._foreground_locked:
            self._foreground_locked = False
            self._foreground_timer.stop()
            unlock_foreground_after_launch()

    def _start_foreground_guard(self) -> None:
        self._foreground_deadline = monotonic() + START_TIMEOUT
        if not self._foreground_locked and lock_foreground_for_launch():
            self._foreground_locked = True
            self._foreground_input = last_input_tick()
            self._foreground_timer.start()

    def _check_foreground_guard(self) -> None:
        if self._provider == "spotify":
            paths, family = spotify_executable_paths(), SPOTIFY_PACKAGE
        else:
            paths, family = yandex_executable_paths(), ""
        if (monotonic() >= self._foreground_deadline or
                not keep_launch_in_background(int(self.window().winId()), self._foreground_input,
                                              paths, package_family=family)):
            self._release_foreground_guard()

    def _poll_player(self) -> None:
        if self._phase in ("waiting", "playing", "confirm_gate", "gate", "tail"):
            self._call("poll")

    def _call(self, action: str, track=None, *, seek_ms=None, backend=None) -> bool:
        if self._busy:
            return False
        self._busy = True
        generation = self._generation
        command = {"start": "play", "tail": "play", "play": "play",
                   "gate": "pause", "pause": "pause", "cleanup": "pause",
                   "seek": "seek", "next": "next"}.get(action)
        if track is None:
            track = self._queue[self._index]
        emit = self._media_result.emit
        QThreadPool.globalInstance().start(_MediaCall(
            backend if backend is not None else self._backend, track, command,
            lambda snapshot, accepted, error: emit(generation, action, snapshot, accepted, error),
            seek_ms=seek_ms,
        ))
        return True

    def _on_media_result(self, generation, action, snapshot, accepted, error) -> None:
        self._busy = False
        if self._cleanup is not None:
            (track, backend), self._cleanup = self._cleanup, None
            self._call("cleanup", track, backend=backend)
            return
        if generation != self._generation or action == "cleanup":
            return
        if action == "next":
            if not accepted or error:
                self.status.setText(f"Выберите показанный трек в «{self._app_name}».")
            return
        if action == "seek":
            if error or not accepted:
                self._seek_failed()
            else:
                self._seek_deadline = monotonic() + SEEK_TIMEOUT
            return
        if error:
            if action == "poll" and self._waiting_to_open:
                self._cancel_autoplay()
                self._open_client()
                return
            self._fail(error)
            return
        if action != "poll":
            if not accepted:
                self._fail(f"Плеер не принял команду. Включите нужный трек в «{self._app_name}».")
                return
            if action == "gate":
                self._phase = "confirm_gate"
                self._deadline = monotonic() + 1.5
            if action == "tail":
                self._phase = "tail"
                self._deadline = monotonic() + 8
                self.rating_area.setEnabled(False)
                self.status.setText("Дослушиваем трек…")
            if action == "play" and self._phase == "tail":
                self._deadline = monotonic() + 8
            self._dispatch_seek()
            self._sync_seek_control()
            return
        self._observe(snapshot)
        self._dispatch_seek()
        pending, self._pending_action = self._pending_action, None
        if pending == "tail":
            self._continue_tail()
        elif pending == "toggle":
            self._toggle_play()

    def _observe(self, snapshot) -> None:
        track = self._queue[self._index]
        now = monotonic()
        if snapshot is None or not track.matches(snapshot):
            self._waves.set_playing(False)
            if self._phase == "tail" and snapshot is not None:
                self._advance(snapshot)
            elif self._phase in ("waiting", "tail"):
                if (self._phase == "waiting" and self._autoplay_at is not None
                        and self._autoplay_at <= now < self._deadline):
                    self._start_autoplay(track)
                elif (self._phase == "waiting" and self._next_after is not None
                        and self._next_after <= now < self._deadline and snapshot is not None
                        and self._queue[self._index - 1].matches(snapshot)):
                    if self._call("next", self._queue[self._index - 1]):
                        self._next_after = None
                elif now >= self._deadline:
                    self._fail(f"Включите показанный трек в «{self._app_name}». Ожидаем медиасессию…",
                               listen=self._phase == "waiting")
            else:
                self._fail(f"В «{self._app_name}» играет другой трек или медиасессия закрыта.")
            return

        self._matched = True
        self._cancel_autoplay()
        if self._waiting_to_open:
            self._waiting_to_open = False
            self._client_opened = True
        self._next_after = None
        self._playing = snapshot.playing
        if self._playing and self._foreground_locked:
            self._check_foreground_guard()
            self._release_foreground_guard()
        self._waves.set_playing(self._playing)
        self._can_seek = snapshot.can_seek
        self.retry_button.hide()
        duration = snapshot.duration_ms or track.duration_ms
        position = snapshot.position_ms
        remaining = duration - position
        if self._seek_target is not None:
            target = self._seek_target
            if abs(position - target) <= SEEK_TOLERANCE_MS:
                self._seek_target = None
                self._seek_notice_until = 0.0
                if self._phase == "gate" and target < duration - PAUSE_MS:
                    self._phase = "playing"
                    self.next_button.setEnabled(False)
            elif now >= self._seek_deadline:
                self._seek_failed()
            else:
                return
        self._update_timeline(position, duration)
        if self._phase == "waiting":
            if not snapshot.playing:
                if not self._play_requested:
                    self._play_requested = self._call("start")
                elif now >= self._deadline:
                    self.status.setText(f"Нажмите воспроизведение в «{self._app_name}».")
                return
            self._phase = "playing"

        self.pause_button.setIcon(self._pause_icon if snapshot.playing else self._play_icon)

        if self._phase == "tail":
            if duration > 0 and (
                remaining <= 0 or (not snapshot.playing and remaining <= 350)
            ):
                self._advance(snapshot)
            elif snapshot.playing and now >= self._deadline:
                self._fail("Не удалось дождаться окончания трека. Проверьте воспроизведение.")
            else:
                self.pause_button.setEnabled(True)
                self.status.setText("Дослушиваем трек…" if snapshot.playing else "Воспроизведение приостановлено")
            return

        if self._phase == "confirm_gate":
            if not snapshot.playing:
                self._pause_for_ratings()
            elif now >= self._deadline:
                self._fail("Плеер не подтвердил паузу.")
            return
        if self._phase == "gate":
            self._sync_seek_control()
            if snapshot.playing:
                self.next_button.setEnabled(False)
                self._call("gate")
            elif self._seek_notice_until and now >= self._seek_notice_until:
                self._seek_notice_until = 0.0
                self._pause_for_ratings()
            return

        self.pause_button.setEnabled(True)
        self._sync_seek_control()
        if duration <= 0 or (snapshot.duration_ms <= 0 and position <= 0):
            self.status.setText("Клиент пока не передаёт позицию воспроизведения.")
            return
        if duration > 0 and remaining <= SHOW_RATINGS_MS:
            self._set_ratings_visible(True)
            if remaining <= PAUSE_MS:
                self.pause_button.setEnabled(False)
                if self._queued_seek is not None:
                    return
                if snapshot.playing:
                    if self._call("gate"):
                        self._phase = "confirm_gate"
                        self._deadline = now + 1.5
                        self._sync_seek_control()
                else:
                    self._pause_for_ratings()
                return
        else:
            self._set_ratings_visible(False)
        if now >= self._seek_notice_until:
            self.status.setText(f"Воспроизведение в «{self._app_name}»" if snapshot.playing else "Воспроизведение приостановлено")

    def _pause_for_ratings(self) -> None:
        self._phase = "gate"
        self._set_ratings_visible(True)
        self.pause_button.setEnabled(False)
        self.status.setText("Пауза перед финалом · выставьте оценки и нажмите стрелку")
        self.next_button.setEnabled(not self._rating_invalid and self._queued_seek is None)
        self._sync_seek_control()

    def _toggle_play(self) -> None:
        if self._phase not in ("playing", "tail"):
            return
        if not self._call("pause" if self._playing else "play"):
            self._pending_action = "toggle"

    def _continue_tail(self) -> None:
        if (self._phase == "gate" and not self._rating_invalid
                and self._queued_seek is None and self._seek_target is None):
            self.next_button.setEnabled(False)
            if not self._call("tail"):
                self._pending_action = "tail"

    def set_rating_error(self, invalid: bool) -> None:
        self._rating_invalid = invalid
        self.rating_error.setText("Оценку 11 можно поставить один раз на участника.")
        self.rating_error.setVisible(invalid)
        if self._ratings_requested:
            self._layout_ratings()
        self.next_button.setEnabled(self._phase == "gate" and not invalid
                                    and self._pending_action != "tail"
                                    and self._queued_seek is None and self._seek_target is None)

    def _advance(self, snapshot) -> None:
        if self._index + 1 == len(self._queue):
            self.completed.emit()
            return
        was_playing = snapshot.playing
        self._show_track(self._index + 1)
        if self._queue[self._index].matches(snapshot) and was_playing and snapshot.position_ms < 10_000:
            self._phase = "playing"
            self._observe(snapshot)
        else:
            self._next_after = monotonic() + TRACK_CHANGE_GRACE
            self._request_track()

    def _fail(self, message: str, *, retry: bool = True, listen: bool = False) -> None:
        self._release_foreground_guard()
        self._waves.set_playing(False)
        if not listen:
            self._cancel_autoplay()
            self._phase = "error"
            self._poll.stop()
            self._pending_action = None
            self._set_ratings_visible(False)
            self._reset_seek()
        self.status.setText(message)
        self.retry_button.setText("Обновить подключение" if self._client_opened or self._index > 0
                                  else f"Открыть «{self._app_name}»")
        self.retry_button.setVisible(retry)
        self.pause_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def stop(self) -> None:
        self._release_foreground_guard()
        self._cancel_autoplay()
        self._waiting_to_open = False
        self._waves.set_playing(False)
        self._poll.stop()
        self._text_animation.stop()
        self._set_ratings_visible(False)
        self._ratings_animation.stop()
        self._apply_rating_progress(0.0)
        self._next_after = None
        self._generation += 1
        self._pending_action = None
        self._reset_seek()
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.finished.disconnect(self._catalog_ready)
            reply.abort()
            reply.deleteLater()
        if self._matched and self._phase != "idle" and self._queue:
            track = self._queue[self._index]
            if not self._call("cleanup", track):
                self._cleanup = track, self._backend
        self._phase = "idle"

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._waves.setGeometry(self.rect())
        self._waves.lower()
