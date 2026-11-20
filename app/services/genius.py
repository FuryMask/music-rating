"""Страница альбома Genius — автоматическое заполнение альбома по ссылке.

Genius не даёт публичного API без регистрации приложения, поэтому
парсится САМА страница альбома (genius.com/albums/<исполнитель>/<альбом>).
Страница отдаётся сервером целиком (SSR), данные в ней лежат в двух
местах — используются обе стратегии, какая сработает:

  A. Скрипт window.__PRELOADED_STATE__ = JSON.parse("…") — большой
     JSON с данными альбома (включая треклист с исполнителями).
     Строка раскодируется как JSON-литерал, альбом ищется
     рекурсивно по устойчивому признаку (имя + список треков).
  B. HTML-маркеры, стабильные годами:
       og:title            — «Название by Исполнитель»;
       og:image            — обложка;
       metadata_unit       — «Release Date» → год;
       chart_row-content-title — названия треков по порядку;
       chart_row-non-title — исполнитель строки (если есть).

Признаки «(Ft. …)» и «(with …)» в названии трека разбираются в фитов
и соавторов и убираются из названия — как у треков из Deezer/Spotify.
Соавторы коллабораций («A & B» в строках треклиста) берутся из строк
разметки (ссылки-исполнители или текст) и дополняют JSON треклиста:
компактные записи состояния страницы соавторов часто не содержат.
Фото исполнителей страница альбома не содержит (их дозагружает
фоновый ArtBackfiller с Deezer). Жанра на Genius нет — поле остаётся
пустым.

ПОЛНЫЙ список исполнителей трека собирается из ТРЁХ источников.

1) JSON состояния страницы альбома (window.__PRELOADED_STATE__). На
   реальных страницах (проверено на Hurry Up Tomorrow) он: (а) обёрнут
   в ОДИНАРНЫЕ кавычки JSON.parse('…') с JS-эскейпами (\' в названиях
   с апострофами — json.loads это не ест, нужен JS-декодер); (б)
   треклист лежит в islands.albumAppearances — списком записей
   {song: …}, ключи camelCase (primaryArtists/featuredArtists),
   ПОЛНЫЙ список соисполнителей коллабораций — в primaryArtists
   («The Weeknd & Anitta»), а featuredArtists у них ПУСТ; (в) у каждой
   песни есть id и url её страницы. Старый формат (name + songs,
   snake_case) понимается по-прежнему.

2) Официальный Genius API (api.genius.com — НЕ за антиботом):
   GET /songs/<id> по id из состояния (primary_artist +
   featured_artists; продюсеров/авторов не берём). Client Access
   Token берётся из локального хранилища или MUSICRATING_GENIUS_TOKEN.
   Без него применяется разбор открытых страниц.

3) СТРАНИЦЫ САМИХ ТРЕКОВ (решение пользователя): у каждого трека
   открывается его страница (…-lyrics) — исполнители берутся из
   состояния страницы или подзаголовка под названием («The Weeknd &
   Anitta» — там они есть всегда). Самый надёжный источник; загрузка
   альбома становится дольше (запрос на каждый трек).

Сбои не ломают загрузку: трек остаётся с уже собранными
исполнителями; после нескольких неудач подряд соответствующий
источник пропускается. Продюсеры и авторы в треклист не попадают.

Клиент синхронный (QNetworkAccessManager + локальный QEventLoop) —
интерфейс не замерзает, как у остальных сервисов. Запросы идут с
браузерными заголовками (User-Agent, Accept, Accept-Language): без
User-Agent антибот Genius сразу отвечает 403 «отказано в доступе»
(тот же урок, что в spotify.py). Базовый URL переопределяется
переменной MUSICRATING_GENIUS_BASE — это используют тесты с
локальным моком (см. verify_task32).
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from html import unescape as _html_unescape
from urllib.parse import unquote

from PySide6.QtCore import QEventLoop, QIODevice, QSaveFile, QUrl
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

PAGE_BASE = os.environ.get("MUSICRATING_GENIUS_BASE", "https://genius.com")
REQUEST_TIMEOUT_MS = 12000

# Официальный API Genius: не за антиботом, авторизация Bearer-токеном
API_BASE = os.environ.get("MUSICRATING_GENIUS_API_BASE", "https://api.genius.com")
API_TIMEOUT_MS = 8000

# Подряд неудачных обращений к API, после которых обогащение трека
# прекращается (мертвый API не должен тормозить загрузку альбома)
_MAX_API_FAILS_IN_ROW = 3

# Антибот Genius мгновенно отвечает 403 на запросы без браузерного
# User-Agent (Qt по умолчанию его не отправляет) — как в spotify.py
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_BROWSER_HEADERS = (
    (b"User-Agent", BROWSER_UA.encode()),
    (
        b"Accept",
        b"text/html,application/xhtml+xml,application/xml;q=0.9,"
        b"image/avif,image/webp,*/*;q=0.8",
    ),
    (b"Accept-Language", b"en-US,en;q=0.9,ru;q=0.8"),
)

# /albums/<исполнитель>/<альбом> (слаги: латиница, цифры, дефисы, %XX)
_ALBUM_PATH = re.compile(r"/albums/[^/?#]+/[^/?#]+")
NOT_ALBUM_MSG = (
    "Это не ссылка на альбом Genius. Пример: "
    "https://genius.com/albums/Artist/Album"
)
_NO_CONNECTION_MSG = "Нет соединения с Genius. Проверьте интернет."
_PARSE_FAIL_MSG = (
    "Не удалось разобрать страницу альбома Genius. Попробуйте ещё раз."
)

# «(Ft. …)», «(feat. …)», «(featuring …)» в названии трека
_FEAT_RE = re.compile(
    r"\s*\((?:f(?:ea)?t(?:uring)?\.?|ft)\.?\s+([^)]+)\)\s*", re.IGNORECASE
)
# «(with …)», «(w/ …)» в КОНЦЕ названия — соавторы (стиль Genius для
# коллабораций «A & B»); только хвост, чтобы не задеть названия вида
# «… (… with …)» в середине
_WITH_RE = re.compile(
    r"\s*\((?:with|w/)\s+([^)]+)\)\s*$", re.IGNORECASE
)

# Страница оборачивает JSON в JS-строку: реальные страницы — в
# ОДИНАРНЫХ кавычках (JSON.parse('…')), старые — в двойных
_STATE_RE = re.compile(
    r"window\.__PRELOADED_STATE__\s*=\s*JSON\.parse\(\s*(?:"
    r'"((?:[^"\\]|\\.)*)"'
    r"|'((?:[^'\\]|\\.)*)'"
    r")\s*\)",
    re.DOTALL,
)
_OG_RE = re.compile(
    r'<meta[^>]+property=["\']og:(\w+)["\'][^>]+content=["\']([^"\']*)["\']'
    r"|<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+property=[\"']og:(\w+)[\"']",
    re.IGNORECASE,
)
_TITLE_H1_RE = re.compile(
    r'header_with_cover_art-primary_info-title[^>]*>\s*'
    r'(?:(?:<[^>]+>\s*)*)([^<]+?)\s*(?:<|\Z)',
    re.DOTALL,
)
_ARTIST_H1_RE = re.compile(
    r'header_with_cover_art-primary_info-primary_artist[^>]*>'
    r'(?:\s*<[^>]+>)*\s*([^<]+?)\s*(?:<|\Z)',
    re.DOTALL,
)
_RELEASE_RE = re.compile(
    r'metadata_unit-label[^>]*>\s*([^<]*?(?:Release|Дат)[^<]*?)\s*<.*?'
    r'metadata_unit-info[^>]*>\s*([^<]+?)\s*<',
    re.DOTALL | re.IGNORECASE,
)
# Строка треклиста: ссылка на страницу текста с заголовком внутри
_ROW_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*?-lyrics[^"\']*)["\'][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_ROW_TITLE_RE = re.compile(
    r'chart_row-content-title[^>]*>(.*?)</span>', re.DOTALL
)
# Блок исполнителей строки треклиста: внутри может быть несколько
# ссылок (по одной на имя) либо текст «A & B»; сам блок — как внутри
# ссылки-строки, так и сразу после неё (в HTML ссылка не может
# вкладываться в ссылку — в реальной разметке соавторы снаружи)
_NON_TITLE_RE = re.compile(
    r'chart_row-non-title[^>]*>(.*?)(?:</span>)', re.DOTALL
)
_LINK_TEXT_RE = re.compile(r'<a[^>]*>(.*?)</a>', re.DOTALL)
_YEAR_RE = re.compile(r"\d{4}")
# id песни из apiPath («/songs/9933283») — запасной источник
_SONG_ID_RE = re.compile(r"/songs/(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class GeniusError(Exception):
    """Ошибка сети/ссылки/разбора — текст показывается пользователю."""


@dataclass
class GeniusTrack:
    """Трек со страницы Genius: название + имена исполнителей.

    song_id — id песни в Genius (из JSON состояния страницы); по нему
    официальное API достраивает полный список исполнителей трека.
    """

    title: str
    artists: list[str] = field(default_factory=list)
    song_id: int | None = None
    url: str | None = None  # страница трека (…-lyrics) — источник исполнителей


@dataclass
class GeniusAlbum:
    """Данные альбома, полученные с Genius (см. fetch_album)."""

    title: str = ""
    year: str = ""
    genre: str = ""     # у Genius жанров нет — заполняется вручную
    cover_url: str | None = None
    artist_names: list[str] = field(default_factory=list)
    tracks: list[GeniusTrack] = field(default_factory=list)
    photos: dict[str, str] = field(default_factory=dict)  # всегда пусто:
    # страница альбома не содержит фото исполнителей (дозагрузка —
    # фоновым ArtBackfiller, см. services/backfill.py)
    album_id: str = ""  # «genius:<id>» — защита от повторной загрузки

    def download_image(self, url: str | None) -> str | None:
        """Скачать картинку (у DeezerAlbum/SpotifyAlbum такой же метод —
        код мастера не зависит от сервиса)."""
        if not url:
            return None
        return download_image(url)


# --- Низкий уровень: синхронные запросы -----------------------------------
_nam: QNetworkAccessManager | None = None


def _manager() -> QNetworkAccessManager:
    global _nam
    if _nam is None:
        _nam = QNetworkAccessManager()
    return _nam


def _friendly_error(reply: QNetworkReply) -> str:
    code = reply.error()
    if code in (
        QNetworkReply.NetworkError.ConnectionRefusedError,
        QNetworkReply.NetworkError.HostNotFoundError,
        QNetworkReply.NetworkError.TimeoutError,
        QNetworkReply.NetworkError.TemporaryNetworkFailureError,
        QNetworkReply.NetworkError.NetworkSessionFailedError,
        QNetworkReply.NetworkError.UnknownNetworkError,
    ):
        return _NO_CONNECTION_MSG
    if code in (
        QNetworkReply.NetworkError.AuthenticationRequiredError,
        QNetworkReply.NetworkError.ContentAccessDenied,
        QNetworkReply.NetworkError.ContentOperationNotPermittedError,
    ):
        return "Genius отказал в доступе к этому адресу. Попробуйте ещё раз позже."
    return "Не удалось связаться с Genius. Проверьте интернет."


def _get_bytes(
    url: str,
    extra_headers: tuple[tuple[bytes, bytes]] = (),
    timeout_ms: int = REQUEST_TIMEOUT_MS,
) -> bytes:
    """Синхронный GET: ждём завершения в локальном цикле событий."""
    loop = QEventLoop()
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(timeout_ms)
    for header, value in _BROWSER_HEADERS + extra_headers:
        request.setRawHeader(header, value)
    reply = _manager().get(request)
    reply.finished.connect(loop.quit)
    loop.exec()

    error = reply.error()
    payload = bytes(reply.readAll())
    reply.deleteLater()
    if error != QNetworkReply.NetworkError.NoError:
        raise GeniusError(_friendly_error(reply))
    return payload


# --- Публичный интерфейс: ссылка → путь страницы ---------------------------
def resolve_album_path(link_text: str) -> str:
    """Путь «/albums/<исполнитель>/<альбом>» из ссылки Genius.

    Подходит любой поддомен (genius.com, ru.genius.com, …); ссылки
    на песни («…-lyrics») и прочие страницы отклоняются.
    """
    text = link_text.strip()
    if not text:
        raise GeniusError("Вставьте ссылку на альбом Genius.")
    if "://" not in text:
        text = "https://" + text
    parsed = QUrl(text)
    if not parsed.isValid() or not parsed.host():
        raise GeniusError(NOT_ALBUM_MSG)

    host = parsed.host().casefold()
    if host != "genius.com" and not host.endswith(".genius.com"):
        raise GeniusError(NOT_ALBUM_MSG)

    path = unquote(parsed.path())
    match = _ALBUM_PATH.fullmatch(path.rstrip("/"))
    if not match:
        raise GeniusError(NOT_ALBUM_MSG)
    return path.rstrip("/")


# --- Разбор страницы -------------------------------------------------------
def _og_meta(html: str) -> dict[str, str]:
    """Словарь og:* мета-тегов (порядок атрибутов не важен)."""
    og: dict[str, str] = {}
    for prop_after, val_after, val_before, prop_before in _OG_RE.findall(html):
        key = prop_after or prop_before
        value = val_after or val_before
        if key and value:
            og.setdefault(key.casefold(), _html_unescape(value).strip())
    return og


def _split_title_artist(text: str) -> tuple[str, str]:
    """«Название by Исполнитель» (или «… от …» на локальных страницах)."""
    text = re.sub(r"\s*\|\s*Genius\s*$", "", text, flags=re.IGNORECASE)
    for sep in (" by ", " от "):
        idx = text.rfind(sep)
        if idx > 0:
            title = text[:idx].strip()
            artist = text[idx + len(sep):].strip()
            if title and artist:
                return title, artist
    return text.strip(), ""


def _clean_track_title(raw: str) -> tuple[str, list[str]]:
    """Сырое название строки треклиста → (чистое название, фиты).

    Убирает вложенные теги, хвост «Lyrics», суффиксы «(Ft. …)» и
    «(with …)» — исполнители из них становятся исполнителями трека.
    """
    text = _TAG_RE.sub("", raw)
    text = _html_unescape(text)
    text = re.sub(r"\s*Lyrics\s*$", "", text.strip(), flags=re.IGNORECASE)
    featured: list[str] = []

    def _take(match: re.Match) -> str:
        for name in re.split(r"[,;&]", match.group(1)):
            name = name.strip()
            if name:
                featured.append(name)
        return " "

    # Суффиксы могут идти цепочкой: «A (with B) (Ft. C)»
    changed = True
    while changed:
        changed = False
        stripped = _FEAT_RE.sub(_take, text)
        if stripped != text:
            text, changed = stripped, True
        tail = _WITH_RE.search(text)
        if tail is not None:
            _take(tail)
            text = text[: tail.start()] + " "
            changed = True
    return _SPACE_RE.sub(" ", text).strip(), featured


def _decode_js_string(body: str) -> str:
    """Тело JS-строки (между кавычками) → текст: эскейпы JS раскрываются.

    json.loads здесь не годится: в одинарных кавычках апострофы
    экранированы (\\') — в JSON такой эскейп недопустим, а названия
    треков сплошь с апострофами (Don't → Don\\'t).
    """
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "u" and i + 6 <= len(body):
                try:
                    out.append(chr(int(body[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if nxt == "x" and i + 4 <= len(body):
                try:
                    out.append(chr(int(body[i + 2:i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            out.append(
                {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(nxt, nxt)
            )
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_state(html: str) -> dict | None:
    """JSON из window.__PRELOADED_STATE__ (если он есть и читается)."""
    match = _STATE_RE.search(html)
    if not match:
        return None
    body = match.group(1) if match.group(1) is not None else match.group(2)
    try:
        state = json.loads(_decode_js_string(body))
    except (json.JSONDecodeError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _find_album_node(node) -> dict | None:
    """Рекурсивный поиск объекта альбома: имя + список треков-словарей."""
    if isinstance(node, dict):
        songs = node.get("songs") or node.get("tracks")
        name = node.get("name") or node.get("title")
        if (
            isinstance(name, str)
            and name.strip()
            and isinstance(songs, list)
            and songs
            and all(
                isinstance(song, dict) and isinstance(song.get("title"), str)
                for song in songs[:3]
            )
        ):
            return node
        for value in node.values():
            found = _find_album_node(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_album_node(item)
            if found is not None:
                return found
    return None


def _find_island_node(node) -> tuple[dict | None, list]:
    """«Остров» альбома нового формата: albumAppearances (+ album).

    Реальные страницы отдают треклист в islands.albumAppearances —
    списком записей {song: {...}, trackNumber, …}; сам альбом лежит
    рядом (islands.album). Возвращает (узел альбома, список записей)
    или (None, []), если формат не островной.
    """
    if isinstance(node, dict):
        apps = node.get("albumAppearances")
        if (
            isinstance(apps, list)
            and apps
            and all(
                isinstance(a, dict) and isinstance(a.get("song"), dict)
                for a in apps[:3]
            )
        ):
            album = node.get("album")
            return (album if isinstance(album, dict) else None), apps
        for value in node.values():
            found = _find_island_node(value)
            if found[1]:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_island_node(item)
            if found[1]:
                return found
    return None, []


def _names_of(entry) -> list[str]:
    """Имена артистов из записи JSON (строка, {"name": …} или список)."""
    if isinstance(entry, str):
        name = entry.strip()
        return [name] if name else []
    if isinstance(entry, list):
        names: list[str] = []
        for item in entry:
            for name in _names_of(item):
                if name not in names:
                    names.append(name)
        return names
    if not isinstance(entry, dict):
        return []
    name = str(entry.get("name") or "").strip()
    return [name] if name else []


def _tracks_from_state(entries: list) -> list[GeniusTrack]:
    """Треклист из JSON состояния (записи appearance или сами песни).

    Понимает оба формата Genius: старый (песня сразу в записи,
    snake_case: primary_artist, featured_artists) и новый «острова»
    (song внутри записи, camelCase: primaryArtists, featuredArtists).
    У соавторов коллабораций («The Weeknd & Anitta») на реальной
    странице полный список — в primaryArtists, а featuredArtists пуст.
    """
    tracks: list[GeniusTrack] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        song = entry.get("song")
        if not isinstance(song, dict):
            song = entry
        raw_title = str(
            song.get("title") or song.get("titleWithFeatured") or ""
        ).strip()
        if not raw_title:
            continue
        title, featured = _clean_track_title(raw_title)
        if not title:
            continue
        artists = _names_of(
            song.get("primaryArtist") or song.get("primary_artist")
            or song.get("artist")
        )
        lower = {a.casefold() for a in artists}
        # Соавторы/варианты ключей обоих форматов
        for key in ("primaryArtists", "primary_artists", "artists",
                    "featuredArtists", "featured_artists",
                    "featuring_artists", "featured_artist", "featuring"):
            for name in _names_of(song.get(key)):
                if name.casefold() not in lower:
                    artists.append(name)
                    lower.add(name.casefold())
        # Фиты из хвостов «(Ft. …)»/«(with …)» названия
        for name in featured:
            if name.casefold() not in lower:
                artists.append(name)
                lower.add(name.casefold())
        raw_id = song.get("id")
        if not isinstance(raw_id, int):
            api_path = str(song.get("apiPath") or song.get("api_path") or "")
            found = _SONG_ID_RE.search(api_path)
            raw_id = int(found.group(1)) if found else None
        track_url = song.get("url") or song.get("path") or None
        tracks.append(GeniusTrack(
            title=title,
            artists=artists,
            song_id=raw_id if isinstance(raw_id, int) else None,
            url=str(track_url) if track_url else None,
        ))
    return tracks


def _clean_name(raw: str) -> str:
    """Кусок разметки → чистое имя (без тегов, лишних пробелов)."""
    return _SPACE_RE.sub(" ", _html_unescape(_TAG_RE.sub("", raw))).strip()


def _row_artist_names(
    inner: str, window: str, album_artists: list[str]
) -> list[str]:
    """Имена исполнителей строки треклиста (может быть несколько).

    Сначала ищем блок исполнителей внутри ссылки-строки, затем в её
    окрестности до начала следующей строки (в реальной разметке ссылки
    на артистов стоят снаружи ссылки-строки). Ссылка = одно имя;
    без ссылок текст «A & B» разделяется по амперсанду (если текст —
    просто имя исполнителя альбома, деление не нужно: «Simon &
    Garfunkel» не разваливается).
    """
    for region in (inner, window):
        match = _NON_TITLE_RE.search(region)
        if not match:
            continue
        block = match.group(1)
        names = [
            name
            for name in (_clean_name(t) for t in _LINK_TEXT_RE.findall(block))
            if name and "©" not in name
        ]
        if not names:
            text = _clean_name(block)
            if text and "©" not in text:
                if text.casefold() in {a.casefold() for a in album_artists}:
                    names = [text]
                else:
                    names = [
                        part.strip()
                        for part in re.split(r"\s+&\s+", text)
                        if part.strip()
                    ]
        if names:
            return names
    return []


def _norm_title(title: str) -> str:
    return _SPACE_RE.sub(" ", title).strip().casefold()


def _merge_row_artists(
    tracks: list[GeniusTrack], rows: list[GeniusTrack]
) -> list[GeniusTrack]:
    """Дополняет треклист из JSON исполнителями строк HTML.

    Компактные записи треклиста в состоянии страницы могут не содержать
    соавторов коллабораций — в разметке строк они есть всегда.
    Сопоставление по очищенному названию; имена строки добавляются
    к JSON-именам без дублей (сравнение без учёта регистра).
    """
    if not rows or not tracks:
        return tracks
    by_title: dict[str, GeniusTrack] = {}
    for row in rows:
        by_title.setdefault(_norm_title(row.title), row)
    merged: list[GeniusTrack] = []
    for track in tracks:
        row = by_title.get(_norm_title(track.title))
        if row is not None:
            names = list(track.artists)
            for name in row.artists:
                if not any(name.casefold() == n.casefold() for n in names):
                    names.append(name)
            track = GeniusTrack(
                title=track.title,
                artists=names,
                song_id=track.song_id,
                url=track.url or row.url,
            )
        merged.append(track)
    return merged


def _tracks_from_html(html: str, album_artists: list[str]) -> list[GeniusTrack]:
    """Треклист из HTML-строк: заголовок + исполнители строки (если есть).

    Исполнители ищутся и внутри ссылки-строки, и после неё (окно до
    начала следующей строки) — разметка Genius встречается в обоих
    вариантах.
    """
    tracks: list[GeniusTrack] = []
    seen: set[str] = set()
    matches = list(_ROW_RE.finditer(html))
    for index, match in enumerate(matches):
        window_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(html)
        )
        window = html[match.end(): window_end]
        inner = match.group(2)
        title_match = _ROW_TITLE_RE.search(inner)
        if not title_match:
            continue
        title, featured = _clean_track_title(title_match.group(1))
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        artists = _row_artist_names(inner, window, album_artists)
        if not artists:
            artists = list(album_artists)
        for name in featured:
            if name not in artists:
                artists.append(name)
        tracks.append(GeniusTrack(
            title=title,
            artists=artists,
            url=match.group(1),
        ))
    return tracks


def parse_album_html(html: str, path: str) -> GeniusAlbum:
    """HTML страницы альбома → GeniusAlbum (стратегии A и B).

    Стратегия A — window.__PRELOADED_STATE__ (полные данные, включая
    исполнителей каждого трека); стратегия B — HTML-маркеры. Имена
    строк HTML ДОПОЛНЯЮТ JSON-исполнителей (соавторы коллабораций
    в компактных записях треклиста часто отсутствуют). Ни треков,
    ни строк → GeniusError с понятным текстом (например, когда
    Genius отдал анти-бот страницу без данных).
    """
    og = _og_meta(html)
    cover = og.get("image") or None

    title = artist = ""
    state = _parse_state(html)
    album_node = _find_album_node(state) if state else None
    island_album, island_apps = (
        _find_island_node(state) if state else (None, [])
    )
    # «Острова» (реальный формат) приоритетнее старого узла альбома
    data_node = island_album if island_album is not None else album_node
    if data_node is not None:
        title = str(
            data_node.get("name") or data_node.get("title") or ""
        ).strip()
        artist_names_state = _names_of(data_node.get("artist"))
        if not artist_names_state and data_node.get("artist_name"):
            artist_names_state = _names_of(data_node.get("artist_name"))
        if not artist_names_state:
            artist_names_state = _names_of(
                data_node.get("primaryArtists") or data_node.get("primary_artists")
            )
        artist = artist_names_state[0] if artist_names_state else ""
        if not cover:
            cover = (
                data_node.get("coverArtUrl") or data_node.get("cover_art_url")
                or None
            )
    if not title:
        match = _TITLE_H1_RE.search(html)
        if match:
            title = _html_unescape(_SPACE_RE.sub(" ", match.group(1))).strip()
    if not title and og.get("title"):
        title, artist = _split_title_artist(og["title"])
    if not artist:
        match = _ARTIST_H1_RE.search(html)
        if match:
            artist = _html_unescape(_SPACE_RE.sub(" ", match.group(1))).strip()
    if not artist and og.get("title"):
        _, artist = _split_title_artist(og["title"])

    year = ""
    if data_node is not None:
        for key, value in data_node.items():
            if "release" in key.casefold():
                found = _YEAR_RE.search(str(value))
                if found:
                    year = found.group(0)
                    break
    if not year:
        release = _RELEASE_RE.search(html)
        if release:
            found = _YEAR_RE.search(release.group(2))
            if found:
                year = found.group(0)

    if not title:
        raise GeniusError(_PARSE_FAIL_MSG)

    artist_names: list[str] = []
    if artist:
        artist_names.append(artist)

    if island_apps:
        tracks = _tracks_from_state(island_apps)
    elif album_node is not None:
        tracks = _tracks_from_state(
            album_node.get("songs") or album_node.get("tracks") or []
        )
    else:
        tracks = []
    rows = _tracks_from_html(html, artist_names)
    if tracks:
        tracks = _merge_row_artists(tracks, rows)
        for track in tracks:
            if not track.artists:
                track.artists = list(artist_names)
    else:
        tracks = rows

    if not tracks:
        # Страница-заглушка анти-бота или изменившаяся разметка
        raise GeniusError(_PARSE_FAIL_MSG)

    node_id = data_node.get("id") if data_node is not None else None
    album_id = f"genius:{node_id}" if node_id else f"genius:{path.lstrip('/')}"
    return GeniusAlbum(
        title=title,
        year=year,
        cover_url=cover,
        artist_names=artist_names,
        tracks=tracks,
        album_id=album_id,
    )


def fetch_album(album_path: str, *, catalog=None) -> GeniusAlbum:
    """Скачать страницу альбома, разобрать её и достроить исполнителей
    треков: официальное API (по id) + страницы самих треков."""
    url = album_path if album_path.startswith("http") else PAGE_BASE + album_path
    html = _get_bytes(url).decode("utf-8", errors="replace")
    album = parse_album_html(html, album_path)
    album = _enrich_performers(album, catalog=catalog)
    return _enrich_from_track_pages(album)


# --- Официальный API: полные исполнители трека ----------------------------
def _song_performers_from_payload(payload: bytes) -> list[str]:
    """Исполнители из JSON-ответа /songs/<id> (primary + featured)."""
    return _song_performers(json.loads(payload))


def _song_performers(data) -> list[str]:
    if not isinstance(data, dict):
        return []
    response = data.get("response")
    song = response.get("song") if isinstance(response, dict) else None
    if not isinstance(song, dict):
        return []
    names = _names_of(song.get("primary_artist"))
    lower = {n.casefold() for n in names}
    for name in _names_of(song.get("featured_artists")):
        if name.casefold() not in lower:
            names.append(name)
            lower.add(name.casefold())
    return names


def _credentials_path():
    from app.store import DATA_DIR

    return DATA_DIR / "genius_credentials.json"


def load_access_token() -> str:
    """Ключ из окружения или защищённого файла текущего пользователя Windows."""
    from app.services.windows_credentials import unprotect_secret

    override = os.environ.get("MUSICRATING_GENIUS_TOKEN", "").strip()
    if override:
        return override
    try:
        payload = json.loads(_credentials_path().read_text(encoding="utf-8"))
        return unprotect_secret(payload["access_token_dpapi"]).strip()
    except (OSError, ValueError, TypeError, KeyError):
        return ""


def save_access_token(token: str) -> None:
    """Сохранить ключ через Windows DPAPI с атомарной заменой файла."""
    from app.services.windows_credentials import protect_secret

    token = token.strip()
    if not token:
        raise ValueError("Введите ключ Genius API.")
    protected = json.dumps({"access_token_dpapi": protect_secret(token)}).encode("utf-8")
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(protected) != len(protected):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def fetch_song_performers(song_id: int, *, token: str | None = None) -> list[str]:
    """Полный список исполнителей трека из официального Genius API.

    GET /songs/<id> с Authorization: Bearer <Client Access Token>
    (api.genius.com не за антиботом). Бросает GeniusError при любой
    проблеме — фолбэк решает вызывающий код. Продюсеров и авторов
    ответ содержит тоже, но треклисту они не нужны.
    """
    token = load_access_token() if token is None else token
    if not token:
        raise GeniusError("Укажите ключ Genius API.")
    headers = ((b"Authorization", f"Bearer {token}".encode()), (b"Accept", b"application/json"))
    url = f"{API_BASE}/songs/{song_id}"
    raw = _get_bytes(url, extra_headers=headers, timeout_ms=API_TIMEOUT_MS)
    names = _song_performers_from_payload(raw)
    if not names:
        raise GeniusError("Genius API вернул ответ без исполнителей трека.")
    return names


def _enrich_performers(album: GeniusAlbum, *, catalog=None) -> GeniusAlbum:
    """Достроить исполнителей треков полными списками из API.

    На странице альбома соисполнители коллабораций («The Weeknd &
    Anitta») в разметке строк бывают не видны вовсе — API по id трека
    отдаёт полный список (основной + соисполнители). Имена API идут
    первыми (порядок как на Genius), имена со страницы дополняются
    без дублей. Любая ошибка трека/сети — трек остаётся с исполнителями
    со страницы; после нескольких неудач подряд обогащение прекращается,
    чтобы мертвый API не растягивал загрузку альбома на минуты.
    """
    token = load_access_token()
    if catalog is not None and not token:
        from app.services.music_catalog import CatalogError

        ids = list(dict.fromkeys(track.song_id for track in album.tracks if track.song_id))
        performers = {}
        for start in range(0, len(ids), 20):
            try:
                performers.update(catalog.request("genius-songs", ids=ids[start:start + 20]))
            except CatalogError:
                break  # Страницы треков остаются доступны при сбое API.
        for track in album.tracks:
            _merge_api_performers(track, _song_performers(performers.get(str(track.song_id))))
        return album
    if not token:
        return album
    failures = 0
    for track in album.tracks:
        if not track.song_id:
            continue
        try:
            api_names = fetch_song_performers(track.song_id, token=token)
        except (GeniusError, json.JSONDecodeError, ValueError):
            failures += 1
            if failures >= _MAX_API_FAILS_IN_ROW:
                break
            continue
        failures = 0
        _merge_api_performers(track, api_names)
    return album


def _merge_api_performers(track: GeniusTrack, api_names: list[str]) -> None:
    if api_names:
        names = list(api_names)
        for name in track.artists:
            if not any(name.casefold() == n.casefold() for n in names):
                names.append(name)
        track.artists = names


# --- Страницы треков: исполнители из самого трека --------------------------
_H2_BLOCK_RE = re.compile(
    r"header_with_cover_art-primary_info-primary_artist[^>]*>(.*?)</h2>",
    re.DOTALL,
)


def _find_song_node(node) -> dict | None:
    """Рекурсивный поиск узла песни: title + какой-то из ключей исполнителей."""
    keys = (
        "primaryArtist", "primary_artist", "primaryArtists", "primary_artists",
        "featuredArtists", "featured_artists",
    )
    if isinstance(node, dict):
        title = node.get("title")
        if isinstance(title, str) and title.strip() and any(node.get(k) for k in keys):
            return node
        for value in node.values():
            found = _find_song_node(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_song_node(item)
            if found is not None:
                return found
    return None


def _song_node_performers(song: dict) -> list[str]:
    """Исполнители из узла песни (состояние страницы трека)."""
    names = _names_of(
        song.get("primaryArtist") or song.get("primary_artist")
        or song.get("artist")
    )
    lower = {n.casefold() for n in names}
    for key in ("primaryArtists", "primary_artists", "featuredArtists",
                "featured_artists", "featuring_artists", "featuring"):
        for name in _names_of(song.get(key)):
            if name.casefold() not in lower:
                names.append(name)
                lower.add(name.casefold())
    _, featured = _clean_track_title(
        str(song.get("titleWithFeatured") or song.get("title") or "")
    )
    for name in featured:
        if name.casefold() not in lower:
            names.append(name)
            lower.add(name.casefold())
    return names


def _h2_artist_names(html: str) -> list[str]:
    """Исполнители из подзаголовка страницы трека (h2 под названием).

    На странице трека там каждый исполнитель — отдельная ссылка
    («The Weeknd & Anitta»); без ссылок — текст «A & B» по амперсанду.
    """
    match = _H2_BLOCK_RE.search(html)
    if not match:
        return []
    block = match.group(1)
    names = [
        name
        for name in (_clean_name(t) for t in _LINK_TEXT_RE.findall(block))
        if name and "©" not in name
    ]
    if not names:
        text = _clean_name(block)
        if text and "©" not in text:
            names = [p.strip() for p in re.split(r"\s+&\s+", text) if p.strip()]
    return names


def _track_performers_from_html(html: str) -> list[str]:
    """Исполнители со страницы трека: состояние, затем h2-подзаголовок."""
    state = _parse_state(html)
    song = _find_song_node(state) if state else None
    if song is not None:
        names = _song_node_performers(song)
        if names:
            return names
    return _h2_artist_names(html)


def fetch_track_performers(track_url: str) -> list[str]:
    """Полный список исполнителей со страницы трека (…-lyrics).

    Страница трека — самый надёжный источник: подзаголовок «The Weeknd
    & Anitta» есть всегда, даже когда страница альбома соавторов не
    показывает. Бросает GeniusError при проблемах сети/разбора —
    фолбэк решает вызывающий код.
    """
    url = track_url if track_url.startswith("http") else PAGE_BASE + track_url
    html = _get_bytes(url).decode("utf-8", errors="replace")
    names = _track_performers_from_html(html)
    if not names:
        raise GeniusError("На странице трека Genius не найдены исполнители.")
    return names


def _enrich_from_track_pages(album: GeniusAlbum) -> GeniusAlbum:
    """Достроить исполнителей каждого трека с его собственной страницы.

    Решение пользователя (Task 37): парсятся страницы ВСЕХ треков —
    это самый надёжный источник. Имена страницы дополняют уже собранные
    (страница альбома + API) без дублей. Сбой трека не ломает загрузку;
    после нескольких неудач подряд обход прекращается.
    """
    failures = 0
    for track in album.tracks:
        if not track.url:
            continue
        try:
            names = fetch_track_performers(track.url)
        except (GeniusError, ValueError):
            failures += 1
            if failures >= _MAX_API_FAILS_IN_ROW:
                break
            continue
        failures = 0
        for name in names:
            if not any(name.casefold() == n.casefold() for n in track.artists):
                track.artists.append(name)
    return album


def load_album_from_link(link_text: str, *, catalog=None) -> GeniusAlbum:
    """Ссылка → данные альбома (разобрать ссылку + скачать страницу)."""
    album_path = resolve_album_path(link_text)
    return fetch_album(album_path, catalog=catalog)


def save_image_bytes(raw: bytes) -> str | None:
    """Сохранить скачанную картинку в data/covers (путь от корня приложения)."""
    if not raw:
        return None
    # Локальный импорт: app.store не зависит от сервисов — цикла нет
    from app.store import COVERS_DIR, DATA_DIR

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.jpg"
        (COVERS_DIR / name).write_bytes(raw)
    except OSError:
        return None
    return f"data/covers/{name}"


def download_image(url: str) -> str | None:
    """Скачать картинку по URL в data/covers; путь или None при ошибке."""
    try:
        raw = _get_bytes(url)
    except GeniusError:
        return None
    return save_image_bytes(raw)
