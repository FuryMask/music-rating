"""Задача 32: парсинг Genius в автоматическом создании альбома.

Покрывает:
  1. detect_provider: genius.com и поддомены (ru.genius.com) → «genius»;
     прежние провайдеры не сломаны; неизвестный хост → «».
  2. resolve_album_path: ссылка на альбом → путь /albums/…; ссылки на
     песни (…-lyrics), главная, чужие домены, пустая строка → ошибка.
  3. Стратегия A — window.__PRELOADED_STATE__ (JSON.parse): название,
     исполнитель, год, обложка (og:image), 8 треков, фиты из JSON
     (featured_artists) и из названия «(Ft. …)», album_id genius:<id>.
  4. Стратегия B — без скрипта (страница без состояния): те же данные
     из HTML-маркеров (h1-заголовок, og:мета, metadata_unit,
     chart_row-content-title/non-title); дубль трека отфильтрован;
     «Lyrics»-хвосты и вложенные теги вычищены.
  5. Мусорная страница (анти-бот «включите javascript») и страница
     без треклиста → GeniusError с понятным текстом.
  6. Сеть через локальный мок (MUSICRATING_GENIUS_BASE): fetch_album,
     load_album_from_link, download_image сохраняет файл в data/covers.
  7. Диалог создания целиком: ссылка Genius → альбом_loaded → мастер
     с заполненными полями (название/год/исполнители/треки/source_id).
  8. Защита от повторной загрузки: «Кажется, этот альбом уже создан».
  9. Страница альбома с source_id «genius:…» — «Создано с помощью» +
     логотип Genius (genius_logo.png).
 10. Браузерные заголовки запроса (User-Agent обязателен: без него
     антибот Genius отвечает 403) и ошибка 403 → понятный текст.
 11. Соавторы коллабораций: «(with …)» в конце названия (JSON и
     HTML-строка), исполнители-ссылки в строке треклиста (внутри и
     вне ссылки-строки), primary_artists списком, гибрид JSON+HTML
     (дополнение исполнителей из строк без дублей).
 12. Официальный API Genius (api.genius.com, Client Access Token
     вшит в код): полные исполнители треков (primary + featured)
     по song_id из JSON страницы — соисполнители, которых на странице
     альбома не видно вовсе («The Weeknd & Anitta»); склейка с
     исполнителями страницы без дублей; фолбэк на исполнителей
     страницы при сбое API (404/500); стоп после 3 неудач подряд;
     заголовок Authorization: Bearer доходит до сервера.
 13. Реальный формат страницы альбома (сверено с Hurry Up Tomorrow):
     state в ОДИНАРНЫХ кавычках JSON.parse('…') с JS-эскейпами,
     треклист в islands.albumAppearances (camelCase primaryArtists —
     полный список соавторов коллабораций, featuredArtists у них
     пуст), id и url каждой песни; coverArtUrl без og:мета.
 14. Страницы самих треков (решение пользователя): каждый трек
     дополнительно открывается по своему url — исполнители из h2
     подзаголовка (ссылки на каждого) и из состояния страницы;
     дополнение без дублей, фолбэк при 500, стоп после 3 неудач.

ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
"""

import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

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

from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QApplication
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

# --- Мок-сервер Genius (до импорта app.services.genius!) -------------------
FIXTURE = (APP / "checks" / "fixtures" / "genius_album_page.html").read_text("utf-8")
ISLANDS_FIXTURE = (APP / "checks" / "fixtures" / "genius_album_islands.html").read_text("utf-8")
CHALLENGE_HTML = (
    "<!DOCTYPE html><html><head><title>Genius</title></head><body>"
    "Please enable javascript and refresh the page to continue</body></html>"
)
FAKE_COVER = b"\x89PNG-fake-cover-bytes"

LAST_UA: list[str] = []  # User-Agent запросов, дошедших до мока
LAST_AUTH: list[str] = []  # Authorization запросов к официальному API
API_HITS: list[str] = []  # пути всех запросов /songs/<id>
PAGE_HITS: list[str] = []  # пути всех запросов страниц треков

