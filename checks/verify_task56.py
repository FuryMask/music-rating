"""Exercise the cloud upload dialog and its HTTP contract with an isolated library."""

import json
import os
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(ROOT):
    raise SystemExit("Run this check through checks/run.py.")
sys.path.insert(0, str(ROOT))

from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.services.cloud_library import SHARED_ARTWORK, SHARED_STATUS, SHARED_UPLOAD, CloudLibrary, CloudSession
from app.services.shared_library import baseline, download_plan, upload_plan
from app.store import COVERS_DIR, MusicStore, STORE
from app.theme import apply_theme
from app.ui.main_window import MainWindow

USER_ID = "33d07720-0f58-45c2-aa60-4767541747c2"
TOKEN = "mock-user-session"
REFRESH_TOKEN = "mock-refresh-session"
OTHER_ID = "ad40a647-7db0-4ce5-b96a-d0d34ed08bde"
OTHER_TOKEN = "second-user-session"
MEMBERS = {USER_ID: "Участник", OTHER_ID: "Володя"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        digest = self.path.rsplit("/", 1)[-1]
        if self.path.startswith(SHARED_ARTWORK.replace("/object/", "/object/authenticated/")) and digest in self.server.images:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(self.server.images[digest])
        else:
            self.reply(404, {})

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("apikey") != "mock-public-key":
            self.reply(401, {})
        elif self.path == "/auth/v1/signup":
            self.reply(200, {"id": USER_ID})
        elif self.path == "/auth/v1/resend":
            if json.loads(body) == {"type": "signup", "email": "test@example.test"}:
                self.server.resend_count += 1
                self.reply(200, {})
            else:
                self.reply(400, {})
        elif self.path == "/auth/v1/verify":
            if json.loads(body) == {"type": "email", "email": "test@example.test", "token": "012345"}:
                self.server.confirmed = True
                self.reply(200, {"user": {"id": USER_ID}, "access_token": TOKEN, "refresh_token": REFRESH_TOKEN})
            else:
                self.reply(403, {"error_code": "otp_expired"})
        elif self.path == "/auth/v1/token?grant_type=password":
            if json.loads(body) == {"email": "test@example.test", "password": "test-cloud-password"}:
                if self.server.confirmed:
                    self.reply(200, {"user": {"id": USER_ID}, "access_token": TOKEN})
                else:
                    self.reply(400, {"error_code": "email_not_confirmed"})
            else:
                self.reply(400, {"error_code": "invalid_credentials"})
        elif self.path == "/auth/v1/token?grant_type=refresh_token":
            if json.loads(body) == {"refresh_token": REFRESH_TOKEN}:
                self.server.refreshes += 1
                self.reply(200, {"user": {"id": USER_ID}, "access_token": TOKEN, "refresh_token": REFRESH_TOKEN})
            else:
                self.reply(400, {"error_code": "refresh_token_not_found"})
        elif self.headers.get("Authorization") not in (f"Bearer {TOKEN}", f"Bearer {OTHER_TOKEN}"):
            self.reply(401, {})
        elif self.path.startswith(f"{SHARED_ARTWORK}/"):
            self.server.images[self.path.rsplit("/", 1)[1]] = body
            self.reply(200, {})
        elif self.path == SHARED_STATUS:
            if self.server.missing_schema:
                self.reply(404, {"code": "PGRST202"})
                return
            status = {"revision": str(self.server.revision), "has_data": bool(self.server.items),
                      "members": [{"id": member, "name": name} for member, name in MEMBERS.items()]}
            if json.loads(body)["p_download"]:
                status.update(shared=list(self.server.items.values()), personal=[])
            self.reply(200, status)
        elif self.path == SHARED_UPLOAD:
            if self.server.fail_upload:
                self.reply(500, {})
                return
            self.server.upload_count += 1
            self.server.revision += 1
            for item in json.loads(body)["p_items"]:
                self.server.items[item["kind"], item["item_id"]] = {**item, "updated_at": "2026-11-20T11:00:00+00:00"}
            self.reply(204)
        else:
            self.reply(404, {})

    def reply(self, status, payload=None) -> None:
        data = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


def wait_for(predicate) -> bool:
    for _ in range(220):
        if predicate():
            return True
        QTest.qWait(20)
    return False


class CloudUploadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication([])
        apply_theme(cls.qt)

    def test_preview_upload_and_retry(self) -> None:
        STORE.register_user("Участник", "local-password")
        album = STORE.add_album(AlbumDraft(title="Проверка облака", artists=[ArtistDraft("Исполнитель")],
                                          tracks=[TrackDraft("Трек")]))
        STORE.rate_album(album, ["Участник"], [[8.5]])
        COVERS_DIR.mkdir(exist_ok=True)
        (COVERS_DIR / "sample.png").write_bytes(b"fixture image")
        STORE.set_album_cover(album, "data/covers/sample.png")
        outside = ROOT / "local-only.png"
        outside.write_bytes(b"outside app artwork folder")
        STORE.add_artist("Исполнитель").photo_path = str(outside)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            server.items, server.images, server.upload_count, server.fail_upload = {}, {}, 0, True
            server.revision = 0
            server.refreshes = 0
            server.confirmed, server.resend_count = False, 0
            server.missing_schema = True
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            window = MainWindow()
            try:
                window.show()
                window.sidebar.btn_cloud_upload.click()
                dialog = window._cloud_upload
                dialog._cloud = CloudLibrary(f"http://127.0.0.1:{server.server_port}", "mock-public-key")
                self.assertTrue(dialog.isVisible())
                dialog.preview_button.click()
                self.assertTrue(wait_for(lambda: dialog.pages.currentWidget() is dialog.preview))
                self.assertEqual([dialog.tree.topLevelItem(i).childCount() for i in range(3)], [1, 1, 1])
                self.assertIn("8.5", dialog.tree.topLevelItem(2).child(0).text(0))
                self.assertEqual(server.upload_count, 0)
                dialog.preview_upload_button.click()
                self.assertTrue(wait_for(lambda: dialog.pages.currentWidget() is dialog.sign_in))
                self.assertEqual({button.text() for button in dialog.sign_in.findChildren(QPushButton)},
                                 {"Назад", "Создать аккаунт", "Войти"})

                dialog.email.setText("test@example.test")
                dialog.password.setText("test-cloud-password")
                dialog._authenticate(register=True)
                self.assertTrue(wait_for(lambda: dialog.pages.currentWidget() is dialog.verify_email), dialog.status.text())
                dialog._show_sign_in()
                dialog.password.setText("test-cloud-password")
                dialog.password.returnPressed.emit()
                self.assertTrue(wait_for(lambda: "Почта ещё не подтверждена" in dialog.status.text()))
                self.assertIs(dialog.pages.currentWidget(), dialog.verify_email)
                dialog.email_code.setText("654321")
                dialog.email_code.returnPressed.emit()
                self.assertTrue(wait_for(lambda: "Код неверный или истёк" in dialog.status.text()))
                dialog._resend_code()
                self.assertTrue(wait_for(lambda: "Запрошено новое письмо" in dialog.status.text()))
                self.assertEqual(server.resend_count, 1)
                self.assertEqual(dialog.email_code.text(), "")
                dialog.email_code.setText("012345")
                dialog.email_code.returnPressed.emit()
                self.assertTrue(wait_for(lambda: "Почта подтверждена" in dialog.status.text()))
                self.assertIs(dialog.pages.currentWidget(), dialog.confirm)
                self.assertEqual(server.upload_count, 0)
                self.assertTrue(server.confirmed)
                dialog.yes_button.click()
                self.assertTrue(wait_for(lambda: "SQL Editor" in dialog.status.text()))
                self.assertEqual(server.upload_count, 0)
                server.missing_schema = False
                dialog.yes_button.click()
                self.assertTrue(wait_for(lambda: "HTTP 500" in dialog.status.text()))
                self.assertEqual(baseline(STORE), {})
                self.assertEqual(len(STORE.albums), 1)

                server.fail_upload = False
                dialog._show_confirm()
                dialog.yes_button.click()
                self.assertTrue(wait_for(lambda: "Данные загружены" in dialog.status.text()))
                self.assertEqual(server.upload_count, 1)
                self.assertEqual(set(kind for kind, _ in server.items), {"album", "artist", "rating"})
                self.assertEqual(len(server.images), 1)
                own_rating = f"{album.cloud_id}:{USER_ID}"
                self.assertEqual(list(server.items["rating", own_rating]["payload"]["scores"].values()), [8.5])
                self.assertEqual(server.items["rating", own_rating]["payload"]["name"], "Участник")
                self.assertNotIn("photo", server.items["artist", "Исполнитель"]["payload"])
                self.assertNotIn("password", json.dumps(list(server.items.values())))
                self.assertEqual(len(STORE.albums), 1)

                dialog._show_confirm()
                dialog.yes_button.click()
                self.assertTrue(wait_for(lambda: "Нет данных" in dialog.status.text()))
                self.assertEqual(server.upload_count, 1)

                dialog.reject()
                self.assertTrue(wait_for(window.top_bar.cloud_button.isEnabled))
                window.top_bar.cloud_button.click()
                self.assertTrue(wait_for(lambda: not dialog.isVisible() and not window.top_bar.cloud_button.isEnabled()))
                album = STORE.albums[0]
                self.assertEqual(album.ratings.rater_ids, [USER_ID])

                # Same release created independently on another PC, with a different local ID.
                second_session = CloudSession(OTHER_ID, OTHER_TOKEN)
                second_album = replace(deepcopy(album), id="separate-local-id", cloud_id="", ratings=None, rating=None)
                second_store = SimpleNamespace(albums=[second_album], artists=STORE.artists, resolve=STORE.resolve)
                second_ratings = replace(album.ratings, rater_names=["Володя"], rater_ids=[OTHER_ID], values=[[7]])
                second_album.ratings = second_ratings
                state = dialog._cloud.shared_status(second_session, download=True)
                pending, _, _, _ = upload_plan(second_store, state, {})
                self.assertEqual([item.kind for item in pending], ["rating"])
                dialog._cloud.shared_upload(second_session, pending)
                self.assertEqual(sum(kind == "rating" for kind, _ in server.items), 2)
                self.assertIn(("rating", own_rating), server.items)

                self.assertTrue(wait_for(lambda: not dialog._polling))
                dialog.poll()
                self.assertTrue(wait_for(window.top_bar.cloud_button.isEnabled))
                window.top_bar.cloud_button.click()
                self.assertTrue(wait_for(lambda: not dialog.isVisible() and not window.top_bar.cloud_button.isEnabled()))
                album = STORE.albums[0]
                self.assertEqual(dict(zip(album.ratings.rater_ids, album.ratings.values[0])), {USER_ID: 8.5, OTHER_ID: 7})
                self.assertEqual(MusicStore().albums[0].ratings.rater_ids, album.ratings.rater_ids)

                window.open_rate_album(album)
                wizard = window._rate_overlay
                self.assertEqual(set(wizard.rater_buttons), set(MEMBERS))
                wizard.rater_buttons[USER_ID].click()
                wizard.go_to_step(1)
                self.assertEqual(wizard._values, [[8.5]])
                wizard._cells[0][0].setText("9")
                wizard._finish()
                self.assertEqual(dict(zip(album.ratings.rater_ids, album.ratings.values[0])), {USER_ID: 9.0, OTHER_ID: 7})

                dialog.open()
                dialog.preview_button.click()
                self.assertTrue(wait_for(lambda: dialog.pages.currentWidget() is dialog.preview))
                self.assertEqual([dialog.tree.topLevelItem(i).childCount() for i in range(3)], [0, 0, 1])
                dialog.preview_upload_button.click()
                self.assertTrue(wait_for(lambda: "Данные загружены" in dialog.status.text()))
                self.assertEqual(list(server.items["rating", own_rating]["payload"]["scores"].values()), [9])
                self.assertEqual(list(server.items["rating", f"{album.cloud_id}:{OTHER_ID}"]["payload"]["scores"].values()), [7])
                state = dialog._cloud.shared_status(second_session, download=True)
                clean = SimpleNamespace(albums=[], artists=[], resolve=STORE.resolve)
                restored, artists, _, skipped = download_plan(dialog._cloud, second_session, clean, state, {})
                self.assertEqual((len(restored), len(artists), skipped), (1, 1, 0))
                self.assertEqual(STORE.resolve(restored[0].cover_path).read_bytes(), b"fixture image")
                self.assertEqual(dict(zip(restored[0].ratings.rater_ids, restored[0].ratings.values[0])),
                                 {USER_ID: 9, OTHER_ID: 7})
                # A stale PC must not re-upload a column which hasn't changed locally.
                second_album.ratings = replace(album.ratings, rater_names=["Участник"], rater_ids=[USER_ID], values=[[8.5]])
                old_state = {**state, "shared": [row if row["item_id"] != own_rating else
                    {**row, "payload": {**row["payload"], "scores": {key: 8.5 for key in row["payload"]["scores"]}}}
                    for row in state["shared"]]}
                _, prior, _, _ = upload_plan(second_store, old_state, {})
                stale, _, _, _ = upload_plan(second_store, state, prior)
                self.assertEqual(stale, [])

                if sys.platform == "win32":
                    reopened = MainWindow()
                    try:
                        reopened._cloud_upload._cloud = dialog._cloud
                        reopened._cloud_upload.start_monitoring()
                        self.assertTrue(wait_for(reopened.top_bar.cloud_button.isEnabled))
                        self.assertEqual(server.refreshes, 1)
                        settings = reopened._cloud_upload._settings
                        self.assertNotIn(REFRESH_TOKEN, settings.value(reopened._cloud_upload._profile_key, ""))
                    finally:
                        reopened.close()
            finally:
                window.close()
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
