"""Задача 38: Яндекс Музыка — источник автозаполнения альбома.

Покрывает:
  1. detect_provider: music.yandex.ru|by|kz|uz|com → «yandex»;
     прочие хосты Яндекса (disk.yandex.ru, mail.yandex.ru, yandex.ru)
     и прежние провайдеры не сломаны; неизвестный хост → «».
  2. resolve_album_id: ссылки на альбом (с utm-параметрами, без
     схемы, региональные домены, с хвостовым слэшем), ссылка на
     трек /album/<id>/track/<tid> → альбом, голый числовой id;
     плейлисты, исполнители, чужие домены, пустая строка → ошибки
     с понятным текстом.
  3. fetch_album через мок (MUSICRATING_YANDEX_API): название,
     год, жанр (rock → Рок, общий словарь с Deezer), обложка
     (плейсхолдер %%size%% → 400x400), исполнители альбома,
     8 треков с ПОЛНЫМИ списками исполнителей (главный + фиты),
     дедуп повторов, «версия» издания в скобках у трека, фолбэк
     на исполнителей альбома у трека без артистов, album_id
     «yandex:<id>».
  4. Альбом с версией издания («Deluxe») — дописывается к
     названию; без жанра/года → пустые поля.
  5. Ошибки: подкаст → внятная ошибка; 404 → «не нашла такой
     альбом»; 451 → гео-сообщение (не зарубежный VPN не мешает);
     мусорный JSON → «неожиданный ответ»; мёртвый порт → «нет
     соединения».
  6. download_image: обложка сохраняется в data/covers (функцией
     и методом альбома); битая ссылка → None без исключений.
  7. Заголовок клиента X-Yandex-Music-Client доходит до сервера
     во всех запросах к API.
  8. Диалог: подпись упоминает Яндекс Музыку; ссылка → альбом
     загружен → мастер заполнен (название/год/жанр/исполнители/
     треки/source_id/обложка с мока).
  9. Защита от повторной загрузки («Кажется, этот альбом уже
     создан»).
 10. Страница альбома с source_id «yandex:…» → «Создано с
     помощью» + логотип Яндекс Музыки.

ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
"""

import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CANDIDATES = [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[1],
    Path("/home/z/my-project/music-rating-app"),
]
APP = next(c for c in _CANDIDATES if (c / "app" / "theme.py").exists())
sys.path.insert(0, str(APP))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(APP):
    raise SystemExit("Run this check through checks/run.py.")

DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

app = QApplication([])
app.setApplicationName("Music Rating")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))

import app.theme as theme

theme.apply_theme(app)

import app.services.backfill as bf
from PySide6.QtCore import QObject, Signal


class _StubBackfiller(QObject):
    changed = Signal()

    def __init__(self, *a, **k) -> None:
        super().__init__()

    def start(self) -> None:
        pass


bf.ArtBackfiller = _StubBackfiller

# --- Мок-сервер API Яндекс Музыки (до импорта app.services.yandex_music!) --
FAKE_COVER = b"\x89PNG-fake-yandex-cover-bytes"
API_HITS: list[str] = []       # пути всех запросов к API
LAST_CLIENT: list[str] = []    # заголовки X-Yandex-Music-Client


def _artist(entry_id: int, name: str) -> dict:
    return {"id": entry_id, "name": name}


def _album_full(base: str) -> dict:
    """Альбом «Группа крови» (id 130644) — как отдаёт настоящий API."""
    kino = _artist(1306, "Кино")
    return {
        "invocationInfo": {"req-id": "mock-1", "hostname": "mock"},
        "result": {
            "id": 130644,
            "type": "album",
            "title": "Группа крови",
            "version": None,
            "year": 1988,
            "genre": "rock",
            "coverUri": f"{base}/covers/kino/%%size%%",
            "ogImage": f"{base}/covers/kino/%%size%%",
            "available": True,
            "artists": [kino],
            "tracks": [
                {"id": 1001, "title": "Группа крови", "durationMs": 284000,
                 "version": None, "artists": [kino]},
                {"id": 1002, "title": "Закрой за мной дверь, я ухожу",
                 "artists": [kino, _artist(7, "Гость")]},
                {"id": 1003, "title": "В наших глазах",
                 "artists": [kino, _artist(7, "Гость")]},
                # дубль исполнителя в списке + версия трека
                {"id": 1004, "title": "Попробуй спеть вместе со мной",
                 "version": "Remix",
                 "artists": [kino, _artist(8, "Роберт"), kino]},
                # трек вовсе без исполнителей → фолбэк на альбомных
                {"id": 1005, "title": "Легенда", "artists": []},
                {"id": 1006, "title": "Спокойная ночь", "artists": [kino]},
                {"id": 1007, "title": "Мама, мы все тяжело больны",
                 "artists": [kino, _artist(9, "Гость 2")]},
                {"id": 1008, "title": "Бошетунмай", "artists": [kino]},
            ],
        },
    }