# Ответы официального API по трекам фикстур (id 101..108 старой,
# 201..208 островной): 101/105 — совпадает со страницей; 102 —
# совпадает (дублей нет); 104/107 — соисполнитель, которого на
# странице альбома НЕ видно вовсе (главный кейс «The Weeknd &
# Anitta»); 106 — API «знает меньше» страницы (имя со страницы
# сохраняется); 103 → 404, 108/208/555 → 500 (фолбэк/предохранитель);
# 204/207 — API НЕ знает соисполнителя (добавит страница трека)
API_SONGS: dict[int, dict] = {
    101: {"primary_artist": {"name": "Кино"}},
    102: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Гость"}]},
    104: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Роберт"}]},
    105: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Дюша"}]},
    106: {"primary_artist": {"name": "Кино"}},
    107: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Гость 2"}]},
    201: {"primary_artist": {"name": "Кино"}},
    202: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Гость"}]},
    203: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Гость"}]},
    204: {"primary_artist": {"name": "Кино"}},
    205: {"primary_artist": {"name": "Кино"}},
    206: {"primary_artist": {"name": "Кино"},
          "featured_artists": [{"name": "Дюша"}]},
    207: {"primary_artist": {"name": "Кино"}},
}

# Страницы треков (…-lyrics): имена из h2-подзаголовка; None → 500.
# 204 → «Кино, Роберт» и 207 → «Кино, Дюша» — соисполнители, которых
# нет ни в islands, ни в API: их даёт ТОЛЬКО страница трека
TRACK_PAGES: dict[str, list[str] | None] = {
    "/Kino-Gruppa-krovi-lyrics": ["Кино"],
    "/Kino-Zakroy-za-mnoy-dver-ya-uhozhu-lyrics": ["Кино", "Гость"],
    "/Kino-V-nashih-glazah-lyrics": ["Кино", "Гость"],
    "/Kino-Poprobuj-spet-vmeste-so-mnoj-lyrics": ["Кино", "Роберт"],
    "/Kino-Legenda-lyrics": ["Кино", "Дюша"],
    "/Kino-Spokojnaya-noch-lyrics": ["Кино", "Дюша"],
    "/Kino-Mama-my-vse-tyazhelo-bolny-lyrics": ["Кино", "Гость 2"],
    "/Kino-Mama-remix-lyrics": ["Кино", "Дюша"],
    "/Kino-Boshetunmaj-lyrics": None,
}


def _track_page(names: list[str]) -> bytes:
    """Мини-страница трека: исполнители ссылками в h2 (как на Genius)."""
    links = " &amp; ".join(
        f'<a href="/artists/{i}">{n}</a>' for i, n in enumerate(names)
    )
    html = (
        "<!DOCTYPE html><html><head><title>Трек Lyrics | Genius</title></head>"
        '<body><div class="header_with_cover_art">'
        '<h1 class="header_with_cover_art-primary_info-title">Трек</h1>'
        f'<h2 class="header_with_cover_art-primary_info-primary_artist">{links}</h2>'
        "</div></body></html>"
    )
    return html.encode("utf-8")


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # тишина в выводе
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        LAST_UA.append(self.headers.get("User-Agent") or "")
        path = unquote(urlparse(self.path).path)
        if path.startswith("/songs/"):
            # Официальный API Genius: /songs/<id> с Bearer-токеном
            LAST_AUTH.append(self.headers.get("Authorization") or "")
            API_HITS.append(path)
            song_id = path.rsplit("/", 1)[-1]
            entry = API_SONGS.get(int(song_id)) if song_id.isdigit() else None
            if song_id == "103":
                self.send_response(404)
                self.end_headers()
                return
            if entry is None:
                self.send_response(500)
                self.end_headers()
                return
            payload = {"response": {"song": {"id": int(song_id), **entry}}}
            self._send(json.dumps(payload).encode("utf-8"), "application/json")
            return
        if path.endswith("-lyrics"):
            # Страница трека: исполнители ссылками в h2; неизвестный
            # путь или None → 500 (фолбэк/предохранитель)
            PAGE_HITS.append(path)
            entry = TRACK_PAGES.get(path)
            if entry is None:
                self.send_response(500)
                self.end_headers()
                return
            self._send(_track_page(entry), "text/html")
            return
        if path.startswith("/albums/82980/large.jpg"):
            self._send(FAKE_COVER, "image/jpeg")
            return
        if path.startswith("/missing") or path.endswith("/nope"):
            self.send_response(404)
            self.end_headers()
            return
        if path.startswith("/bad"):
            self._send(CHALLENGE_HTML.encode("utf-8"), "text/html")
            return
        if path.startswith("/denied"):
            # Симуляция антибота Genius: HTTP 403 без тела
            self.send_response(403)
            self.end_headers()
            return
        if path.startswith("/albums/"):
            # og:image в отданной странице указывает на мок — тогда
            # обложка скачивается с мока, а не с images.genius.com;
            # путь …-islands отдаёт фикстуру реального («островного»)
            # формата
            if path.endswith("-islands"):
                self._send(ISLANDS_FIXTURE.encode("utf-8"), "text/html")
                return
            self._send(
                FIXTURE.replace(
                    "https://images.genius.com/albums/82980/large.jpg",
                    f"http://127.0.0.1:{MOCK_PORT}/albums/82980/large.jpg",
                ).encode("utf-8"),
                "text/html",
            )
            return
        self.send_response(404)
        self.end_headers()


