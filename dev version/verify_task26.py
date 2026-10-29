"""Задача 26: Spotify как второй источник автозаполнения.

Мок-серверы Spotify и Deezer на 127.0.0.1 + проверки сервиса и UI:
  • resolve ссылок Spotify (обычная/intl/URI/короткая редиректом/
    короткая через тело страницы/чужой хост);
  • fetch_album: маппинг полей, обложка, фото артистов, жанр,
    пагинация треков, префикс source_id;
  • ключи: нет ключей, неверные ключи (400 invalid_client), env-ключи,
    сохранение в файл через диалог;
  • окно «Создание альбома»: ключи-страница при ссылке Spotify без
    ключей; сохранение ключей → автозагрузка; диспетчеризация Deezer;
    неизвестный хост; защита от дублей;
  • мастер: apply_auto_fill(SpotifyAlbum) — поля/метки/source_id;
  • страница альбома: строка источника с лого Spotify/Deezer/вручную.

Запускается в ИЗОЛИРОВАННОЙ КОПИИ проекта (data/ создаётся заново).
"""
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

os.environ["MUSICRATING_SPOTIFY_API"] = ""       # заполним после старта сервера
os.environ["MUSICRATING_SPOTIFY_TOKEN_URL"] = ""

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

app = QApplication([])

from app.models import AlbumDraft  # noqa: E402
from app.services import deezer, spotify  # noqa: E402
from app.store import STORE  # noqa: E402
from app.ui.dialogs.create_choice_dialog import (  # noqa: E402
    NOT_LINK_MSG,
    CreateChoiceOverlay,
    detect_provider,
)
from app.ui.pages.album_detail import AlbumDetailPage  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, name: str) -> None:
    RESULTS.append((bool(cond), name))
    print(("OK  " if cond else "FAIL"), name)


# ---------------------------------------------------------------------------
# Мок-сервер: /api/token и /v1/... — Spotify; /album/... — Deezer;
# /img/... — картинки для обоих; /short/... — короткие ссылки Spotify
# ---------------------------------------------------------------------------
PORT = 8975
TOKEN = "TESTTOKEN"
GOOD_BASIC = None


