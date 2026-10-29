"""YouTube Music — третий источник автозаполнения альбома по ссылке.

Работает через внутренний API music.youtube.com (youtubei/v1/browse,
клиент WEB_REMIX): данные альбомов публичны, НИ ключей, НИ
регистрации не требуется — в отличие от Spotify сервис доступен и
из России (YouTube Music не заблокирован).

Как это устроено:
  • альбом на YouTube Music — это плейлист с id OLAK5uy_…; ссылка
    на страницу альбома использует ДРУГОЙ id (MPREb_…). Ссылка,
    которую вставляет пользователь (playlist?list=OLAK5uy_…),
    сначала конвертируется: плейлист запрашивается по адресу
    «VL» + id, а id страницы альбома берётся из колонки «альбом»
    у его же треков (в ответе плейлиста он есть у каждого трека);
  • затем запрашивается страница альбома (browse MPREb_…): шапка
    musicResponsiveHeaderRenderer — название, год (подзаголовок
    «Album • 1973»), обложка, исполнитель (straplineTextOne);
    полка musicShelfRenderer — треки (название, номер, длительность).

Ограничения API:
  • жанров YouTube Music не отдаёт — жанр остаётся пустым,
    пользователь выбирает сам (как у Spotify);
  • списка исполнителей у трека в ответе полки НЕТ структурно —
    он восстанавливается из accessibility-метки кнопки «Play
    <название> - <исполнители>» (так же делает ytmusicapi);
    если метки нет или она не разобралась — исполнитель альбома;
  • фиты в метке разделяются запятыми, «feat.» и «&» — разбор
   best-effort, в мастере всё можно поправить.

Ссылки: music.youtube.com/playlist?list=OLAK5uy_…, watch?v=…&list=…,
youtube.com / youtu.be / m.youtube.com с тем же list=, голый
OLAK5uy_… или MPREb_…. Обычные плейлисты (PL…/RD…) и watch-ссылки
без list= отклоняются с внятной ошибкой.

Ссылка запоминается за альбомом с префиксом «ytmusic:» (внутри —
OLAK5uy_…; он у альбома один и не меняется), поэтому у разных
сервисов id не конфликтуют.

Для тестов адрес переопределяется переменной окружения
MUSICRATING_YTMUSIC_API (локальный мок-сервер).
"""

import json
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtCore import QUrlQuery
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

API_BASE = os.environ.get(
    "MUSICRATING_YTMUSIC_API", "https://music.youtube.com"
)
REQUEST_TIMEOUT_MS = 15000
BROWSE_PATH = "/youtubei/v1/browse?prettyPrint=false"
# Версия клиента WEB_REMIX: если YouTube Music однажды перестанет
# отвечать на browse-запросы — обновить (свежая видна в запросах
# самого сайта music.youtube.com)
CLIENT_CONTEXT = {
    "context": {
        "client": {
            "clientName": "WEB_REMIX",
            "clientVersion": "1.20240403.01.00",
            "hl": "en",
            "gl": "US",
        }
    }
}

_LIST_ID = re.compile(r"^OLAK5uy_[A-Za-z0-9_-]+$")
_ALBUM_BROWSE_ID = re.compile(r"^MPREb_[A-Za-z0-9]+$")
# id страницы альбома, спрятанные в ответе плейлиста
_MPREF_IN_JSON = re.compile(r"MPREb_[A-Za-z0-9]+")
_YEAR_IN_RUNS = re.compile(r"^\d{4}$")
# разделители фит-исполнителей в accessibility-метке
_FEATURE_SPLIT = re.compile(r"\s*(?:,\s+|\s+&\s+|\s+feat\.?\s+|\s+with\s+)\s*")

NOT_ALBUM_MSG = (
    "Это не ссылка на альбом YouTube Music. Пример: "
    "https://music.youtube.com/playlist?list=OLAK5uy_…"
)
_NOT_PLAYLIST_MSG = (
    "Это обычный плейлист или микс, а не альбом. Откройте страницу "
    "альбома в YouTube Music и скопируйте её ссылку (list=OLAK5uy_…)."
)
_NO_CONNECTION_MSG = "Нет соединения с YouTube Music. Проверьте интернет."
UNEXPECTED_MSG = "YouTube Music вернул неожиданный ответ."


