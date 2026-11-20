"""Задача 27: YouTube Music как третий источник + прокси для Spotify.

YouTube Music работает из РФ без ключей (в отличие от Spotify),
поэтому именно он закрывает потребность «вставить ссылку и получить
альбом». Мок-сервер на 127.0.0.1 отдаёт УРЕЗАННЫЕ ЖИВЫЕ ответы
youtubei/v1/browse (The Dark Side of the Moon, снятые с реального
API): страница альбома (MPREb_…) и плейлист-двойник (VL+OLAK5uy_…,
через который ссылки playlist?list=… конвертируются в альбом).

Проверки:
  • resolve ссылок YouTube Music (music.youtube.com/youtube.com/
    youtu.be, watch+list, голые OLAK5uy_/MPREb_; плейлисты PL…/RD…,
    watch без list=, чужие хосты — ошибки);
  • разбор ответа: название/год/исполнитель/обложка/треки с
    исполнителями из accessibility-метки; source_id «ytmusic:»
    одинаков для ссылки и прямого MPREb (устойчивость дублей);
  • прокси Spotify: разбор (http/socks5/сокращённый/с авторизацией/
    ошибки), применение к QNAM и сброс, хранение в файле ключей;
  • окно «Создание альбома»: ytmusic-ссылка загружается; ссылка
    Spotify без ключей → страница ключей с подставленным прокси;
    невалидный прокси не сохраняется; сохранение ключей+прокси;
    недоступный Spotify (мёртвый порт) → страница ключей с ошибкой;
    неизвестный хост; дубль;
  • мастер: apply_auto_fill(YTMusicAlbum);
  • страница альбома: лого YouTube Music/Deezer/вручную.

Запускается в ИЗОЛИРОВАННОЙ КОПИИ проекта (data/ создаётся заново).
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(HERE):
    raise SystemExit("Run this check through checks/run.py.")

# Spotify в этом тесте ВСЕГДА недоступен (мёртвый порт): проверяем
# сценарий «Spotify заблокирован → окно ключей с прокси».
# YTM-адрес подставляется после старта мок-сервера.
os.environ["MUSICRATING_SPOTIFY_API"] = "http://127.0.0.1:9"
os.environ["MUSICRATING_SPOTIFY_TOKEN_URL"] = "http://127.0.0.1:9/api/token"
os.environ["MUSICRATING_YTMUSIC_API"] = ""

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

app = QApplication([])

from app.models import AlbumDraft  # noqa: E402
from app.services import spotify, ytmusic  # noqa: E402
from app.store import STORE  # noqa: E402
from checks.fixtures.library import populate_library

populate_library(STORE)
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
# Мок-сервер: youtubei/v1/browse (плейлист/альбом) + картинки
# ---------------------------------------------------------------------------
PORT = 8976
OLAK = "OLAK5uy_lrCrcAdxFG4aMzMrebs7o9TU384xyF240"
MPREB = "MPREb_nHbCAGX6uUL"   # тот же альбом — The Dark Side of the Moon

ALBUM_FIXTURE = json.loads(
    (HERE / "checks" / "fixtures" / "ytm_album_fixture.json").read_text(encoding="utf-8")
)
PLAYLIST_FIXTURE = json.loads(
    (HERE / "checks" / "fixtures" / "ytm_playlist_fixture.json").read_text(encoding="utf-8")
)

# Обложки в фикстуре → локальный мок (проверяем скачивание)


def _patch_thumbnails(node: dict) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "thumbnails" and isinstance(value, list):
                for i, thumb in enumerate(value):
                    if isinstance(thumb, dict) and thumb.get("url"):
                        thumb["url"] = f"http://127.0.0.1:{PORT}/img/c{i}.jpg"
            else:
                _patch_thumbnails(value)
    elif isinstance(node, list):
        for item in node:
            _patch_thumbnails(item)


_patch_thumbnails(ALBUM_FIXTURE)


class YTMHandler(BaseHTTPRequestHandler):

    def log_message(self, *_args):  # тишина в логах
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/youtubei/v1/browse":
            return self._json({}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json({}, 400)
        browse_id = str(payload.get("browseId") or "")
        if browse_id.startswith("VL"):
            if "EMPTY" in browse_id:
                return self._json({})   # в ответе нет адреса альбома
            return self._json(PLAYLIST_FIXTURE)
        if browse_id == MPREB:
            return self._json(ALBUM_FIXTURE)
        return self._json({})   # страница альбома без шапки

    def do_GET(self):  # noqa: N802
        if urlparse(self.path).path.startswith("/img/"):
            body = FAKE_JPEG
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({}, 404)


# Настоящий крошечный JPEG: битые байты дают предупреждения imageio
from PySide6.QtCore import QBuffer  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402

_pm = QPixmap(8, 8)
_pm.fill(QColor("#cc4444"))
_buf = QBuffer()
_buf.open(QBuffer.OpenModeFlag.WriteOnly)
_pm.save(_buf, "JPEG")
FAKE_JPEG = bytes(_buf.data())


server = ThreadingHTTPServer(("127.0.0.1", PORT), YTMHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["MUSICRATING_YTMUSIC_API"] = f"http://127.0.0.1:{PORT}"
# API_BASE у ytmusic читается при импорте — перезадать уже после env
ytmusic.API_BASE = os.environ["MUSICRATING_YTMUSIC_API"]

BASE = f"http://127.0.0.1:{PORT}"

# ---------------------------------------------------------------------------
# 1. resolve ссылок YouTube Music
# ---------------------------------------------------------------------------
check(ytmusic.resolve_list_id(
    f"https://music.youtube.com/playlist?list={OLAK}") == OLAK,
    "resolve: music.youtube.com/playlist")
check(ytmusic.resolve_list_id(
    f"music.youtube.com/watch?v=FEacDWPWfJU&list={OLAK}") == OLAK,
    "resolve: watch + list без схемы")
check(ytmusic.resolve_list_id(
    f"https://www.youtube.com/playlist?list={OLAK}") == OLAK,
    "resolve: www.youtube.com/playlist")
check(ytmusic.resolve_list_id(
    f"https://m.youtube.com/watch?v=x&list={OLAK}") == OLAK,
    "resolve: m.youtube.com")
check(ytmusic.resolve_list_id(
    f"https://youtu.be/FEacDWPWfJU?list={OLAK}") == OLAK,
    "resolve: youtu.be с list")
check(ytmusic.resolve_list_id(OLAK) == OLAK, "resolve: голый OLAK5uy_")
check(ytmusic.resolve_list_id(MPREB) == MPREB, "resolve: голый MPREb_")
for bad, why in (
    ("https://music.youtube.com/watch?v=FEacDWPWfJU", "watch без list"),
    (f"https://music.youtube.com/playlist?list=PLab_cdef123", "обычный плейлист PL"),
    (f"https://music.youtube.com/playlist?list=RDab_cdef123", "микс RD"),
    ("https://www.deezer.com/album/123", "чужой хост"),
    ("https://music.youtube.com/playlist", "страница без параметров"),
    ("", "пустая строка"),
):
    try:
        ytmusic.resolve_list_id(bad)
        check(False, f"resolve: {why} → ошибка")
    except ytmusic.YTMusicError:
        check(True, f"resolve: {why} → ошибка")

# ---------------------------------------------------------------------------
# 2. fetch_album через мок: ссылка → конвертация OLAK → альбом
# ---------------------------------------------------------------------------
album = ytmusic.load_album_from_link(
    f"https://music.youtube.com/playlist?list={OLAK}")
check(album.title == "The Dark Side of the Moon", "fetch: название")
check(album.year == "1973", "fetch: год из подзаголовка")
check(album.artist_names == ["Pink Floyd"], "fetch: исполнитель альбома")
check(album.genre == "", "fetch: жанра нет у YTM — пусто")
check(album.album_id == f"ytmusic:{OLAK}", "fetch: source_id ytmusic:OLAK")
check(album.cover_url is not None and album.cover_url.startswith(BASE),
      "fetch: обложка с мока")
check([t.title for t in album.tracks][:2] ==
      ["Speak to Me", "Breathe (In the Air)"], "fetch: треки по порядку")
check(all(t.artists == ["Pink Floyd"] for t in album.tracks),
      "fetch: исполнители треков из accessibility-метки")
check(album.photos == {}, "fetch: фото исполнителей YTM не даёт")

# Прямой MPREb: тот же source_id (OLAK берётся из watch-ссылки трека)
direct = ytmusic.fetch_album(MPREB)
check(direct.album_id == f"ytmusic:{OLAK}",
      "fetch: MPREb-ссылка даёт тот же source_id (дубль ловится)")

# Пустой ответ плейлиста → «это не альбом»
try:
    ytmusic.fetch_album("OLAK5uy_kEMPTYabcdef")
    check(False, "fetch: плейлист без альбома → ошибка")
except ytmusic.YTMusicError as exc:
    check("альбом" in str(exc).casefold(),
          "fetch: плейлист без альбома — понятный текст")

# Страница альбома без шапки
try:
    ytmusic.fetch_album("MPREb_unknown123")
    check(False, "fetch: пустая страница альбома → ошибка")
except ytmusic.YTMusicError as exc:
    check("не нашёл" in str(exc), "fetch: пустая страница — понятный текст")

path = album.download_image(album.cover_url)
from app.store import COVERS_DIR, DATA_DIR  # noqa: E402
check(path is not None and str(STORE.resolve(path)).startswith(str(COVERS_DIR)),
      "fetch: обложка скачана в data/covers")

# Разбор accessibility-меток (исполнители треков)
check(ytmusic._artists_from_label(
    "Play Speak to Me - Pink Floyd", "Speak to Me", "Pink Floyd") ==
    ["Pink Floyd"], "метка: обычный трек")
check(ytmusic._artists_from_label(
    "Play X - A, B & C feat. D", "X", "") == ["A", "B", "C", "D"],
    "метка: фиты через запятую, & и feat.")
check(ytmusic._artists_from_label(
    "Pause Совсем Другое Название - Кто-то", "X", "Из шапки") ==
    ["Из шапки"], "метка: не совпала → исполнитель альбома")

# ---------------------------------------------------------------------------
# 3. Прокси Spotify: разбор, применение, хранение
# ---------------------------------------------------------------------------
proxy, error = spotify.parse_proxy("")
check(proxy is None and error == "", "прокси: пусто → напрямую")
proxy, error = spotify.parse_proxy("socks5://user:pass@10.0.0.1:1080")
check(proxy is not None and error == ""
      and proxy.type() == proxy.ProxyType.Socks5Proxy
      and proxy.hostName() == "10.0.0.1" and proxy.port() == 1080
      and proxy.user() == "user" and proxy.password() == "pass",
      "прокси: socks5 с авторизацией")
proxy, error = spotify.parse_proxy("127.0.0.1:8080")
check(proxy is not None and proxy.type() == proxy.ProxyType.HttpProxy
      and proxy.hostName() == "127.0.0.1" and proxy.port() == 8080,
      "прокси: сокращённый host:port → http")
proxy, error = spotify.parse_proxy("https://proxy.example.com")
check(proxy is not None and proxy.port() == 8080,
      "прокси: без порта → порт по умолчанию")
proxy, error = spotify.parse_proxy("ftp://x")
check(proxy is None and "socks5" in error, "прокси: неизвестная схема → ошибка")

manager = spotify._manager()
check(spotify.apply_proxy("socks5://5.6.7.8:1080") == "",
      "прокси: применён без ошибок")
check(manager.proxy().type() == manager.proxy().ProxyType.Socks5Proxy
      and manager.proxy().hostName() == "5.6.7.8",
      "прокси: менеджер ходит через socks5://5.6.7.8:1080")
check(spotify.apply_proxy("мусор") != "", "прокси: мусор отклонён")
check(manager.proxy().hostName() == "5.6.7.8",
      "прокси: после отклонённого — прежний")
check(spotify.apply_proxy("") == ""
      and manager.proxy().type() == manager.proxy().ProxyType.DefaultProxy,
      "прокси: пустая строка → сброс на системное поведение")

# Файл ключей: прокси сохраняется и подчитывается
CREDS_FILE = spotify.credentials_path()
spotify.save_credentials("id-1", "sec-1", "socks5://1.2.3.4:1080")
saved = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
check(saved.get("client_id") == "id-1" and "client_secret" not in saved
      and bool(saved.get("client_secret_dpapi")) and saved.get("proxy") == "socks5://1.2.3.4:1080",
      "прокси: сохранён в файле ключей")
spotify.save_credentials("id-2", "sec-2")   # старый вызов без прокси
saved = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
check(saved["proxy"] == "socks5://1.2.3.4:1080"
      and saved["client_id"] == "id-2",
      "прокси: вызов без прокси не затирает сохранённый")
check(spotify.load_proxy() == "socks5://1.2.3.4:1080",
      "прокси: load_proxy читает файл")

# ---------------------------------------------------------------------------
# 4. Диалог «Создание альбома»: YouTube Music и ключи/прокси
# ---------------------------------------------------------------------------
holder = QWidget()
holder.resize(900, 600)
holder.show()
QTest.qWait(50)

results: list[object] = []
overlay = CreateChoiceOverlay(holder)

# Оповещения — тосты (Task 31): помощник чтения последнего тоста
from app.ui.widgets.toast import manager_for

def last_toast():
    active = manager_for(holder).active
    return active[0] if active else None

overlay.setGeometry(holder.rect())
overlay.album_loaded.connect(results.append)

check(detect_provider("https://music.youtube.com/playlist?list=OLAK5uy_x") == "ytmusic",
      "окно: detect music.youtube.com → ytmusic")
check(detect_provider("https://youtu.be/x?list=OLAK5uy_x") == "ytmusic",
      "окно: detect youtu.be → ytmusic")
check(detect_provider("https://open.spotify.com/album/1") == "spotify",
      "окно: detect spotify не сломан")
check(detect_provider("https://www.deezer.com/album/1") == "deezer",
      "окно: detect deezer не сломан")

# 4.1 Полный поток: ссылка YouTube Music → загрузка
overlay.open()
overlay._choose_auto()
overlay.input_link.setText(f"https://music.youtube.com/playlist?list={OLAK}")
overlay._try_load()
check(len(results) == 1, "окно: ytmusic-ссылка загрузилась")
if results:
    loaded = results[0]
    check(type(loaded).__name__ == "YTMusicAlbum",
          "окно: сигнал несёт YTMusicAlbum")
    check(loaded.album_id == f"ytmusic:{OLAK}", "окно: source_id с префиксом")
check(not overlay.isVisible() or not overlay.card.isVisible(),
      "окно: после загрузки карточка скрыта")

# 4.2 Ссылка Spotify без ключей (файл стёрт) → страница ключей
CREDS_FILE.unlink(missing_ok=True)
spotify.invalidate_token()
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://open.spotify.com/album/ALBUM1")
overlay._try_load()
check(overlay.pages.currentIndex() == 2,
      "окно: ссылка Spotify без ключей → страница ключей")
check(overlay.input_client_id.text() == ""
      and overlay.input_client_secret.text() == ""
      and overlay.input_proxy.text() == "",
      "окно: без ключей все поля пусты")
check(overlay.btn_keys_save.isEnabled() is False,
      "окно: «Сохранить и загрузить» неактивна при пустых полях")
overlay.handle_escape()
check(overlay.pages.currentIndex() == 1,
      "окно: Esc со страницы ключей → назад к ссылке")

# 4.3 Ключи и прокси из файла подставляются для правки
spotify.save_credentials("id-2", "sec-2", "socks5://1.2.3.4:1080")
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://open.spotify.com/album/ALBUM1")
overlay._try_load()
check(overlay.pages.currentIndex() == 2,
      "окно: повторная ссылка Spotify → страница ключей")
check(overlay.input_proxy.text() == "socks5://1.2.3.4:1080",
      "окно: сохранённый прокси подставлен в поле")
check(overlay.input_client_id.text() == "id-2"
      and overlay.input_client_secret.text() == "sec-2",
      "окно: сохранённые ключи подставлены")

# 4.4 Невалидный прокси не сохраняется
overlay.input_client_id.setText("new-id")
overlay.input_client_secret.setText("new-sec")
overlay.input_proxy.setText("ftp://broken")
overlay._save_keys_and_load()
_t = last_toast()
check(_t is not None and "socks5" in _t.text,
      "окно: невалидный прокси — тост на странице ключей")
check(json.loads(CREDS_FILE.read_text(encoding="utf-8"))["client_id"] == "id-2",
      "окно: невалидный прокси — файл ключей не перезаписан")

# 4.5 Сохранение ключей + прокси → автозагрузка → Spotify недоступен
# (токен ходит на мёртвый порт; прокси 127.0.0.1:9 — отказ мгновенный)
overlay.input_client_id.setText("new-id")
overlay.input_client_secret.setText("new-sec")
overlay.input_proxy.setText("socks5://127.0.0.1:9")
overlay._save_keys_and_load()
saved = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
check(saved.get("client_id") == "new-id" and "client_secret" not in saved
      and bool(saved.get("client_secret_dpapi")) and saved.get("proxy") == "socks5://127.0.0.1:9",
      "окно: ключи и прокси сохранены вместе")
check(spotify._manager().proxy().hostName() == "127.0.0.1",
      "окно: прокси применён к менеджеру Spotify")
_t = last_toast()
check(overlay.pages.currentIndex() == 2
      and _t is not None and _t.text in spotify.CONNECTION_MESSAGES,
      "окно: Spotify недоступен → страница ключей + тост с ошибкой")

# 4.6 Неизвестный хост → общая красная подсказка
overlay.open()
overlay._choose_auto()
overlay.input_link.setText("https://example.com/album/1")
overlay._try_load()
_t = last_toast()
check(_t is not None and _t.text == NOT_LINK_MSG,
      "окно: чужой хост — общий текст «не ссылка на альбом» (тост)")

# 4.7 Дубль: альбом по этой ссылке уже создавали
draft = AlbumDraft()
draft.title = "The Dark Side of the Moon"
draft.source_id = f"ytmusic:{OLAK}"
STORE.add_album(draft)
overlay.open()
overlay._choose_auto()
overlay.input_link.setText(f"music.youtube.com/playlist?list={OLAK}")
overlay._try_load()
_t = last_toast()
check(_t is not None
      and _t.text == "Кажется, этот альбом уже создан.",
      "окно: ytmusic-дубль — тост (Task 31)")
check(overlay.btn_load.isEnabled() is False,
      "окно: «Загрузить» заблокирована для дубля")

# ---------------------------------------------------------------------------
# 5. Мастер: apply_auto_fill(YTMusicAlbum)
# ---------------------------------------------------------------------------
from app.ui.pages.create_album import CreateAlbumOverlay  # noqa: E402

master = CreateAlbumOverlay(holder)
master.setGeometry(holder.rect())
master.reset()
master.apply_auto_fill(album)
check(master.input_title.text() == "The Dark Side of the Moon",
      "мастер: название")
check(master.input_year.text() == "1973", "мастер: год")
check(master.combo_genre.currentText() == "", "мастер: жанр не заполнен")
check(len(master.draft.tracks) == 4, "мастер: треки заполнены")
check(master.draft.artists[0].name == "Pink Floyd",
      "мастер: исполнитель альбома в черновике")
check(master.draft.source_id == f"ytmusic:{OLAK}", "мастер: source_id черновика")
check(master.badge_title.property("mark") == "ok", "мастер: жёлтая метка названия")
check(master.badge_region.property("mark") == "bad", "мастер: красная метка региона")
check(master._auto_filled is True, "мастер: флаг автозаполнения")
check(any(a.name == "Pink Floyd" for a in STORE.artists),
      "мастер: исполнитель попал в базу")

# ---------------------------------------------------------------------------
# 6. Строка источника на странице альбома
# ---------------------------------------------------------------------------
page = AlbumDetailPage(holder)
page.setGeometry(holder.rect())
page.show()
QTest.qWait(50)
albums = {a.title: a for a in STORE.albums}
stored_album = albums["The Dark Side of the Moon"]
check(stored_album.source_id == f"ytmusic:{OLAK}",
      "страница: у альбома source_id YouTube Music")
page.set_album(stored_album)
check(page.lbl_source.text() == "Создано с помощью",
      "страница: текст «Создано с помощью»")
check(page.source_icon.isVisible() and not page.source_icon.pixmap().isNull(),
      "страница: лого YouTube Music показан")

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
