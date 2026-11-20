"""Regression coverage for listening mode, with simulated media snapshots."""

import os
from pathlib import Path
import sys
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, QThreadPool, Qt
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(APP):
    raise SystemExit("Run this check through checks/run.py.")

from app import theme
from app.models import Album, ArtistDraft, TrackDraft
from app.services.desktop_playback import WindowsMediaSession
from app.services.spotify_playback import SPOTIFY_PACKAGE, SpotifyDesktopSession, _is_spotify_app, launch_spotify_desktop
from app.services.yandex_playback import MediaSnapshot, PlaybackTrack, launch_yandex_desktop
from app.ui.dialogs.profile_dialog import ProfileOverlay
from app.ui.pages.rate_album import RateAlbumOverlay
from app.ui.widgets.audio_waves import AudioWaves, BANDS


def wait_for(predicate, timeout: float = 1.5) -> bool:
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(20)
    return predicate()


class ListeningModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication([])
        cls.app.setStyle("Fusion")
        theme.apply_theme(cls.app, "Ruby")

    def setUp(self) -> None:
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings = QSettings(str(Path(settings_dir.name) / "settings.ini"), QSettings.Format.IniFormat)
        appearance = patch.object(theme, "_appearance_settings", return_value=settings)
        appearance.start()
        self.addCleanup(appearance.stop)
        capture = patch.object(AudioWaves, "_should_capture", return_value=False)
        capture.start()
        self.addCleanup(capture.stop)
        transport = patch.object(WindowsMediaSession, "read", return_value=(None, False))
        transport.start()
        self.addCleanup(transport.stop)
        motion = patch.dict("os.environ", {"MUSICRATING_REDUCED_MOTION": "0"})
        motion.start()
        self.addCleanup(motion.stop)
        self.addCleanup(QThreadPool.globalInstance().waitForDone, 1500)
        self.window = QWidget()
        self.addCleanup(self.window.close)
        self.window.resize(1000, 680)
        self.window.show()

    def open_player(self, position: int = 84_000, provider: str = "yandex"):
        album = Album("Альбом", artist_names=["Исполнитель"], tracks=[
            TrackDraft("Первый трек"), TrackDraft("Второй трек", [ArtistDraft("Другой исполнитель")]),
        ])
        wizard = RateAlbumOverlay(self.window)
        self.addCleanup(wizard._close_player)
        wizard.open_for(album)
        wizard._raters = [f"Участник {index + 1}" for index in range(14)]
        wizard._selected = set(wizard._raters)
        wizard._values = [[None] * len(wizard._raters) for _ in album.tracks]
        wizard.go_to_step(1)
        wizard.btn_listen.click()
        choice = wizard._playback_choice
        self.assertTrue(choice.isVisible())
        if provider == "spotify":
            choice.spotify_button.click()
            return wizard, wizard._player
        choice.yandex_button.click()
        player = wizard._player
        player._queue = [
            PlaybackTrack("", track.title, track.title, tuple(
                artist.name for artist in track.artists
            ) or tuple(album.artist_names), 90_000)
            for track in album.tracks
        ]
        player._phase = "playing"
        player._observe(MediaSnapshot("Первый трек", "Исполнитель", position, 90_000, True, True))
        return wizard, player

    def test_visualizer_setting_persists(self) -> None:
        profile = ProfileOverlay(self.window)
        combo = profile.visualizer_select
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Выключено", "Волна"])
        self.assertEqual(combo.currentData(), "wave")
        combo.setCurrentIndex(0)
        self.assertEqual(ProfileOverlay(self.window).visualizer_select.currentData(), "off")
        wizard, player = self.open_player()
        self.assertTrue(player._waves.isHidden())
        wizard._close_player()
        combo.setCurrentIndex(1)
        wizard._open_player()
        self.assertTrue(player._waves.isVisible())

    def test_title_ratings_and_idle_fades(self) -> None:
        wizard, player = self.open_player()
        self.assertEqual(player._text_reveal._progress, 0.0)
        self.assertEqual(player._rating_reveal._progress, 0.0)
        QTest.qWait(220)
        self.assertTrue(0 < player._text_reveal._progress < 1)
        self.assertTrue(0 < player._rating_reveal._progress < 1)
        self.assertEqual(player._rating_panel.geometry(), player.cover.geometry())
        self.assertGreater(player.rating_area.verticalScrollBar().maximum(), 0)
        wizard._player_cells[0].setText("8.5")
        self.assertEqual(wizard._cells[0][0].text(), "8.5")
        cover = player.cover.mapTo(player, QPoint())
        slider = player.progress.mapTo(player, QPoint())
        # Check the actual idle threshold, then the opacity during both transitions.
        player._last_activity -= 4
        player._check_idle()
        self.assertFalse(player._idle)
        player._last_activity -= 1.1
        player._check_idle()
        QTest.qWait(130)
        self.assertTrue(0 < player._idle_opacity < 1)
        QTest.qWait(260)
        for widget in (player.cover, player.title_label, player.artist_label, player.progress):
            self.assertTrue(widget.isVisible())
        for widget in (player.status, player.elapsed_time, player.pause_button, player._rating_panel):
            self.assertFalse(widget.isVisible())
        self.assertTrue(player._waves.isVisible())
        self.assertEqual(player.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.assertEqual(player.progress.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.assertEqual(player.cover.mapTo(player, QPoint()), cover)
        self.assertEqual(player.progress.mapTo(player, QPoint()), slider)

        with patch("app.ui.pages.listen_and_rate.QCursor") as cursor:
            cursor.pos.return_value = player._cursor + QPoint(20, 0)
            player._check_idle()
            QTest.qWait(130)
            self.assertTrue(0 < player._idle_opacity < 1)
            QTest.qWait(260)
        self.assertTrue(player._rating_panel.isVisible())
        self.assertNotEqual(player.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.assertEqual(player._idle_opacity, 1)
        self.assertEqual(wizard._player_cells[0].text(), "8.5")
        self.assertEqual(player.cover.mapTo(player, QPoint()), cover)
        self.assertEqual(player.progress.mapTo(player, QPoint()), slider)

        player._show_track(1)
        self.assertEqual(player.title_label.text(), "Второй трек")
        self.assertEqual(player.artist_label.text(), "Другой исполнитель")
        self.assertEqual(player._text_reveal._progress, 0.0)
        self.assertFalse(player._rating_panel.isVisible())
        QTest.qWait(650)
        self.assertEqual(player._text_reveal._progress, 1.0)
        self.assertTrue(player.cover.isVisible())
        self.assertEqual(player.cover.mapTo(player, QPoint()), cover)
        wizard._close_player()
        self.assertFalse(player._cursor_timer.isActive())

    def test_ratings_restore_idle_controls(self) -> None:
        _, player = self.open_player(position=40_000)
        with patch("app.ui.pages.listen_and_rate.QCursor") as cursor:
            cursor.pos.return_value = player._cursor
            player._last_activity = monotonic() - 5.1
            player._check_idle()
            self.assertTrue(wait_for(lambda: not player.pause_button.isVisible()))
            self.assertFalse(player.rating_area.isVisible())

            near_end = MediaSnapshot("Первый трек", "Исполнитель", 84_000, 90_000, True, True)
            player._observe(near_end)
            self.assertFalse(player._idle)
            self.assertTrue(player.rating_area.isVisible())
            self.assertEqual(player._rating_reveal._progress, 0.0)
            woke_at = player._last_activity
            self.assertTrue(wait_for(lambda: player._idle_opacity == 1.0))
            self.assertTrue(player.pause_button.isVisible())
            player._observe(near_end)
            self.assertEqual(player._last_activity, woke_at)
            self.assertTrue(wait_for(lambda: not player.cover.isVisible()))
            self.assertTrue(player.rating_area.isVisible())

    def test_next_track_reuses_client(self) -> None:
        wizard, player = self.open_player(position=40_000)
        first, second = player._queue
        finished = MediaSnapshot(first.title, first.artists[0], 90_000, 90_000, False)
        with (patch("app.ui.pages.listen_and_rate.launch_yandex_desktop") as launch,
              patch.object(player, "_call", return_value=True) as media):
            player._request_track()
            player._open_client()
            player._request_track()
            launch.assert_called_once_with(first.uri)
            player._phase = "tail"
            player._observe(finished)
            self.assertEqual(player._index, 1)
            self.assertEqual(player._phase, "waiting")
            media.reset_mock()
            player._observe(finished)
            media.assert_not_called()
            player._next_after = monotonic() - 1
            player._observe(MediaSnapshot("Другой трек", "Исполнитель", 0, 90_000, True))
            media.assert_not_called()
            player._observe(finished)
            player._observe(finished)
            media.assert_called_once_with("next", first)
            player._on_media_result(player._generation, "next", finished, False, "")
            self.assertEqual(player._phase, "waiting")
            player._request_track()
            launch.assert_called_once_with(first.uri)
            player._observe(MediaSnapshot(second.title, second.artists[0], 0, 90_000, True))
            self.assertEqual(player._phase, "playing")
            wizard._close_player()

    def test_fullscreen_button_and_exit_restore_window(self) -> None:
        wizard, player = self.open_player(position=40_000)
        generation = player._generation
        wizard._player_cells[0].setText("8.5")
        self.assertLess(player.fullscreen_button.x(), player.pause_button.x())
        player.fullscreen_button.click()
        self.assertTrue(wait_for(self.window.isFullScreen))
        self.assertEqual(player.fullscreen_button.accessibleName(), "Выйти из полноэкранного режима")
        player.fullscreen_button.click()
        self.assertTrue(wait_for(lambda: not self.window.isFullScreen()))
        self.assertFalse(self.window.isMaximized())
        self.assertIs(wizard._surface.currentWidget(), player)
        self.assertEqual(player._generation, generation)

        player.fullscreen_button.click()
        self.assertTrue(wait_for(self.window.isFullScreen))
        self.window.activateWindow()
        QTest.qWait(40)
        QTest.keyClick(player.album_link, Qt.Key.Key_Escape)
        self.assertTrue(wait_for(lambda: not self.window.isFullScreen()))
        self.assertIs(wizard._surface.currentWidget(), player)
        self.assertEqual(player.progress.value(), 40_000)
        self.assertEqual(wizard._player_cells[0].text(), "8.5")

        self.window.showMaximized()
        self.assertTrue(wait_for(self.window.isMaximized))
        player.fullscreen_button.click()
        self.assertTrue(wait_for(self.window.isFullScreen))
        player._set_idle(True)
        self.assertTrue(wait_for(lambda: player.cursor().shape() == Qt.CursorShape.BlankCursor))
        player.closed.emit()
        self.assertTrue(wait_for(lambda: not self.window.isFullScreen() and self.window.isMaximized()))
        self.assertTrue(wizard.steps.isVisible())
        self.assertNotEqual(player.cursor().shape(), Qt.CursorShape.BlankCursor)

    def test_wave_color_and_feathering(self) -> None:
        _, player = self.open_player()
        QTest.qWait(30)
        player._waves._levels = (1.0,) * BANDS
        image = player.grab().toImage()
        background = theme.themed_color(theme.BG_MAIN)
        accent = theme.themed_color(theme.ACCENT)
        half_accent = QColor(*(round((base + wave) / 2)
                               for base, wave in zip(background.getRgb()[:3], accent.getRgb()[:3])))
        self.assertEqual(image.pixelColor(320, 370).getRgb(), background.getRgb())
        self.assertEqual(image.pixelColor(320, image.height() - 1).getRgb(), background.getRgb())
        for actual, expected in zip(image.pixelColor(320, 500).getRgb(), half_accent.getRgb()):
            self.assertAlmostEqual(actual, expected, delta=5)
        near_edge = image.pixelColor(2, 500)
        self.assertLess(abs(near_edge.red() - background.red()), 12)
        player._set_idle(True)
        self.assertTrue(wait_for(lambda: not player.status.isVisible()))
        self.assertEqual(player.grab().toImage().pixelColor(320, 500).getRgb(),
                         image.pixelColor(320, 500).getRgb())

    def test_spotify_playback_and_choice(self) -> None:
        wizard, player = self.open_player(provider="spotify")
        self.assertIsInstance(player._backend, SpotifyDesktopSession)
        self.assertIn("Spotify", player.album_link.placeholderText())
        self.assertEqual(player._waves._source[2], SPOTIFY_PACKAGE)
        self.assertTrue(_is_spotify_app("Spotify.exe"))
        self.assertTrue(_is_spotify_app(f"{SPOTIFY_PACKAGE}!Spotify"))
        self.assertFalse(_is_spotify_app("browser.exe"))
        self.assertFalse(_is_spotify_app(SPOTIFY_PACKAGE + "-other!Spotify"))
        player.album_link.setText("https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv")
        with (patch("app.ui.pages.listen_and_rate.launch_spotify_desktop") as launch,
              patch.object(player, "_call", return_value=True) as transport):
            player.load_button.click()
            with patch("app.ui.pages.listen_and_rate.try_start_desktop_track", return_value=False) as probe:
                player._observe(None)
                self.assertTrue(wait_for(lambda: launch.called))
                self.assertEqual(probe.call_args.kwargs, {"wait_for_window": False})
            launch.assert_called_once_with("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")
            self.assertFalse(player.album_link.isVisible())
            self.assertEqual(player._queue[0].artists, ("Исполнитель",))
            with patch("app.ui.pages.listen_and_rate.try_start_desktop_track", return_value=True) as autoplay:
                player._autoplay_at = monotonic() - 1
                previous = MediaSnapshot("Предыдущий трек", "Исполнитель", 0, 90_000, False)
                player._observe(previous)
                self.assertTrue(wait_for(lambda: autoplay.called))
                player._observe(previous)
                autoplay.assert_called_once()
                provider, expected, album_name, cancellation = autoplay.call_args.args
                self.assertEqual(provider, "spotify")
                self.assertEqual(expected, player._queue[0])
                self.assertEqual(autoplay.call_args.kwargs, {"wait_for_window": True})
                self.assertEqual(album_name, wizard._album.title)
                self.assertFalse(cancellation.is_set())
            player._observe(MediaSnapshot("Первый трек", "Исполнитель", 84_000, 90_000, True, True))
            self.assertTrue(cancellation.is_set())
            self.assertTrue(player.rating_area.isVisible())
            self.assertTrue(player.progress.isEnabled())
            player._observe(MediaSnapshot("Первый трек", "Исполнитель", 87_000, 90_000, False, True))
            self.assertEqual(player._phase, "gate")
            player.next_button.click()
            self.assertEqual(transport.call_args.args, ("tail",))
            player._on_media_result(player._generation, "tail", None, True, "")
            player._observe(MediaSnapshot("Второй трек", "Другой исполнитель", 0, 90_000, True, True))
            launch.assert_called_once()
            self.assertEqual(player._index, 1)
            wizard._close_player()

        wizard.btn_listen.click()
        self.assertTrue(wizard._playback_choice.isVisible())
        QTest.qWait(250)
        chooser = wizard._playback_choice.grab().toImage()
        for x, y in ((0, 0), (chooser.width() - 1, 0), (0, chooser.height() - 1),
                     (chooser.width() - 1, chooser.height() - 1)):
            self.assertEqual(chooser.pixelColor(x, y).alpha(), 0)
        self.assertGreater(chooser.pixelColor(chooser.width() // 2, 4).alpha(), 150)
        wizard._playback_choice.back_button.click()
        self.assertFalse(player.isVisible())
        self.assertTrue(wizard.steps.isVisible())
        wizard._album.source_id = "spotify:4LH4d3cOWNNsVw41Gqt2kv"
        with (patch("app.ui.pages.listen_and_rate.launch_spotify_desktop") as launch,
              patch("app.ui.pages.listen_and_rate.try_start_desktop_track", return_value=False),
              patch.object(player, "_call", return_value=True)):
            wizard.btn_listen.click()
            wizard._playback_choice.spotify_button.click()
            player._observe(None)
            self.assertTrue(wait_for(lambda: launch.called))
            launch.assert_called_once_with("spotify:album:4LH4d3cOWNNsVw41Gqt2kv")
            self.assertFalse(player.album_link.isVisible())
            wizard._close_player()

    def test_spotify_desktop_uses_registered_uri_argument(self) -> None:
        executable = Path(sys.executable)
        uri = "spotify:album:4LH4d3cOWNNsVw41Gqt2kv"
        with (patch("app.services.spotify_playback.sys.platform", "win32"),
              patch("app.services.spotify_playback.spotify_executable_paths", return_value=(executable,)),
              patch("app.services.spotify_playback.launch_without_activation", return_value=True) as start):
            launch_spotify_desktop(uri)
        start.assert_called_once_with(executable, [f"--protocol-uri={uri}"])

    def test_yandex_autoplay_and_foreground_guard(self) -> None:
        wizard, player = self.open_player(position=40_000)
        track = PlaybackTrack("yandexmusic://album/12/track/34", "Первый трек", "Первый трек",
                              ("Исполнитель",), 90_000)
        player._queue[0] = track
        with (patch("app.ui.pages.listen_and_rate.lock_foreground_for_launch", return_value=True) as lock,
              patch("app.ui.pages.listen_and_rate.unlock_foreground_after_launch") as unlock,
              patch("app.ui.pages.listen_and_rate.keep_launch_in_background", return_value=True),
              patch("app.ui.pages.listen_and_rate.launch_yandex_desktop") as launch,
              patch("app.ui.pages.listen_and_rate.try_start_desktop_track", return_value=False) as autoplay,
              patch.object(player, "_call", return_value=True)):
            player._request_track()
            player._observe(None)
            self.assertTrue(wait_for(lambda: launch.called))
            launch.assert_called_once_with("yandexmusic://album/12")
            lock.assert_called_once()
            self.assertTrue(player._foreground_timer.isActive())
            autoplay.reset_mock()
            autoplay.return_value = True
            player._autoplay_at = monotonic() - 1
            player._observe(None)
            self.assertTrue(wait_for(lambda: autoplay.called))
            provider, expected, album_name, cancellation = autoplay.call_args.args
            self.assertEqual((provider, expected, album_name), ("yandex", track, wizard._album.title))
            self.assertEqual(autoplay.call_args.kwargs, {"wait_for_window": True})
            player._observe(MediaSnapshot("Первый трек", "Исполнитель", 1000, 90_000, True))
            unlock.assert_called_once()
            self.assertFalse(player._foreground_timer.isActive())
            self.assertTrue(cancellation.is_set())
            wizard._close_player()

    def test_autoplay_reuses_album_already_open_in_client(self) -> None:
        wizard, player = self.open_player(position=40_000)
        with (patch("app.ui.pages.listen_and_rate.launch_yandex_desktop") as launch,
              patch("app.ui.pages.listen_and_rate.try_start_desktop_track", return_value=True) as autoplay,
              patch.object(player, "_call", return_value=True)):
            player._request_track()
            player._observe(None)
            self.assertTrue(wait_for(lambda: player._client_opened))
            self.assertFalse(player._waiting_to_open)
            self.assertEqual(autoplay.call_args.kwargs, {"wait_for_window": False})
            launch.assert_not_called()
            wizard._close_player()

    def test_yandex_desktop_enables_renderer_accessibility(self) -> None:
        executable = Path(sys.executable)
        uri = "yandexmusic://album/12"
        with (patch("app.services.yandex_playback.yandex_executable_paths", return_value=(executable,)),
              patch("app.services.yandex_playback.launch_without_activation", return_value=True) as start):
            launch_yandex_desktop(uri)
        start.assert_called_once_with(executable, ["--enable-features=UiaProvider",
                                                   "--force-renderer-accessibility", uri])

    def test_status_timer_and_hover(self) -> None:
        _, player = self.open_player()
        status = player.status
        self.assertEqual(status._timer.interval(), 5000)
        status._timer.setInterval(120)
        status.setText("Первый статус")
        self.assertTrue(status._label.isVisible())
        for _ in range(3):
            QTest.qWait(50)
            status.setText("Первый статус")
        self.assertTrue(wait_for(lambda: status._indicator.arrow_visible))
        self.assertFalse(status._label.isVisible())
        QApplication.sendEvent(status._indicator, QEnterEvent(QPointF(), QPointF(), QPointF()))
        self.assertTrue(status._label.isVisible())
        self.assertFalse(status._indicator.arrow_visible)
        QApplication.sendEvent(status._indicator, QEvent(QEvent.Type.Leave))
        self.assertFalse(status._label.isVisible())
        self.assertTrue(status._indicator.arrow_visible)
        status.setText("Новый статус")
        self.assertTrue(status._label.isVisible())
        self.assertTrue(status._timer.isActive())


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
