"""Проверки пустой библиотеки, регистрации и загрузки обновлений."""

import hashlib
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(ROOT):
    raise SystemExit("Run this check through checks/run.py.")
sys.path.insert(0, str(ROOT))

from app import theme
from app.services.updates import Release, Updates, find_update
from app.store import DATA_DIR, STORE, MusicStore
from app.ui.dialogs.profile_dialog import PAGE_LOGIN, PAGE_REGISTER
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
        self.assertEqual((STORE.albums, STORE.artists, STORE.users), ([], [], []))
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        window.open_profile()
        profile = window._profile_overlay
        self.assertEqual(profile.pages.currentIndex(), PAGE_REGISTER)
        profile.in_reg_login.setText("Новый профиль")
        profile.in_reg_password.setText("sample-password")
        profile.in_reg_password2.setText("sample-password")
        profile.btn_register.click()
        self.assertEqual(STORE.current_user.username, "Новый профиль")
        reopened = MusicStore()
        self.addCleanup(reopened._conn.close)
        self.assertEqual(reopened.current_user.id, STORE.current_user.id)
        STORE.logout()
        profile.close_overlay()
        window.open_profile()
        self.assertEqual(profile.pages.currentIndex(), PAGE_LOGIN)
        self.assertEqual(window.sidebar.version_label.text(), VERSION)
        self.assertFalse(window.sidebar.btn_update.isEnabled())
        self.assertNotIn("rooms", window.sidebar._destinations)
        window.updates.available.emit("1.0.1")
        self.assertTrue(window.sidebar.btn_update.isEnabled())
        window.updates.available.emit("")
        self.assertFalse(window.sidebar.btn_update.isEnabled())

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
              patch("app.services.updates.QProcess.startDetached", return_value=(True, 1)) as run):
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
            run.assert_called_once_with(str(installer), [], str(directory))
            self.assertEqual(installer.read_bytes(), CONTENT)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