class FakeHandler(BaseHTTPRequestHandler):

    def log_message(self, *_args):  # тишина в логах
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _img(self) -> None:
        body = b"\xff\xd8\xff\xe0FAKEJPEG"
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/img/"):
            return self._img()
        if path.startswith("/v1/albums/"):
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._json(
                    {"error": {"status": 401, "message": "No token"}}, 401)
            album_id = path.split("/v1/albums/")[1].strip("/")
            if album_id == "ALBUM1":
                return self._json({
                    "name": "Тестовый альбом",
                    "release_date": "1999-05-01",
                    "genres": [],
                    "images": [
                        {"url": f"http://127.0.0.1:{PORT}/img/cover_big.jpg",
                         "width": 640},
                        {"url": f"http://127.0.0.1:{PORT}/img/cover_small.jpg",
                         "width": 64},
                    ],
                    "artists": [{"name": "Тест Артист", "id": "AR1"}],
                    "tracks": {"items": [
                        {"name": "Трек один", "artists": [
                            {"name": "Тест Артист", "id": "AR1"}]},
                        {"name": "Трек два", "artists": [
                            {"name": "Тест Артист", "id": "AR1"},
                            {"name": "Фит Гость", "id": "AR2"}]},
                    ], "next": None},
                })
            if album_id == "BIGALB":
                return self._json({
                    "name": "Большой альбом", "release_date": "2001",
                    "images": [],
                    "artists": [{"name": "Тест Артист", "id": "AR1"}],
                    "tracks": {"items": [
                        {"name": "Страница 1 — трек А", "artists": []},
                        {"name": "Страница 1 — трек Б", "artists": []},
                    ], "next": f"http://127.0.0.1:{PORT}/v1/albums/BIGALB/page2"},
                })
            if album_id == "BIGALB/page2":
                return self._json({
                    "items": [{"name": "Страница 2 — трек В", "artists": []}],
                    "next": None,
                })
            if album_id == "GENREALB":
                return self._json({
                    "name": "Жанровый альбом", "release_date": "1974-03-15",
                    "genres": ["Rock"], "images": [],
                    "artists": [{"name": "Тест Артист", "id": "AR1"}],
                    "tracks": {"items": [], "next": None},
                })
            return self._json(
                {"error": {"status": 404, "message": "not found"}}, 404)
        if path.startswith("/v1/artists/"):
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._json(
                    {"error": {"status": 401, "message": "No token"}}, 401)
            artist_id = path.split("/v1/artists/")[1].strip("/")
            name = "Тест Артист" if artist_id == "AR1" else "Фит Гость"
            return self._json({
                "id": artist_id, "name": name,
                "images": [{"url": f"http://127.0.0.1:{PORT}/img/{artist_id}.jpg",
                            "width": 640}],
            })
        if path.startswith("/album/"):          # Deezer
            album_id = path.split("/album/")[1].strip("/")
            if album_id == "1987":
                return self._json({
                    "title": "Дизер Альбом", "release_date": "2001-01-01",
                    "cover_big": f"http://127.0.0.1:{PORT}/img/dcover.jpg",
                    "genres": {"data": [{"name": "Rock"}]},
                    "contributors": [
                        {"name": "Дизер Артист",
                         "picture_xl": f"http://127.0.0.1:{PORT}/img/dar.jpg"}],
                    "tracks": {"data": [
                        {"title": "ДТрек 1", "contributors": [
                            {"name": "Дизер Артист",
                             "picture_xl": f"http://127.0.0.1:{PORT}/img/dar.jpg"},
                            {"name": "ДГость",
                             "picture_xl": f"http://127.0.0.1:{PORT}/img/dg.jpg"}]},
                        {"title": "ДТрек 2", "contributors": [
                            {"name": "Дизер Артист",
                             "picture_xl": f"http://127.0.0.1:{PORT}/img/dar.jpg"}]},
                    ]},
                })
            return self._json(
                {"error": {"type": "DataException", "message": "no data"}})
        if path == "/short/redirect":           # короткая ссылка Spotify
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{PORT}/album/SHORT1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if path == "/short/html":               # фолбэк: адрес в теле HTML
            body = (
                '<html><script>window.location="'
                'http://open.spotify.com/album/BODY1?si=x"</script></html>'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return self._json({"error": {"status": 404, "message": "no route"}}, 404)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path == "/api/token":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            auth = self.headers.get("Authorization") or ""
            if "grant_type=client_credentials" not in raw:
                return self._json({"error": "unsupported_grant_type"}, 400)
            if auth != GOOD_BASIC:
                return self._json({"error": "invalid_client"}, 400)
            return self._json({"access_token": TOKEN, "token_type": "Bearer",
                               "expires_in": 3600})
        return self._json({"error": "not found"}, 404)


server = ThreadingHTTPServer(("127.0.0.1", PORT), FakeHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()

CLIENT_ID = "testid123"
CLIENT_SECRET = "testsecret456"
GOOD_BASIC = "Basic " + base64.b64encode(
    f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
).decode()

BASE = f"http://127.0.0.1:{PORT}"
CREDS_FILE = HERE / "data" / "spotify_credentials.json"
os.environ["MUSICRATING_SPOTIFY_API"] = BASE
os.environ["MUSICRATING_SPOTIFY_TOKEN_URL"] = f"{BASE}/api/token"
os.environ["MUSICRATING_SPOTIFY_CREDENTIALS"] = str(CREDS_FILE)
# модуль читает адреса при импорте — перезаписать после старта сервера
spotify.API_BASE = BASE
spotify.TOKEN_URL = f"{BASE}/api/token"
deezer.API_BASE = BASE

if CREDS_FILE.exists():
    CREDS_FILE.unlink()
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_ID", None)
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_SECRET", None)

# ---------------------------------------------------------------------------
# 1. detect_provider (без сети)
# ---------------------------------------------------------------------------
check(detect_provider("https://www.deezer.com/album/123") == "deezer",
      "detect: deezer.com")
check(detect_provider("https://link.deezer.com/abc") == "deezer",
      "detect: link.deezer.com")
check(detect_provider("https://open.spotify.com/album/ABC") == "spotify",
      "detect: open.spotify.com")
check(detect_provider("https://spotify.link/xyz") == "spotify",
      "detect: spotify.link")
check(detect_provider("spotify:album:ABC") == "spotify", "detect: spotify: URI")
check(detect_provider("https://youtube.com/x") == "ytmusic",
      "detect: youtube.com → ytmusic (с Task 27)")
check(detect_provider("https://example.com/album/1") == "",
      "detect: чужой хост")
check(detect_provider("") == "", "detect: пусто")

# ---------------------------------------------------------------------------
# 2. resolve_album_id (мок)
# ---------------------------------------------------------------------------
try:
    spotify.resolve_album_id("")
    check(False, "resolve: пустая строка → ошибка")
except spotify.SpotifyError:
    check(True, "resolve: пустая строка → ошибка")
try:
    spotify.resolve_album_id("https://youtube.com/watch?v=1")
    check(False, "resolve: чужой хост → ошибка")
except spotify.SpotifyError:
    check(True, "resolve: чужой хост → ошибка")
check(spotify.resolve_album_id(
    "https://open.spotify.com/album/ALBUM1?si=x") == "ALBUM1",
    "resolve: обычная ссылка")
check(spotify.resolve_album_id(
    "open.spotify.com/intl-ru/album/ALBUM1") == "ALBUM1",
    "resolve: intl без схемы")
check(spotify.resolve_album_id("spotify:album:ALBUM1") == "ALBUM1",
      "resolve: URI")
# Короткие ссылки: сначала механика редиректа (реальный QNAM + 302),
# затем диспетчеризация хоста spotify.link (сетевая функция подменена
# — реальный хост spotify.link из песочницы не направить на мок)
_, final_url = spotify._get_bytes(
    f"http://127.0.0.1:{PORT}/short/redirect", browser_ua=True)
check(final_url.endswith("/album/SHORT1"),
      "resolve: короткая — QNAM идёт по редиректу")
html, _ = spotify._get_bytes(
    f"http://127.0.0.1:{PORT}/short/html", browser_ua=True)
check(b"album/BODY1" in html, "resolve: тело короткой страницы содержит адрес")

_original_short = spotify._resolve_short_link
spotify._resolve_short_link = lambda url: (f"{BASE}/album/SHORT1", b"")
check(spotify.resolve_album_id("https://spotify.link/AbCdEf") == "SHORT1",
      "resolve: короткая редиректом")
spotify._resolve_short_link = lambda url: (
    "https://open.spotify.com/",
    b'<script>window.location="https://open.spotify.com/album/BODY1"</script>',
)
check(spotify.resolve_album_id("https://spotify.app.link/AbCdEf") == "BODY1",
      "resolve: короткая через тело HTML")
spotify._resolve_short_link = _original_short

# ---------------------------------------------------------------------------
# 3. Ключи: нет ключей → понятный текст
# ---------------------------------------------------------------------------
try:
    spotify.load_album_from_link("https://open.spotify.com/album/ALBUM1")
    check(False, "ключи: без ключей → SpotifyError")
except spotify.SpotifyError as exc:
    check(str(exc) == spotify.NO_CREDENTIALS_MSG,
          "ключи: без ключей — понятный текст")

# Неверные ключи → invalid_client
os.environ["MUSICRATING_SPOTIFY_CLIENT_ID"] = "wrong"
os.environ["MUSICRATING_SPOTIFY_CLIENT_SECRET"] = "wrong"
try:
    spotify.invalidate_token()
    spotify.load_album_from_link("https://open.spotify.com/album/ALBUM1")
    check(False, "ключи: неверные → SpotifyError")
except spotify.SpotifyError as exc:
    check(str(exc) == spotify.BAD_CREDENTIALS_MSG,
          "ключи: invalid_client — понятный текст")

# Правильные ключи через env → загрузка работает
os.environ["MUSICRATING_SPOTIFY_CLIENT_ID"] = CLIENT_ID
os.environ["MUSICRATING_SPOTIFY_CLIENT_SECRET"] = CLIENT_SECRET
spotify.invalidate_token()

# ---------------------------------------------------------------------------
# 4. fetch_album (мок): маппинг, фото, префикс, жанр, пагинация
# ---------------------------------------------------------------------------
album = spotify.fetch_album("ALBUM1")
check(album.title == "Тестовый альбом", "fetch: название")
check(album.year == "1999", "fetch: год из release_date")
check(album.genre == "", "fetch: жанр пустой (Spotify не отдаёт)")
check(album.artist_names == ["Тест Артист"], "fetch: артисты альбома")
check(album.cover_url == f"http://127.0.0.1:{PORT}/img/cover_big.jpg",
      "fetch: выбрана самая крупная обложка")
check(album.album_id == "spotify:ALBUM1", "fetch: префикс source_id")
check([t.title for t in album.tracks] == ["Трек один", "Трек два"],
      "fetch: треки")
check(album.tracks[1].artists == ["Тест Артист", "Фит Гость"],
      "fetch: фиты трека")
check(album.photos.get("Тест Артист", "").endswith("/img/AR1.jpg"),
      "fetch: фото главного")
check(album.photos.get("Фит Гость", "").endswith("/img/AR2.jpg"),
      "fetch: фото фита")
check(album.download_image(album.cover_url) is not None,
      "fetch: обложка скачана")

big = spotify.fetch_album("BIGALB")
check([t.title for t in big.tracks] == [
    "Страница 1 — трек А", "Страница 1 — трек Б", "Страница 2 — трек В"],
    "fetch: пагинация треков (2 страницы)")
check(big.tracks[0].artists == ["Тест Артист"],
      "fetch: трек без артистов → главный")

genre_album = spotify.fetch_album("GENREALB")
check(genre_album.genre == "Рок", "fetch: жанр Rock → Рок")

# ---------------------------------------------------------------------------
# 5. Диалог «Создание альбома»: ключи-страница и диспетчеризация
# ---------------------------------------------------------------------------
holder = QWidget()
holder.resize(900, 600)
holder.show()
QTest.qWait(50)

results: list[object] = []
overlay = CreateChoiceOverlay(holder)
overlay.setGeometry(holder.rect())
overlay.album_loaded.connect(results.append)

# Оповещения — тосты (Task 31): помощник чтения последнего тоста
from app.ui.widgets.toast import manager_for

def last_toast():
    active = manager_for(holder).active
    return active[0] if active else None


# 5.1 Ссылка Spotify без ключей (env убраны) → страница ключей
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_ID", None)
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_SECRET", None)
spotify.invalidate_token()
overlay.open()
overlay.input_link.setText("https://open.spotify.com/album/ALBUM1?si=x")
overlay._try_load()
check(overlay.pages.currentIndex() == 2,
      "окно: ссылка Spotify без ключей → страница ключей")
check(not overlay.lbl_status.isVisible(), "окно: статус загрузки скрыт")
check(overlay.btn_keys_save.isEnabled() is False,
      "окно: «Сохранить и загрузить» неактивна при пустых полях")

# 5.2 Сохранение ключей → автозагрузка
overlay.input_client_id.setText(CLIENT_ID)
overlay.input_client_secret.setText(CLIENT_SECRET)
overlay._save_keys_and_load()
check(len(results) == 1, "окно: после сохранения ключей альбом загрузился")
if results:
    loaded = results[0]
    check(type(loaded).__name__ == "SpotifyAlbum", "окно: сигнал несёт SpotifyAlbum")
    check(loaded.album_id == "spotify:ALBUM1", "окно: source_id с префиксом")
check(CREDS_FILE.exists(), "окно: файл ключей создан")
saved = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
check(saved == {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                "proxy": ""},
      "окно: в файле ключей — id, secret и пустой прокси")

# 5.3 Повторная загрузка по сохранённым ключам (без env)
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://open.spotify.com/album/ALBUM1")
overlay._try_load()
check(len(results) == 2, "окно: повторная загрузка по сохранённым ключам")

# 5.4 Неверные ключи → страница ключей с ошибкой
CREDS_FILE.write_text(json.dumps({"client_id": "bad", "client_secret": "bad"}),
                      encoding="utf-8")
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_ID", None)
os.environ.pop("MUSICRATING_SPOTIFY_CLIENT_SECRET", None)
spotify.invalidate_token()
overlay.open()
overlay.input_link.setText("open.spotify.com/album/ALBUM1")
overlay._try_load()
check(overlay.pages.currentIndex() == 2, "окно: неверные ключи → страница ключей")
_t = last_toast()
check(_t is not None and _t.text == spotify.BAD_CREDENTIALS_MSG,
      "окно: текст invalid_client показан тостом (Task 31)")
check(overlay.input_client_id.text() == "bad",
      "окно: неверные ключи подставлены для правки")
overlay.handle_escape()
check(overlay.pages.currentIndex() == 1,
      "окно: Esc со страницы ключей → назад к ссылке")

# 5.5 Deezer-ссылка через диспетчеризацию
os.environ["MUSICRATING_SPOTIFY_CLIENT_ID"] = CLIENT_ID
os.environ["MUSICRATING_SPOTIFY_CLIENT_SECRET"] = CLIENT_SECRET
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://www.deezer.com/album/1987")
overlay._try_load()
check(len(results) == 3, "окно: deezer-ссылка загрузилась")
if len(results) == 3:
    check(type(results[2]).__name__ == "DeezerAlbum",
          "окно: сигнал несёт DeezerAlbum")
    check(results[2].album_id == "1987", "окно: у Deezer source_id без префикса")
    check(results[2].genre == "Рок", "окно: жанр Deezer смаппирован")

# 5.6 Неизвестный хост → красная подсказка (youtube.com с Task 27 —
# провайдер ytmusic, поэтому «чужой» теперь другой)
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://example.com/album/1")
overlay._try_load()
_t = last_toast()
check(_t is not None and _t.text == NOT_LINK_MSG,
      "окно: чужой хост — общий текст «не ссылка на альбом» (тост)")

# 5.7 Защита от дублей (source_id Spotify)
draft = AlbumDraft()
draft.title = "Тестовый альбом"
draft.source_id = "spotify:ALBUM1"
STORE.add_album(draft)
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://open.spotify.com/album/ALBUM1")
overlay._try_load()
_t = last_toast()
check(_t is not None
      and _t.text == "Кажется, этот альбом уже создан.",
      "окно: ссылка уже созданного альбома — тост (Task 31)")
check(overlay.btn_load.isEnabled() is False,
      "окно: «Загрузить» заблокирована для дубля")

# ---------------------------------------------------------------------------
# 6. Мастер: apply_auto_fill(SpotifyAlbum)
# ---------------------------------------------------------------------------
from app.ui.pages.create_album import CreateAlbumOverlay  # noqa: E402

master = CreateAlbumOverlay(holder)
master.setGeometry(holder.rect())
master.reset()
master.apply_auto_fill(spotify.fetch_album("ALBUM1"))
check(master.input_title.text() == "Тестовый альбом", "мастер: название")
check(master.input_year.text() == "1999", "мастер: год")
check(len(master.draft.tracks) == 2, "мастер: треки заполнены")
check(len(master.draft.artists) == 1,
      "мастер: исполнители альбома в черновике (фит — в базе, в треках)")
check(master.draft.source_id == "spotify:ALBUM1", "мастер: source_id черновика")
check(master.badge_title.property("mark") == "ok", "мастер: жёлтая метка названия")
check(master.badge_region.property("mark") == "bad", "мастер: красная метка региона")
check(master._auto_filled is True, "мастер: флаг автозаполнения")

# ---------------------------------------------------------------------------
# 7. Строка источника на странице альбома
# ---------------------------------------------------------------------------
page = AlbumDetailPage(holder)
page.setGeometry(holder.rect())
page.show()
QTest.qWait(50)
albums = {a.title: a for a in STORE.albums}
stored_album = albums["Тестовый альбом"]
check(stored_album.source_id == "spotify:ALBUM1",
      "страница: у альбома source_id Spotify")
page.set_album(stored_album)
check(page.lbl_source.text() == "Создано с помощью",
      "страница: текст «Создано с помощью»")
check(page.source_icon.isVisible() and not page.source_icon.pixmap().isNull(),
      "страница: лого Spotify показан")

stored_album.source_id = "D1"      # как у Deezer — числовой id без префикса
page.set_album(stored_album)
check(page.source_icon.isVisible() and not page.source_icon.pixmap().isNull(),
      "страница: лого Deezer показан")

stored_album.source_id = ""
page.set_album(stored_album)
check(page.lbl_source.text() == "Создано вручную"
      and not page.source_icon.isVisible(),
      "страница: ручной альбом — без лого")

# ---------------------------------------------------------------------------
# Итог
# ---------------------------------------------------------------------------
failed = [name for ok, name in RESULTS if not ok]
print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} проверок пройдено ===")
if failed:
    print("ПРОВАЛЫ:")
    for name in failed:
        print(" -", name)
    sys.exit(1)