_server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
MOCK_PORT = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()

os.environ["MUSICRATING_GENIUS_BASE"] = f"http://127.0.0.1:{MOCK_PORT}"
os.environ["MUSICRATING_GENIUS_TOKEN"] = "fake-genius-token-for-local-tests"
os.environ["MUSICRATING_GENIUS_API_BASE"] = f"http://127.0.0.1:{MOCK_PORT}"

import app.services.genius as genius
from app.services.genius import GeniusAlbum, GeniusError, GeniusTrack
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay, detect_provider
from app.ui.pages.album_detail import GENIUS_LOGO_PATH

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


# --- Данные: аккаунт (после стирания data/ — демо-библиотека) -------------
from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.store import DATA_DIR, STORE
from checks.fixtures.library import populate_library

populate_library(STORE)
from PySide6.QtWidgets import QLabel


from app.ui.main_window import MainWindow

win = MainWindow()
win.resize(1200, 800)
win.show()
QTest.qWait(200)

# ============================================================
print("--- 1. detect_provider ---")
check("genius.com", detect_provider("https://genius.com/albums/Kino/Gruppa-krovi") == "genius")
check("ru.genius.com (поддомен)",
      detect_provider("https://ru.genius.com/albums/Kino/Gruppa-krovi") == "genius")
check("без схемы", detect_provider("genius.com/albums/Kino/Gruppa-krovi") == "genius")
check("spotify не сломан",
      detect_provider("https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv") == "spotify")
check("spotify:album: URI", detect_provider("spotify:album:4LH4d3cOWNNsVw41Gqt2kv") == "spotify")
check("deezer не сломан", detect_provider("https://www.deezer.com/album/123") == "deezer")
check("youtube не сломан",
      detect_provider("https://music.youtube.com/playlist?list=OLAK5uy_k") == "ytmusic")
check("чужой домен", detect_provider("https://example.com/albums/A/B") == "")
check("пустая строка", detect_provider("   ") == "")

# ============================================================
print("--- 2. resolve_album_path ---")
check("путь альбома",
      genius.resolve_album_path("https://genius.com/albums/Kino/Gruppa-krovi")
      == "/albums/Kino/Gruppa-krovi")
check("поддомен → тот же путь",
      genius.resolve_album_path("https://ru.genius.com/albums/Kino/Gruppa-krovi/")
      == "/albums/Kino/Gruppa-krovi")
check("без схемы и с query",
      genius.resolve_album_path("genius.com/albums/Kino/Gruppa-krovi?x=1")
      == "/albums/Kino/Gruppa-krovi")
check("percent-encoded раскрывается",
      genius.resolve_album_path("https://genius.com/albums/Kino/%D0%9A%D0%B8%D0%BD%D0%BE")
      == "/albums/Kino/Кино")


def _raises_path(text: str, message: str = genius.NOT_ALBUM_MSG) -> bool:
    try:
        genius.resolve_album_path(text)
    except GeniusError as exc:
        return str(exc) == message
    return False


