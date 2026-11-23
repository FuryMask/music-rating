"""Check the desktop catalog flow without provider credentials."""

import json
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(ROOT):
    raise SystemExit("Run this check through checks/run.py.")
sys.path.insert(0, str(ROOT))

from app.services import genius, music_catalog, spotify
from app.models import AlbumDraft, TrackDraft
from app.services.cloud_library import CloudLibrary, CloudSession
from app.store import MusicStore, STORE
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay
from app.ui.main_window import MainWindow

ALBUM_ID = "A" * 22
ARTIST_ID = "B" * 22
ARTIST = {"name": "Артист", "id": ARTIST_ID}
USER_ID = "4cd14dde-d97b-4225-a033-e699c407fd4f"


class CatalogHandler(BaseHTTPRequestHandler):
    def _reply(self, status, response) -> None:
        raw = json.dumps(response).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_PUT(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.profile_request = self.path, self.headers.get("Authorization"), request
        self._reply(200, {"id": USER_ID, "user_metadata": request["data"]})

    def do_POST(self) -> None:
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/rest/v1/rpc/"):
            self._reply(403, {"code": "PT403"})
            return
        if getattr(self.server, "missing_function", False):
            self._reply(404, {"code": "NOT_FOUND"})
            return
        self.server.requests.append((self.path, self.headers.get("Authorization"), self.headers.get("apikey"), data))
        if data["action"] == "spotify-album":
            response = {"album": {"name": "Альбом", "release_date": "2026-11-20", "artists": [ARTIST],
                                  "tracks": {"items": [{"name": "Песня", "artists": [ARTIST]}]}},
                        "photos": {ARTIST_ID: [{"url": "https://example.test/photo", "width": 300, "height": 300}]}}
        else:
            response = {"17": {"response": {"song": {"primary_artist": ARTIST,
                                                     "featured_artists": [{"name": "Гость"}]}}}}
        self._reply(200, response)

    def log_message(self, *args) -> None:
        pass


class MusicCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication([])

    def test_imports_with_cloud_sign_in(self) -> None:
        window = QWidget()
        window.resize(900, 600)
        window.show()
        with ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler) as server:
            server.requests = []
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                session = None
                client = music_catalog.MusicCatalog(lambda: session, window)
                overlay = CreateChoiceOverlay(window, catalog=client)
                loaded = []
                auth = []
                overlay.album_loaded.connect(loaded.append)
                overlay.cloud_sign_in_requested.connect(lambda: auth.append(True))
                with (patch.object(music_catalog, "PROJECT_URL", f"http://127.0.0.1:{server.server_port}"),
                      patch.object(spotify, "load_credentials", return_value=None),
                      patch.object(spotify, "_get_token", side_effect=AssertionError("Local token requested")),
                      patch.object(genius, "load_access_token", return_value="")):
                    overlay.open()
                    overlay.pages.setCurrentIndex(1)
                    overlay.input_link.setText(f"https://open.spotify.com/album/{ALBUM_ID}")
                    overlay.btn_load.click()
                    self.assertEqual(overlay.pages.currentIndex(), 1)
                    self.assertEqual(auth, [True])
                    self.assertEqual(server.requests, [])

                    session = CloudSession("member", "mock-music-rating-session")
                    overlay.btn_load.click()
                    self.assertEqual(len(loaded), 1)
                    self.assertEqual(loaded[0].album_id, f"spotify:{ALBUM_ID}")
                    self.assertEqual(loaded[0].tracks[0].title, "Песня")
                    self.assertEqual(loaded[0].photos, {"Артист": "https://example.test/photo"})

                    album = genius.GeniusAlbum(tracks=[genius.GeniusTrack("Трек", ["Артист"], 17)])
                    genius._enrich_performers(album, catalog=client)
                    self.assertEqual(album.tracks[0].artists, ["Артист", "Гость"])
                    self.assertEqual([request[3] for request in server.requests],
                                     [{"action": "spotify-album", "id": ALBUM_ID}, {"action": "genius-songs", "ids": [17]}])
                    for url, authorization, api_key, _ in server.requests:
                        self.assertEqual(url, "/functions/v1/music-catalog")
                        self.assertEqual(authorization, "Bearer mock-music-rating-session")
                        self.assertEqual(api_key, music_catalog.PUBLISHABLE_KEY)
                    server.missing_function = True
                    with self.assertRaisesRegex(music_catalog.CatalogError, "music-catalog не опубликована"):
                        client.request("spotify-album", id=ALBUM_ID)
            finally:
                window.close()
                self.qt.processEvents()
                server.shutdown()
                thread.join()

    def test_profile_name_adds_current_account_to_ratings(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        with ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                cloud = window._cloud_upload
                cloud._cloud = CloudLibrary(f"http://127.0.0.1:{server.server_port}", "mock-public-key")
                cloud._save_session(CloudSession(USER_ID, "mock-music-rating-session"))
                album = STORE.add_album(AlbumDraft(title="Проверка имени", tracks=[TrackDraft("Трек")]))
                STORE.rate_album(album, ["Старое имя"], [[8.5]], rater_ids=[USER_ID])
                self.assertEqual(cloud.rating_members(), {})
                window.open_profile()
                profile = window._profile_overlay
                profile.tab_buttons[1].click()
                profile.display_name_input.setText(" Новое имя ")
                profile.btn_save_display_name.click()
                for _ in range(150):
                    if cloud.rating_members() and not cloud._polling:
                        break
                    QTest.qWait(20)
                self.assertEqual(server.profile_request, ("/auth/v1/user", "Bearer mock-music-rating-session",
                                                          {"data": {"display_name": "Новое имя"}}))
                self.assertEqual(cloud.members(), {})
                self.assertEqual(cloud.rating_members(), {USER_ID: "Новое имя"})
                self.assertEqual(album.ratings.rater_names, ["Новое имя"])
                saved = MusicStore()
                try:
                    self.assertEqual(saved.albums[0].ratings.rater_names, ["Новое имя"])
                finally:
                    saved._conn.close()
                profile.close_overlay()
                window.open_rate_album(album)
                wizard = window._rate_overlay
                self.assertEqual(list(wizard.rater_buttons), [USER_ID])
                self.assertEqual(wizard.rater_buttons[USER_ID].text(), "Новое имя")
                wizard.rater_buttons[USER_ID].click()
                wizard.go_to_step(1)
                self.assertEqual(wizard._values, [[8.5]])
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