def _album_deluxe() -> dict:
    """Альбом с версией издания, без жанра и года."""
    return {
        "result": {
            "id": 555,
            "type": "album",
            "title": "Ночь",
            "version": "Deluxe Edition",
            "year": 2020,
            "artists": [_artist(1, "Кино")],
            "tracks": [
                {"id": 2001, "title": "Весна", "version": "Live",
                 "artists": [_artist(1, "Кино")]},
            ],
        },
    }


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # тишина в выводе
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/albums/") and path.endswith("/with-tracks"):
            API_HITS.append(path)
            LAST_CLIENT.append(
                self.headers.get("X-Yandex-Music-Client") or ""
            )
            album_id = path.split("/")[2]
            base = f"http://127.0.0.1:{MOCK_PORT}"
            if album_id == "130644":
                self._send_json(_album_full(base))
            elif album_id == "555":
                self._send_json(_album_deluxe())
            elif album_id == "111":
                self._send_json({
                    "result": {
                        "id": 111, "type": "podcast", "title": "Подкаст",
                        "artists": [], "tracks": [],
                    }
                })
            elif album_id == "222":
                self._send_json(
                    {"error": {"name": "not-found",
                               "message": "Requested action was not found"}},
                    status=404,
                )
            elif album_id == "333":
                self._send_json(
                    {"error": {"name": "Unavailable For Legal Reasons",
                               "message": ""}},
                    status=451,
                )
            elif album_id == "444":
                body = "это точно не JSON".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send_json(
                    {"error": {"name": "not-found", "message": ""}},
                    status=404,
                )
            return
        if path == "/covers/kino/400x400":
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(FAKE_COVER)))
            self.end_headers()
            self.wfile.write(FAKE_COVER)
            return
        self.send_response(404)
        self.end_headers()


_server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
MOCK_PORT = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()

os.environ["MUSICRATING_YANDEX_API"] = f"http://127.0.0.1:{MOCK_PORT}"

import app.services.yandex_music as ym
from app.services.yandex_music import (
    YandexMusicAlbum,
    YandexMusicError,
    YandexMusicTrack,
)
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay, detect_provider
from app.ui.pages.album_detail import YANDEX_LOGO_PATH

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


def _error_of(text: str) -> str:
    try:
        ym.load_album_from_link(text)
    except YandexMusicError as exc:
        return str(exc)
    return "<нет ошибки>"


# --- Данные: аккаунт (после стирания data/ — демо-библиотека) -------------
from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.store import STORE
from checks.fixtures.library import populate_library

populate_library(STORE)


from app.ui.main_window import MainWindow

win = MainWindow()
win.resize(1200, 800)
win.show()
QTest.qWait(200)

# ============================================================
print("--- 1. detect_provider ---")
check("music.yandex.ru → yandex",
      detect_provider("https://music.yandex.ru/album/130644") == "yandex")
check("music.yandex.by → yandex",
      detect_provider("https://music.yandex.by/album/130644") == "yandex")
check("music.yandex.kz → yandex",
      detect_provider("https://music.yandex.kz/album/1?t=x") == "yandex")
check("music.yandex.uz → yandex",
      detect_provider("https://music.yandex.uz/album/1") == "yandex")
check("music.yandex.com → yandex",
      detect_provider("https://music.yandex.com/album/1") == "yandex")
check("без схемы", detect_provider("music.yandex.ru/album/1") == "yandex")
check("disk.yandex.ru — не музыка",
      detect_provider("https://disk.yandex.ru/d/abc") == "")
check("mail.yandex.ru — не музыка",
      detect_provider("https://mail.yandex.ru/") == "")
check("голый yandex.ru — не музыка",
      detect_provider("https://yandex.ru/search?q=x") == "")
check("deezer не сломан", detect_provider("https://www.deezer.com/album/123") == "deezer")
check("spotify не сломан",
      detect_provider("https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv") == "spotify")
check("youtube не сломан",
      detect_provider("https://music.youtube.com/playlist?list=OLAK5uy_k") == "ytmusic")
check("genius не сломан",
      detect_provider("https://genius.com/albums/Kino/Gruppa-krovi") == "genius")
check("чужой домен", detect_provider("https://example.com/album/1") == "")
check("пустая строка", detect_provider("   ") == "")

# ============================================================
print("--- 2. resolve_album_id ---")
check("обычная ссылка",
      ym.resolve_album_id("https://music.yandex.ru/album/130644") == "130644")
check("с utm-параметрами",
      ym.resolve_album_id(
          "https://music.yandex.ru/album/130644?utm_source=desktop&utm_medium=share")
      == "130644")