check("ссылка на песню отклонена",
      _raises_path("https://genius.com/Kino-Gruppa-krovi-lyrics"))
check("главная отклонена", _raises_path("https://genius.com/"))
check("чужой домен отклонён", _raises_path("https://example.com/albums/A/B"))
check("пустая строка — просьба вставить ссылку",
      _raises_path("", "Вставьте ссылку на альбом Genius."))
check("genius без альбома в пути отклонён",
      _raises_path("https://genius.com/search?q=x"))

# ============================================================
print("--- 3. Стратегия A: window.__PRELOADED_STATE__ ---")
album = genius.parse_album_html(FIXTURE, "/albums/Kino/Gruppa-krovi")
check("это GeniusAlbum", isinstance(album, GeniusAlbum))
check("название", album.title == "Группа крови")
check("исполнитель альбома", album.artist_names == ["Кино"])
check("год из release_date", album.year == "1988")
check("обложка из og:image",
      album.cover_url == "https://images.genius.com/albums/82980/large.jpg")
check("жанр пуст (у Genius жанров нет)", album.genre == "")
check("album_id из JSON", album.album_id == "genius:82980")
check("8 треков (дублей нет)", len(album.tracks) == 8)
check("трек 1 без фитов",
      album.tracks[0].title == "Группа крови"
      and album.tracks[0].artists == ["Кино"])
check("фит из featured_artists (JSON)",
      album.tracks[4].title == "Легенда"
      and album.tracks[4].artists == ["Кино", "Дюша"])
check("фит из «(Ft. …)» в названии вычищен",
      album.tracks[5].title == "Спокойная ночь"
      and album.tracks[5].artists == ["Кино", "Дюша"])
check("соавторы из строки-ссылок дополняют JSON (гибрид)",
      album.tracks[1].title == "Закрой за мной дверь, я ухожу"
      and album.tracks[1].artists == ["Кино", "Гость"])
check("«(with …)» в конце названия: вычищен и добавлен исполнителем",
      album.tracks[2].title == "В наших глазах"
      and album.tracks[2].artists == ["Кино", "Гость"])
check("исполнители списком (primary_artists) понимаются",
      album.tracks[3].title == "Попробуй спеть вместе со мной"
      and album.tracks[3].artists == ["Кино"])
check("фото исполнителей пустое (дозагрузит ArtBackfiller)",
      album.photos == {})

# ============================================================
print("--- 4. Стратегия B: HTML-маркеры без состояния ---")
import re as _re

no_state = _re.sub(
    r"<script[^>]*>\s*window\.__PRELOADED_STATE__.*?</script>", "", FIXTURE,
    flags=_re.DOTALL,
)
check("скрипт состояния удалён", "__PRELOADED_STATE__" not in no_state)
album_b = genius.parse_album_html(no_state, "/albums/Kino/Gruppa-krovi")
check("название из h1", album_b.title == "Группа крови")
check("исполнитель из h2", album_b.artist_names == ["Кино"])
check("год из metadata_unit", album_b.year == "1988")
check("обложка из og:image", album_b.cover_url == album.cover_url)
check("8 треков (дубль из HTML отфильтрован)", len(album_b.tracks) == 8)
check("порядок треков как в треклисте",
      [t.title for t in album_b.tracks]
      == ["Группа крови", "Закрой за мной дверь, я ухожу", "В наших глазах",
          "Попробуй спеть вместе со мной", "Легенда", "Спокойная ночь",
          "Мама, мы все тяжело больны", "Бошетунмай"])
check("исполнитель строки + фит из названия",
      album_b.tracks[5].artists == ["Кино", "Дюша"])
check("строка-ссылки вне ссылки-строки: два исполнителя",
      album_b.tracks[1].artists == ["Кино", "Гость"])
check("«(with …)» в строке: соавтор добавлен",
      album_b.tracks[2].artists == ["Кино", "Гость"])
check("album_id из пути (id в HTML не виден)",
      album_b.album_id == "genius:albums/Kino/Gruppa-krovi")

