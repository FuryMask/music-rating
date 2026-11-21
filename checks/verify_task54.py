"""Проверки пустой библиотеки, регистрации и загрузки обновлений."""

import hashlib
import os
import json
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSettings, QThreadPool
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(ROOT):
    raise SystemExit("Run this check through checks/run.py.")
sys.path.insert(0, str(ROOT))

from app import theme
from app.models import AlbumDraft, TrackDraft
from app.services.updates import Release, Updates, find_update
from app.store import DATA_DIR, STORE, MusicStore
from app.services.cloud_library import CloudSession
from app.services.windows_credentials import protect_secret
from app.ui.dialogs.cloud_upload_dialog import CloudUploadDialog
from app.ui.main_window import MainWindow
from app.version import INSTALLER_NAME, RELEASE_REPOSITORY, VERSION


CONTENT = b"fixture installer"
SHA256 = hashlib.sha256(CONTENT).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(CONTENT)))
        self.end_headers()
        self.wfile.write(CONTENT)

    def log_message(self, *args) -> None:
        pass


class ReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication([])
        theme.apply_theme(cls.app)

    def test_new_library_and_profile(self) -> None:
        self.assertEqual(DATA_DIR, ROOT / "data")
        self.assertEqual((STORE.albums, STORE.artists), ([], []))
        window = MainWindow()
        self.addCleanup(window.close)
        window.move(77, 93)
        window.show()
        window.start_cloud()
        login = window._cloud_upload
        QTest.qWait(50)
        self.assertIs(login.pages.currentWidget(), login.sign_in)
        self.assertEqual(login.geometry().topLeft(), window.mapToGlobal(QPoint()))
        self.assertLessEqual((login.card.geometry().center() - login.rect().center()).manhattanLength(), 2)
        window.resize(1050, 760)
        QTest.qWait(40)
        self.assertEqual(login.size(), window.size())
        self.assertLessEqual((login.card.geometry().center() - login.rect().center()).manhattanLength(), 2)
        session = CloudSession("test-id", "token", email="test@example.test", display_name="Облачный профиль")
        with patch.object(login, "poll"):
            login._authenticated(session)
            self.assertFalse(login.isVisible())
            window.open_profile()
            profile = window._profile_overlay
            self.assertEqual(profile.lbl_name.text(), "Облачный профиль")
            self.assertIn(session.email, profile.lbl_email.text())
            with patch.object(login._cloud, "sign_out"):
                profile.btn_logout.click()
                self.assertTrue(login.isVisible())
                self.assertIsNone(login.catalog_session())
                QThreadPool.globalInstance().waitForDone(2000)
            login.reject()
        self.assertEqual(window.sidebar.version_label.text(), VERSION)
        self.assertFalse(window.sidebar.btn_update.isEnabled())
        self.assertNotIn("rooms", window.sidebar._destinations)
        window.updates.available.emit("1.0.1")
        self.assertTrue(window.sidebar.btn_update.isEnabled())
        window.updates.available.emit("")
        self.assertFalse(window.sidebar.btn_update.isEnabled())

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI session")
    def test_legacy_database_and_saved_cloud_session_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "library.db"
            with patch("app.store.DB_FILE", db):
                legacy = MusicStore()
                album = legacy.add_album(AlbumDraft(title="Старая библиотека", tracks=[TrackDraft("Трек")]))
                legacy.rate_album(album, ["Георгий"], [[8.5]])
                legacy._conn.executescript("""
                    CREATE TABLE users (id TEXT, password_hash TEXT);
                    INSERT INTO users VALUES ('legacy-id', 'old-hash');
                    INSERT INTO meta VALUES ('current_user_id', 'legacy-id');
                """)
                legacy._conn.close()
                current = MusicStore()
            try:
                self.assertEqual(current.legacy_cloud_profile(), "legacy-id")
                self.assertIsNone(current._meta_get("current_user_id"))
                self.assertIsNone(current._conn.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone())
                self.assertEqual(current.albums[0].ratings.values, [[8.5]])
                user_id = "4cd14dde-d97b-4225-a033-e699c407fd4f"
                self.assertEqual(current.user_stats(user_id, "Георгий").rated_count, 1)
                settings = QSettings(str(Path(directory) / "session.ini"), QSettings.Format.IniFormat)
                settings.setValue("CloudSession/legacy-id", protect_secret(json.dumps({
                    "user_id": user_id, "refresh_token": "legacy-refresh",
                })))
                parent = QWidget()
                with (patch("app.ui.dialogs.cloud_upload_dialog.STORE", current),
                      patch("app.ui.dialogs.cloud_upload_dialog.QSettings", return_value=settings)):
                    dialog = CloudUploadDialog(parent)
                    self.assertEqual(dialog.catalog_session().refresh_token, "legacy-refresh")
                    self.assertFalse(settings.contains("CloudSession/legacy-id"))
                    self.assertTrue(settings.contains("CloudSession/current"))
                    dialog.logout()
                    self.assertIsNone(CloudUploadDialog(parent).catalog_session())
            finally:
                current._conn.close()

    def test_release_validation(self) -> None:
        tag = "v1.10.0"
        asset = {"name": INSTALLER_NAME, "state": "uploaded", "size": len(CONTENT),
                 "browser_download_url":
                     f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{tag}/{INSTALLER_NAME}",
                 "digest": f"sha256:{SHA256}"}
        payload = {"tag_name": tag, "draft": False, "prerelease": False, "assets": [asset]}
        self.assertEqual(find_update(payload, "1.9.9"), Release(
            "1.10.0", asset["browser_download_url"], len(CONTENT), SHA256))
        self.assertIsNone(find_update(payload, "1.10.0"))
        self.assertIsNone(find_update(payload, "2.0.0"))
        for fields in ({"prerelease": True}, {"draft": True}, {"tag_name": "v1.10.0-beta"}, {"assets": []}):
            with self.subTest(fields=fields):
                self.assertIsNone(find_update({**payload, **fields}, "1.0.0"))
        for fields in ({"digest": None}, {"state": "new"}, {"size": True},
                       {"browser_download_url": "https://example.com/MusicRating-Setup.exe"}):
            with self.subTest(fields=fields):
                self.assertIsNone(find_update({**payload, "assets": [{**asset, **fields}]}, "1.0.0"))

    @unittest.skipUnless(sys.platform == "win32", "Windows installer")
    def test_stream_verification_before_launch(self) -> None:
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, tempfile.TemporaryDirectory() as directory:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self._check_download(server.server_port, Path(directory))
            finally:
                server.shutdown()
                thread.join()

    def _check_download(self, port: int, directory: Path) -> None:
        parent = MainWindow()
        self.addCleanup(parent.close)
        updates = Updates(parent)
        failed = QSignalSpy(updates.failed)
        started = QSignalSpy(updates.installer_started)
        url = f"http://127.0.0.1:{port}/{INSTALLER_NAME}"
        installer = directory / INSTALLER_NAME
        with (patch("app.services.updates.QTemporaryDir") as temp,
              patch("app.services.updates.QProcess") as process):
            run = process.return_value.startDetached
            run.return_value = (True, 1)
            temp.return_value.isValid.return_value = True
            temp.return_value.filePath.return_value = str(installer)
            updates.release = Release("1.0.1", url, len(CONTENT), "0" * 64)
            updates.install()
            for _ in range(200):
                if failed.count():
                    break
                QTest.qWait(20)
            self.assertEqual(failed.count(), 1)
            self.assertEqual(failed.at(0), ["Проверка файла обновления не прошла."])
            run.assert_not_called()
            installer.unlink()

            updates.release = Release("1.0.1", url, len(CONTENT), SHA256)
            updates.install()
            for _ in range(200):
                if started.count():
                    break
                QTest.qWait(20)
            self.assertEqual(started.count(), 1)
            run.assert_called_once_with()
            process.return_value.setProgram.assert_called_once_with(str(installer))
            process.return_value.setWorkingDirectory.assert_called_once_with(str(directory))
            environment = process.return_value.setProcessEnvironment.call_args.args[0]
            self.assertEqual(environment.value("PYINSTALLER_RESET_ENVIRONMENT"), "1")
            self.assertEqual(installer.read_bytes(), CONTENT)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