check("без схемы",
      ym.resolve_album_id("music.yandex.ru/album/130644") == "130644")
check("ссылка на трек → альбом",
      ym.resolve_album_id("https://music.yandex.ru/album/130644/track/926957")
      == "130644")
check("региональный домен .kz",
      ym.resolve_album_id("https://music.yandex.kz/album/777") == "777")
check("хвостовой слэш",
      ym.resolve_album_id("https://music.yandex.ru/album/130644/") == "130644")
check("голый числовой id", ym.resolve_album_id("130644") == "130644")


def _not_album(text: str, message: str = ym.NOT_ALBUM_MSG) -> bool:
    try:
        ym.resolve_album_id(text)
    except YandexMusicError as exc:
        return str(exc) == message
    return False


check("пустая строка → «Вставьте ссылку…»",
      _not_album("", "Вставьте ссылку на альбом Яндекс Музыки."))
check("плейлист → не альбом",
      _not_album("https://music.yandex.ru/users/yamusic-admin/playlists/2509897"))
check("исполнитель → не альбом",
      _not_album("https://music.yandex.ru/artist/130606"))
check("главная без альбома → не альбом",
      _not_album("https://music.yandex.ru/"))
check("чужой домен → не альбом",
      _not_album("https://www.deezer.com/album/123"))
check("почта Яндекса → не альбом",
      _not_album("https://mail.yandex.ru/album/123"))
check("не число в fetch_album → не альбом",
      _not_album("abc"))


def _fetch_error(album_id: str) -> str:
    try:
        ym.fetch_album(album_id)
    except YandexMusicError as exc:
        return str(exc)
    return "<нет ошибки>"


check("fetch_album('abc') — текст «не ссылка на альбом»",
      _fetch_error("abc") == ym.NOT_ALBUM_MSG)

# ============================================================
print("--- 3. fetch_album через мок ---")
album = ym.fetch_album("130644")
check("название", album.title == "Группа крови")
check("год", album.year == "1988")
check("жанр rock → Рок (словарь Deezer)", album.genre == "Рок")
check("обложка: %%size%% → 400x400",
      album.cover_url == f"http://127.0.0.1:{MOCK_PORT}/covers/kino/400x400")
check("исполнители альбома", album.artist_names == ["Кино"])
check("8 треков", len(album.tracks) == 8)
check("трек 1: исполнители",
      album.tracks[0].title == "Группа крови"
      and album.tracks[0].artists == ["Кино"])
reply = ym.request_playback_album("130644")
loop = QEventLoop()
reply.finished.connect(loop.quit)
if not reply.isFinished():
    loop.exec()
playback_album = ym.read_playback_album(reply, "130644")
check("асинхронный запрос сохраняет ID трека и длительность",
      playback_album.tracks[0].track_id == "1001"
      and playback_album.tracks[0].duration_ms == 284000)
check("трек 2: фит в списке",
      album.tracks[1].artists == ["Кино", "Гость"])
check("трек 4: версия в скобках + дубль исполнителя убран",
      album.tracks[3].title == "Попробуй спеть вместе со мной (Remix)"
      and album.tracks[3].artists == ["Кино", "Роберт"])
check("трек без исполнителей → фолбэк на альбомных",
      album.tracks[4].title == "Легенда"
      and album.tracks[4].artists == ["Кино"])
check("трек 7: второй фит",
      album.tracks[6].artists == ["Кино", "Гость 2"])
check("album_id «yandex:<id>»", album.album_id == "yandex:130644")
check("фото исполнителей в ответе нет (дозагрузит ArtBackfiller)",
      album.photos == {})

by_link = ym.load_album_from_link("https://music.yandex.ru/album/130644")
check("load_album_from_link сквозь resolve+fetch",
      by_link.title == "Группа крови" and len(by_link.tracks) == 8
      and by_link.album_id == "yandex:130644")

# ============================================================
print("--- 4. Альбом с версией издания, без жанра ---")
deluxe = ym.fetch_album("555")
check("версия издания дописана к названию",
      deluxe.title == "Ночь (Deluxe Edition)")
check("жанра нет → пусто", deluxe.genre == "")
check("год есть", deluxe.year == "2020")
check("версия трека дописана",
      deluxe.tracks[0].title == "Весна (Live)")
check("версия, уже входящая в название, не дублируется",
      ym._append_version("Ночь (Deluxe)", "Deluxe") == "Ночь (Deluxe)")
check("пустая версия — без изменений",
      ym._append_version("Ночь", "") == "Ночь")

# ============================================================
print("--- 5. Ошибки API ---")
check("подкаст → внятная ошибка",
      "подкаст" in _fetch_error("111").casefold()
      and _fetch_error("111") != ym.UNEXPECTED_MSG)
check("404 → «не нашла такой альбом»",
      _fetch_error("222") == "Яндекс Музыка не нашла такой альбом.")