# Мини-страница: только og:мета и одна строка треклиста; соавторы —
# ссылки ВНЕ ссылки-строки (как в реальной разметке: <a> не вкладывается в <a>)
mini = (
    '<meta property="og:title" content="Альбом от Артист">'
    '<meta property="og:image" content="https://images.genius.com/x.jpg">'
    '<a href="https://genius.com/Artistist-Song-lyrics">'
    '<span class="chart_row-content-title">Песня <span class="x">текст</span> Lyrics</span>'
    '</a>'
    '<span class="chart_row-non-title">'
    '<a href="https://genius.com/artists/A">Другой</a> &amp; '
    '<a href="https://genius.com/artists/B">Третий</a></span>'
)
album_c = genius.parse_album_html(mini, "/albums/Artistist/Альбом")
check("og:title с «от» → название/исполнитель",
      album_c.title == "Альбом" and album_c.artist_names == ["Артист"])
check("исполнители строки (ссылки вне ссылки-строки) важнее исполнителя альбома",
      album_c.tracks[0].artists == ["Другой", "Третий"])
check("хвост Lyrics и вложенные теги вычищены",
      album_c.tracks[0].title == "Песня текст")

# ============================================================
print("--- 5. Мусорные страницы → GeniusError ---")


def _parse_error(html: str) -> str:
    try:
        genius.parse_album_html(html, "/albums/Kino/Gruppa-krovi")
    except GeniusError as exc:
        return str(exc)
    return ""


check("анти-бот страница: понятная ошибка",
      _parse_error(CHALLENGE_HTML) == genius._PARSE_FAIL_MSG)
check("страница без треклиста: ошибка",
      _parse_error(
          '<meta property="og:title" content="Альбом by Кто-то">'
      ) == genius._PARSE_FAIL_MSG)

# ============================================================
print("--- 6. Сеть через мок: fetch_album / download_image ---")
net_album = genius.fetch_album("/albums/Kino/Gruppa-krovi")
check("fetch_album: название", net_album.title == "Группа крови")
check("fetch_album: album_id из JSON", net_album.album_id == "genius:82980")
check("fetch_album: 8 треков", len(net_album.tracks) == 8)
by_link = genius.load_album_from_link("https://genius.com/albums/Kino/Gruppa-krovi")
check("load_album_from_link сквозь resolve+fetch",
      by_link.title == "Группа крови" and len(by_link.tracks) == 8)
cover_path = genius.download_image(
    f"http://127.0.0.1:{MOCK_PORT}/albums/82980/large.jpg"
)
check("download_image сохранил файл",
      cover_path is not None and (APP / cover_path).exists())
check("GeniusAlbum.download_image работает как у остальных сервисов",
      net_album.download_image(
          f"http://127.0.0.1:{MOCK_PORT}/albums/82980/large.jpg"
      ) is not None)
bad_cover = genius.download_image(f"http://127.0.0.1:{MOCK_PORT}/missing.jpg")
check("битая загрузка обложки → None без исключения", bad_cover is None)

# ============================================================
print("--- 6b. Официальный API: полные исполнители треков ---")
check("song_id трека взят из JSON страницы",
      net_album.tracks[3].song_id == 104)
check("соисполнитель, которого НЕТ на странице альбома («The Weeknd & Anitta»)",
      net_album.tracks[3].title == "Попробуй спеть вместе со мной"
      and net_album.tracks[3].artists == ["Кино", "Роберт"])
check("второй соисполнитель из API (трек 7)",
      net_album.tracks[6].artists == ["Кино", "Гость 2"])
check("совпадающие списки API и страницы — без дублей (трек 2)",
      net_album.tracks[1].artists == ["Кино", "Гость"])
check("API «знает меньше» страницы — имя со страницы сохранено (трек 6)",
      net_album.tracks[5].artists == ["Кино", "Дюша"])
check("страница без изменений, когда API совпадает (трек 1)",
      net_album.tracks[0].artists == ["Кино"])
check("API 404 → исполнители со страницы (трек 3)",
      net_album.tracks[2].artists == ["Кино", "Гость"])
check("API 500 → исполнители со страницы (трек 8)",
      net_album.tracks[7].artists == ["Кино"])
check("Bearer-токен дошёл до API во всех запросах",
      bool(LAST_AUTH)
      and all(a == f"Bearer {genius.load_access_token()}" for a in LAST_AUTH))