class YTMusicError(Exception):
    """Ошибка сети/ссылки/ответа API — текст виден пользователю."""


@dataclass
class YTMusicTrack:
    """Трек из ответа YouTube Music: название + имена исполнителей."""

    title: str
    artists: list[str] = field(default_factory=list)


@dataclass
class YTMusicAlbum:
    """Данные альбома, полученные с YouTube Music (см. fetch_album)."""

    title: str = ""
    year: str = ""
    genre: str = ""   # жанров у источника нет — всегда пусто
    cover_url: str | None = None
    artist_names: list[str] = field(default_factory=list)  # авторы альбома
    tracks: list[YTMusicTrack] = field(default_factory=list)
    photos: dict[str, str] = field(default_factory=dict)   # имя → URL фото
    album_id: str = ""   # «ytmusic:<OLAK5uy_…>» — запоминается у
                         # созданного альбома, чтобы ссылку нельзя было
                         # использовать второй раз

    def download_image(self, url: str | None) -> str | None:
        """Скачать картинку этого источника (у DeezerAlbum/SpotifyAlbum
        такой же метод — код мастера не зависит от сервиса)."""
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
    return "Не удалось связаться с YouTube Music. Проверьте интернет."


def _post_json(browse_id: str) -> dict:
    """POST youtubei/v1/browse с browseId → разобранный JSON."""
    body = json.dumps({**CLIENT_CONTEXT, "browseId": browse_id}).encode(
        "utf-8"
    )
    request = QNetworkRequest(QUrl(API_BASE + BROWSE_PATH))
    request.setTransferTimeout(REQUEST_TIMEOUT_MS)
    request.setHeader(
        QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
    )

    loop = QEventLoop()
    reply = _manager().post(request, body)
    reply.finished.connect(loop.quit)
    loop.exec()

    error = reply.error()
    status = reply.attribute(
        QNetworkRequest.Attribute.HttpStatusCodeAttribute
    )
    raw = bytes(reply.readAll())
    final_url = reply.url().toString()
    reply.deleteLater()

    # сетевой сбой: ответа нет вовсе (HTTP-ошибка отдаёт тело)
    if error != QNetworkReply.NetworkError.NoError and status is None:
        raise YTMusicError(_friendly_error(reply))
    # редирект на страницу согласия/капчи (нет JSON) — характерно
    # для заблокированных/подозрительных сетей
    if final_url and "consent" in final_url:
        raise YTMusicError(_NO_CONNECTION_MSG)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise YTMusicError(UNEXPECTED_MSG) from None
    if not isinstance(payload, dict):
        raise YTMusicError(UNEXPECTED_MSG)
    return payload


# --- Разбор ссылок ---------------------------------------------------------
def resolve_list_id(link_text: str) -> str:
    """id альбома (OLAK5uy_… или MPREb_…) из ссылки YouTube Music.

    Не ссылка на альбом → YTMusicError с текстом для пользователя.
    """
    text = link_text.strip()
    if not text:
        raise YTMusicError("Вставьте ссылку на альбом YouTube Music.")

    # голый id (скопировали прямо из адресной строки)
    if _LIST_ID.match(text) or _ALBUM_BROWSE_ID.match(text):
        return text

    if "://" not in text:
        text = "https://" + text
    parsed = QUrl(text)
    if not parsed.isValid() or not parsed.host():
        raise YTMusicError(NOT_ALBUM_MSG)

    host = parsed.host().casefold()
    is_youtube = (
        host == "youtu.be"
        or host == "music.youtube.com"
        or host == "youtube.com"
        or host.endswith(".youtube.com")
    )
    if not is_youtube:
        raise YTMusicError(NOT_ALBUM_MSG)

    list_id = QUrlQuery(parsed).queryItemValue("list").strip()
    if not list_id:
        # watch?v=… без альбомного list= — просто трек/клип
        raise YTMusicError(NOT_ALBUM_MSG)
    if _LIST_ID.match(list_id) or _ALBUM_BROWSE_ID.match(list_id):
        return list_id
    # PL…/RD…/UL…/OL… — плейлисты, миксы, «ваш лайк» — не альбомы
    raise YTMusicError(_NOT_PLAYLIST_MSG)