check("451 → гео-сообщение про Россию/СНГ",
      "страны" in _fetch_error("333")
      and "России" in _fetch_error("333"))
check("мусорный JSON → «неожиданный ответ»",
      _fetch_error("444") == ym.UNEXPECTED_MSG)

# мёртвый порт → «нет соединения»
_real_base = ym.API_BASE
ym.API_BASE = "http://127.0.0.1:1"
check("нет соединения → понятный текст",
      _fetch_error("130644") == ym._NO_CONNECTION_MSG)
ym.API_BASE = _real_base

# ============================================================
print("--- 6. download_image ---")
cover_path = ym.download_image(
    f"http://127.0.0.1:{MOCK_PORT}/covers/kino/400x400"
)
check("download_image сохранил файл",
      cover_path is not None and (APP / cover_path).exists())
check("YandexMusicAlbum.download_image работает как у остальных сервисов",
      album.download_image(
          f"http://127.0.0.1:{MOCK_PORT}/covers/kino/400x400"
      ) is not None)
check("битая загрузка обложки → None без исключения",
      ym.download_image(f"http://127.0.0.1:{MOCK_PORT}/missing.jpg") is None)

# ============================================================
print("--- 7. Заголовок клиента доходит до API ---")
check("X-Yandex-Music-Client во всех запросах",
      bool(LAST_CLIENT) and all(LAST_CLIENT))
check("запросы шли к /albums/<id>/with-tracks",
      len(set(API_HITS)) == 6
      and all(h.startswith("/albums/") and h.endswith("/with-tracks")
              for h in API_HITS))

# ============================================================
print("--- 8. Диалог: ссылка Яндекс Музыки → заполненный мастер ---")
win.open_create_choice()
QTest.qWait(150)
choice = win._choice_overlay
check("диалог открыт", choice is not None and choice.isVisible())
labels = [l.text() for l in choice.pages.widget(1).findChildren(QLabel)]
check("подпись упоминает Яндекс Музыку",
      any("Яндекс" in text for text in labels))
choice.input_link.setText(
    "https://music.yandex.ru/album/130644?utm_source=desktop"
)
check("«Загрузить» активна", choice.btn_load.isEnabled())
choice._try_load()
QTest.qWait(300)
check("диалог закрылся после загрузки", not choice.isVisible())
wizard = win._overlay
check("мастер открыт", wizard is not None and wizard.isVisible())
check("название заполнено", wizard.input_title.text() == "Группа крови")
check("год заполнен", wizard.input_year.text() == "1988")
check("жанр заполнен (Рок)", wizard.combo_genre.currentText() == "Рок")
check("source_id в черновике", wizard.draft.source_id == "yandex:130644")
check("исполнители альбома созданы",
      [a.name for a in wizard.draft.artists] == ["Кино"])
check("треки заполнены (8)", len(wizard.draft.tracks) == 8)
check("исполнитель трека 4: Кино + Роберт",
      [a.name for a in wizard.draft.tracks[3].artists] == ["Кино", "Роберт"])
check("обложка скачалась с мока",
      wizard.draft.cover_path is not None
      and (APP / wizard.draft.cover_path).exists())

# ============================================================
print("--- 9. Защита от повторной загрузки ---")
created = STORE.add_album(AlbumDraft(
    title="Группа крови", year="1988", genre="Рок",
    source_id="yandex:130644",
    tracks=[TrackDraft(title="Группа крови",
                       artists=[ArtistDraft(name="Кино")])],
))
check("альбом с source_id создан",
      STORE.find_album_by_source("yandex:130644") is created)
choice.open()
QTest.qWait(120)
win.toasts.clear()
choice.input_link.setText("https://music.yandex.ru/album/130644")
choice._try_load()
QTest.qWait(200)
check("диалог остался открыт", choice.isVisible())
check("тост «уже создан»",
      any("уже создан" in t.text for t in win.toasts.active))
choice.close_overlay()
QTest.qWait(100)

# ============================================================
print("--- 10. Страница альбома: «Создано с помощью Яндекс Музыки» ---")
check("логотип Яндекс Музыки в ресурсах", YANDEX_LOGO_PATH.exists())
win.open_album(created)
QTest.qWait(200)
page = win.album_page
check("строка источника — «Создано с помощью»",
      page.lbl_source.text() == "Создано с помощью")
check("иконка-логотип видима", page.source_icon.isVisible())
pixmap = page.source_icon.pixmap()
check("пиксмап логотипа ненулевой", pixmap is not None and not pixmap.isNull())
page.grab().save("/tmp/yandex_source.png")

# ============================================================
QTest.qWait(100)
app.processEvents()
_server.shutdown()

print(f"\nИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    for name in FAIL:
        print(f"  FAIL: {name}")
    sys.exit(1)