check("по запросу API на каждый из 8 треков (fetch дважды — пути те же)",
      len(set(API_HITS)) == 8
      and all(h.startswith("/songs/") for h in API_HITS))

# Предохранитель: после 3 неудач API подряд обогащение прекращается
_songs_before = sum(1 for h in API_HITS if h == "/songs/555")
_breaker_album = GeniusAlbum(title="X", tracks=[
    GeniusTrack(title=f"t{i}", artists=["Кино"], song_id=555)
    for i in range(6)
])
genius._enrich_performers(_breaker_album)
_songs_after = sum(1 for h in API_HITS if h == "/songs/555")
check("3 неудачи API подряд → стоп (запросов не больше трёх)",
      _songs_after - _songs_before == 3)
check("после стопа у треков остаются исполнители со страницы",
      all(t.artists == ["Кино"] for t in _breaker_album.tracks))

if sys.platform == "win32":
    fixture_token = "sample-genius-local-token"
    genius.save_access_token(fixture_token)
    credentials = DATA_DIR / "genius_credentials.json"
    check("локальный ключ зашифрован на диске",
          fixture_token not in credentials.read_text(encoding="utf-8"))
    override = os.environ.pop("MUSICRATING_GENIUS_TOKEN")
    try:
        check("локальный ключ передаётся в Genius API",
              genius.fetch_song_performers(104) == ["Кино", "Роберт"]
              and LAST_AUTH[-1] == f"Bearer {fixture_token}")
    finally:
        os.environ["MUSICRATING_GENIUS_TOKEN"] = override
        credentials.unlink()

# ============================================================
print("--- 6c. Реальный формат (острова) + страницы треков ---")
islands_html = ISLANDS_FIXTURE
isl_parsed = genius.parse_album_html(islands_html, "/albums/Kino/Gruppa-krovi")
check("state в ОДИНАРНЫХ кавычках парсится (album_id из islands)",
      isl_parsed.album_id == "genius:82980")
check("название/исполнитель из islands",
      isl_parsed.title == "Группа крови"
      and isl_parsed.artist_names == ["Кино"])
check("год из releaseDate (без og:мета)", isl_parsed.year == "1988")
check("обложка из coverArtUrl (без og:мета)",
      isl_parsed.cover_url == "https://images.genius.com/albums/82980/large.jpg")
check("8 треков из albumAppearances", len(isl_parsed.tracks) == 8)
check("соавторы из primaryArtists («The Weeknd & Anitta»)",
      isl_parsed.tracks[1].title == "Закрой за мной дверь, я ухожу"
      and isl_parsed.tracks[1].artists == ["Кино", "Гость"])
check("фит из featuredArtists (camelCase)",
      isl_parsed.tracks[2].artists == ["Кино", "Гость"])
check("«(Ft. …)» в title нового формата вычищен",
      isl_parsed.tracks[4].title == "Легенда"
      and isl_parsed.tracks[4].artists == ["Кино", "Дюша"])
check("song_id из islands", isl_parsed.tracks[0].song_id == 201)
check("url трека захвачен",
      isl_parsed.tracks[0].url == "/Kino-Gruppa-krovi-lyrics")

net_islands = genius.fetch_album("/albums/Kino/Gruppa-krovi-islands")
check("страница трека дала соисполнителя, которого нет в islands и в API",
      net_islands.tracks[3].title == "Попробуй спеть вместе со мной"
      and net_islands.tracks[3].artists == ["Кино", "Роберт"])
check("страница трека дала второго исполнителя (трек 7)",
      net_islands.tracks[6].artists == ["Кино", "Дюша"])
check("страница трека 500 → исполнители альбома целы (трек 8)",
      net_islands.tracks[7].artists == ["Кино"])
check("страницы треков не добавили дублей (трек 2)",
      net_islands.tracks[1].artists == ["Кино", "Гость"])