# --- Разбор ответов ---------------------------------------------------------
def _find_all(node, key: str) -> list:
    """Все значения dict-ключа key на любой глубине (форма ответа
    меняется между версиями API — ищем по имени, не по пути)."""
    found: list = []
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                found.append(value)
            found.extend(_find_all(value, key))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_all(item, key))
    return found


def _runs_text(node: dict, *path: str) -> str:
    """Склеенный текст runs по пути (пустые пропускаются)."""
    current = node
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part) or {}
    runs = current.get("runs") or [] if isinstance(current, dict) else []
    return "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict)
    ).strip()


def _best_thumbnail(header: dict) -> str | None:
    """URL самой крупной обложки из шапки альбома."""
    renderers = _find_all(header, "musicThumbnailRenderer")
    for renderer in renderers:
        thumbnails = (
            (renderer or {}).get("thumbnail") or {}
        ).get("thumbnails") or []
        candidates = [
            thumb for thumb in thumbnails
            if isinstance(thumb, dict) and thumb.get("url")
        ]
        if candidates:
            best = max(
                candidates,
                key=lambda thumb: thumb.get("width") or 0,
            )
            return str(best["url"])
    return None


def _album_artist(header: dict) -> str:
    """Исполнитель альбома: straplineTextOne (строка над треками);
    для старой шапки (musicDetailHeaderRenderer) — вторая часть
    подзаголовка «Album • Artist • 1973»."""
    name = _runs_text(header, "straplineTextOne")
    if name:
        return name
    subtitle = header.get("subtitle") or {}
    runs = subtitle.get("runs") or []
    if len(runs) == 1:
        parts = [
            part.strip()
            for part in str(runs[0].get("text") or "").split("•")
        ]
        if len(parts) >= 3 and parts[1]:
            return parts[1]
    return ""


def _album_year(header: dict) -> str:
    """Год: отдельный фрагмент подзаголовка («Album • 1973») или
    часть строки-подзаголовка старой шапки."""
    subtitle = header.get("subtitle") or {}
    for run in subtitle.get("runs") or []:
        text = str(run.get("text") or "").strip()
        if _YEAR_IN_RUNS.match(text):
            return text
    for run in subtitle.get("runs") or []:
        for part in str(run.get("text") or "").split("•"):
            part = part.strip()
            if _YEAR_IN_RUNS.match(part):
                return part
    return ""


