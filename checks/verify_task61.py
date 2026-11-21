"""Check the desktop catalog flow without provider credentials."""

import json
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(ROOT):
    raise SystemExit("Run this check through checks/run.py.")
sys.path.insert(0, str(ROOT))

from app.services import genius, music_catalog, spotify
from app.services.cloud_library import CloudSession
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay

ALBUM_ID = "A" * 22
ARTIST_ID = "B" * 22
ARTIST = {"name": "Артист", "id": ARTIST_ID}


class CatalogHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, self.headers.get("Authorization"), self.headers.get("apikey"), data))
        if data["action"] == "spotify-album":
            response = {"album": {"name": "Альбом", "release_date": "2026-11-20", "artists": [ARTIST],
                                  "tracks": {"items": [{"name": "Песня", "artists": [ARTIST]}]}},
                        "photos": {ARTIST_ID: [{"url": "https://example.test/photo", "width": 300, "height": 300}]}}
        else:
            response = {"17": {"response": {"song": {"primary_artist": ARTIST,
                                                     "featured_artists": [{"name": "Гость"}]}}}}
        raw = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:
        pass


class MusicCatalogTest(unittest.TestCase):
    def test_imports_with_cloud_sign_in(self) -> None:
        qt = QApplication([])
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
            finally:
                window.close()
                qt.processEvents()
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