# Предохранитель страниц треков: 3 неудачи подряд → стоп
_pages_before = sum(1 for p in PAGE_HITS if p == "/fail-lyrics")
_page_breaker = GeniusAlbum(title="X", tracks=[
    GeniusTrack(title=f"t{i}", artists=["Кино"], url="/fail-lyrics")
    for i in range(6)
])
genius._enrich_from_track_pages(_page_breaker)
_pages_after = sum(1 for p in PAGE_HITS if p == "/fail-lyrics")
check("страницы треков: 3 неудачи подряд → стоп",
      _pages_after - _pages_before == 3)
check("после стопа исполнители треков целы",
      all(t.artists == ["Кино"] for t in _page_breaker.tracks))

# ============================================================
print("--- 7. Диалог создания: ссылка Genius → заполненный мастер ---")
win.open_create_choice()
QTest.qWait(150)
choice = win._choice_overlay
check("диалог открыт", choice is not None and choice.isVisible())
labels = [l.text() for l in choice.pages.widget(1).findChildren(QLabel)]
check("подпись упоминает Genius",
      any("Genius" in text for text in labels))
choice.input_link.setText("https://genius.com/albums/Kino/Gruppa-krovi")
check("«Загрузить» активна", choice.btn_load.isEnabled())
choice._try_load()
QTest.qWait(300)
check("диалог закрылся после загрузки", not choice.isVisible())
wizard = win._overlay
check("мастер открыт", wizard is not None and wizard.isVisible())
check("название заполнено", wizard.input_title.text() == "Группа крови")
check("год заполнен", wizard.input_year.text() == "1988")
check("source_id в черновике", wizard.draft.source_id == "genius:82980")
check("исполнители альбома созданы",
      [a.name for a in wizard.draft.artists] == ["Кино"])
check("треки заполнены (8)", len(wizard.draft.tracks) == 8)
check("исполнитель трека 6: Кино + Дюша",
      [a.name for a in wizard.draft.tracks[5].artists] == ["Кино", "Дюша"])
check("обложка скачалась с мока",
      wizard.draft.cover_path is not None
      and (APP / wizard.draft.cover_path).exists())

# ============================================================
print("--- 8. Защита от повторной загрузки ---")
created = STORE.add_album(AlbumDraft(
    title="Группа крови", year="1988",
    source_id="genius:82980",
    tracks=[TrackDraft(title="Группа крови",
                       artists=[ArtistDraft(name="Кино")])],
))
check("альбом с source_id создан",
      STORE.find_album_by_source("genius:82980") is created)
choice.open()
QTest.qWait(120)
win.toasts.clear()
choice.input_link.setText("https://genius.com/albums/Kino/Gruppa-krovi")
choice._try_load()
QTest.qWait(200)
check("диалог остался открыт", choice.isVisible())
check("тост «уже создан»",
      any("уже создан" in t.text for t in win.toasts.active))
choice.close_overlay()

# ============================================================
print("--- 9. Страница альбома: «Создано с помощью Genius» ---")
check("логотип Genius в ресурсах", GENIUS_LOGO_PATH.exists())
win.open_album(created)
QTest.qWait(200)
page = win.album_page
check("строка источника — «Создано с помощью»",
      page.lbl_source.text() == "Создано с помощью")
check("иконка-логотип видима", page.source_icon.isVisible())
pixmap = page.source_icon.pixmap()
check("пиксмап логотипа ненулевой", pixmap is not None and not pixmap.isNull())
page.grab().save("/tmp/genius_source.png")

# ============================================================
print("--- 10. Браузерные заголовки и ошибка 403 ---")
ua = LAST_UA[-1] if LAST_UA else ""
check("User-Agent браузерный (Mozilla + Chrome)",
      ua.startswith("Mozilla/5.0") and "Chrome" in ua)


def _denied_message() -> str:
    try:
        genius.fetch_album("/denied")
    except GeniusError as exc:
        return str(exc)
    return ""


msg = _denied_message()
check("403 → «Genius отказал в доступе…», а не сетевой шаблон",
      "Genius отказал в доступе" in msg
      and msg != genius._NO_CONNECTION_MSG)
check("ни один запрос не ушёл без User-Agent", all(LAST_UA))

# ============================================================
QTest.qWait(100)
app.processEvents()
_server.shutdown()

print(f"\nИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    for name in FAIL:
        print(f"  FAIL: {name}")
    sys.exit(1)