def _artists_from_label(label: str, title: str, fallback: str) -> list[str]:
    """Имена исполнителей трека из accessibility-метки кнопки Play.

    Метка вида «Play <название> - <исполнители>» (Pause… — то же
    самое). Если метки нет или название не совпало — исполнитель
    альбома. Разделители фитов: запятая, «feat.», «&», «with».
    """
    text = (label or "").strip()
    for prefix in ("Play ", "Pause "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    rest = ""
    if title and text.startswith(title):
        rest = text[len(title):]
        rest = rest.strip(" -–—")
    if not rest:
        return [fallback] if fallback else []
    names: list[str] = []
    for name in _FEATURE_SPLIT.split(rest):
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names or ([fallback] if fallback else [])


def _parse_album(payload: dict, source_id: str) -> "YTMusicAlbum":
    """Ответ страницы альбома → YTMusicAlbum."""
    headers = _find_all(payload, "musicResponsiveHeaderRenderer") or \
        _find_all(payload, "musicDetailHeaderRenderer")
    if not headers:
        raise YTMusicError(
            "YouTube Music не нашёл такой альбом (или это плейлист, "
            "а не альбом)."
        )
    header = headers[0]

    title = _runs_text(header, "title")
    if not title:
        raise YTMusicError("YouTube Music не вернул название альбома.")
    year = _album_year(header)
    artist = _album_artist(header)
    cover = _best_thumbnail(header)

    tracks: list[YTMusicTrack] = []
    album_olak = ""
    for shelf in _find_all(payload, "musicShelfRenderer"):
        for item in shelf.get("contents") or []:
            if not isinstance(item, dict):
                continue
            renderer = item.get("musicResponsiveListItemRenderer")
            if not isinstance(renderer, dict):
                continue
            columns = renderer.get("flexColumns") or []
            if not columns:
                continue
            first_col = columns[0].get(
                "musicResponsiveListItemFlexColumnRenderer"
            ) or {}
            runs = ((first_col.get("text") or {}).get("runs")) or []
            track_title = "".join(
                str(run.get("text") or "")
                for run in runs if isinstance(run, dict)
            ).strip()
            if not track_title:
                continue

            # исполнители: accessibility-метка кнопки Play
            label = ""
            overlays = _find_all(renderer, "accessibilityPlayData")
            if overlays:
                label = str(
                    ((overlays[0] or {}).get("accessibilityData") or {})
                    .get("label") or ""
                )
            names = _artists_from_label(label, track_title, artist)

            # OLAK этого альбома — в watch-ссылке трека
            if not album_olak:
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    endpoint = run.get("navigationEndpoint") or {}
                    playlist = ((endpoint.get("watchEndpoint") or {})
                                .get("playlistId") or "")
                    if playlist.startswith("OLAK5uy_"):
                        album_olak = playlist
                        break

            tracks.append(YTMusicTrack(title=track_title, artists=names))
        break   # первая полка с треками — остальные секции не нужны

    if source_id.startswith("OLAK5uy_"):
        final_id = f"ytmusic:{source_id}"
    elif album_olak:
        final_id = f"ytmusic:{album_olak}"
    else:
        final_id = f"ytmusic:{source_id}"

    return YTMusicAlbum(
        title=title,
        year=year,
        genre="",
        cover_url=cover,
        artist_names=[artist] if artist else [],
        tracks=tracks,
        photos={},
        album_id=final_id,
    )


# --- Публичный интерфейс --------------------------------------------------
def fetch_album(list_or_browse_id: str) -> YTMusicAlbum:
    """id (OLAK5uy_…/MPREb_…) → данные альбома.

    OLAK5uy_… (плейлист-альбом) конвертируется в id страницы
    альбома одним запросом плейлиста: у каждого его трека в колонке
    «альбом» уже лежит нужный MPREb_….
    """
    source_id = (list_or_browse_id or "").strip()
    if _LIST_ID.match(source_id):
        playlist_payload = _post_json("VL" + source_id)
        matches = _MPREF_IN_JSON.findall(json.dumps(playlist_payload))
        if not matches:
            raise YTMusicError(_NOT_PLAYLIST_MSG)
        browse_id = Counter(matches).most_common(1)[0][0]
    elif _ALBUM_BROWSE_ID.match(source_id):
        browse_id = source_id
    else:
        raise YTMusicError(NOT_ALBUM_MSG)

    payload = _post_json(browse_id)
    return _parse_album(payload, source_id)


def load_album_from_link(link_text: str) -> YTMusicAlbum:
    """Ссылка → данные альбома (разобрать ссылку + запросить API)."""
    album_id = resolve_list_id(link_text)
    return fetch_album(album_id)


def save_image_bytes(raw: bytes) -> str | None:
    """Сохранить скачанную картинку в data/covers (путь от корня)."""
    from app.store import COVERS_DIR, DATA_DIR  # локальный импорт

    if not raw:
        return None
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
    loop = QEventLoop()
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(REQUEST_TIMEOUT_MS)
    reply = _manager().get(request)
    reply.finished.connect(loop.quit)
    loop.exec()

    ok = reply.error() == QNetworkReply.NetworkError.NoError
    raw = bytes(reply.readAll()) if ok else b""
    reply.deleteLater()
    return save_image_bytes(raw)
