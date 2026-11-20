"""Яндекс Музыка — источник автозаполнения альбома по ссылке.

Официального публичного API с ключами у Яндекс Музыки нет
(партнёрский интерфейс — только по договору). Используется
ВНУТРЕННИЙ API официальных приложений (api.music.yandex.net):
данные альбомов публичны и отдаются БЕЗ всякой авторизации —
ни ключей, ни регистрации не требуется (как у Deezer). Достаточно
заголовка клиента X-Yandex-Music-Client, под которым ходят сами
приложения Яндекса.

Особенность сервиса: Яндекс Музыка работает только в России и
нескольких странах СНГ — на запросы из других стран API отвечает
HTTP 451 «Unavailable For Legal Reasons». Пользователю из России
это не мешает; если запрос ушёл «из-за границы» (или включён
зарубежный VPN) — показывается понятная ошибка, а не сетевой
шаблон.

Один запрос GET /albums/<id>/with-tracks даёт всё сразу: шапку
альбома (название, версия издания, год, жанр, обложка coverUri),
исполнителей альбома и треки с ПОЛНЫМ списком исполнителей каждого
трека (главный артист + фиты, в порядке приложения) — дозапросов
по трекам, в отличие от Deezer, не нужно. Фото исполнителей в
ответе нет — их, как и у Genius, фоново дозагружает ArtBackfiller
с Deezer. Поле «версия издания» у альбома/трека («Deluxe», «Live»)
дописывается к названию в скобках — как у Deezer/Spotify в одном
поле; пользователь может поправить в мастере.

Ссылки: music.yandex.ru|by|kz|uz|com/album/<id> (в том числе
ссылка на конкретный трек /album/<id>/track/<tid> — берётся
альбом) и голый числовой id. Плейлисты (/users/…/playlists/…),
страницы исполнителей и подкасты отклоняются с внятной ошибкой.

Ссылка запоминается за альбомом с префиксом «yandex:» — id разных
сервисов не конфликтуют.

Для тестов адрес API переопределяется переменной окружения
MUSICRATING_YANDEX_API (локальный мок-сервер).
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

API_BASE = os.environ.get(
    "MUSICRATING_YANDEX_API", "https://api.music.yandex.net"
)
REQUEST_TIMEOUT_MS = 12000
# Заголовок клиента: под ним к API ходят официальные приложения —
# без него часть ответов API может отличаться/отклоняться
_CLIENT_HEADER = (b"X-Yandex-Music-Client", b"YandexMusicAndroid/240236")

_ALBUM_PATH = re.compile(r"/album/(\d+)")
# региональные домены Яндекс Музыки (другие хосты *.yandex.ru —
# почта, диск и т.п. — альбомами не являются)
_HOST_RE = re.compile(r"music\.yandex\.(ru|by|kz|uz|com|tr)")

NOT_ALBUM_MSG = (
    "Это не ссылка на альбом Яндекс Музыки. Пример: "
    "https://music.yandex.ru/album/123456"
)
_PODCAST_MSG = (
    "Это подкаст, а не музыкальный альбом — подкасты не "
    "поддерживаются."
)
_NO_CONNECTION_MSG = "Нет соединения с Яндекс Музыкой. Проверьте интернет."
_GEO_MSG = (
    "Яндекс Музыка недоступна из вашей страны — сервис работает "
    "только в России и странах СНГ. Отключите зарубежный VPN и "
    "попробуйте снова."
)
_NOT_FOUND_MSG = "Яндекс Музыка не нашла такой альбом."
UNEXPECTED_MSG = "Яндекс Музыка вернула неожиданный ответ."


class YandexMusicError(Exception):
    """Ошибка сети/ссылки/ответа API — текст показывается пользователю."""


@dataclass
class YandexMusicTrack:
    """Трек из ответа Яндекс Музыки: название + имена исполнителей."""

    title: str
    artists: list[str] = field(default_factory=list)
    track_id: str = ""
    base_title: str = ""
    duration_ms: int = 0


@dataclass
class YandexMusicAlbum:
    """Данные альбома, полученные с Яндекс Музыки (см. fetch_album)."""

    title: str = ""
    year: str = ""
    genre: str = ""
    cover_url: str | None = None
    artist_names: list[str] = field(default_factory=list)  # авторы альбома
    tracks: list[YandexMusicTrack] = field(default_factory=list)
    photos: dict[str, str] = field(default_factory=dict)   # имя → URL фото
    album_id: str = ""   # «yandex:<id>» — запоминается у созданного
                         # альбома, чтобы ссылку нельзя было использовать
                         # второй раз

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


def _status_of(reply: QNetworkReply) -> int | None:
    return reply.attribute(
        QNetworkRequest.Attribute.HttpStatusCodeAttribute
    )


def _friendly_error(reply: QNetworkReply) -> str:
    """Понятный текст по коду ответа (сетевой сбой или HTTP-статус)."""
    status = _status_of(reply)
    code = reply.error()
    if status is None or status == 0:
        # HTTP-ответа нет вовсе — сетевая проблема
        if code in (
            QNetworkReply.NetworkError.ConnectionRefusedError,
            QNetworkReply.NetworkError.HostNotFoundError,
            QNetworkReply.NetworkError.TimeoutError,
            QNetworkReply.NetworkError.TemporaryNetworkFailureError,
            QNetworkReply.NetworkError.NetworkSessionFailedError,
            QNetworkReply.NetworkError.UnknownNetworkError,
        ):
            return _NO_CONNECTION_MSG
        return "Не удалось связаться с Яндекс Музыкой. Проверьте интернет."
    if status == 451:
        return _GEO_MSG
    if status == 404:
        return _NOT_FOUND_MSG
    if code in (
        QNetworkReply.NetworkError.AuthenticationRequiredError,
        QNetworkReply.NetworkError.ContentAccessDenied,
        QNetworkReply.NetworkError.ContentOperationNotPermittedError,
    ):
        return "Яндекс Музыка отказала в доступе к этому адресу."
    return "Не удалось связаться с Яндекс Музыкой. Проверьте интернет."


def _get_json(url: str) -> dict:
    """Синхронный GET с заголовком клиента → разобранный JSON.

    HTTP-ошибки (404/451/…) отдают JSON с описанием ошибки в теле —
    читаем тело и до статуса ошибки, чтобы показать понятный текст
    вместо сетевого шаблона.
    """
    loop = QEventLoop()
    reply = _manager().get(_json_request(url))
    reply.finished.connect(loop.quit)
    loop.exec()
    return _read_json(reply)


def _json_request(url: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(REQUEST_TIMEOUT_MS)
    request.setRawHeader(_CLIENT_HEADER[0], _CLIENT_HEADER[1])
    return request


def _read_json(reply: QNetworkReply) -> dict:
    error = reply.error()
    raw = bytes(reply.readAll())
    reply.deleteLater()

    # сетевой сбой: HTTP-ответа нет вовсе (тело пустое или мусор)
    if error != QNetworkReply.NetworkError.NoError and not raw:
        raise YandexMusicError(_friendly_error(reply))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # HTTP-ошибка без JSON — понятный текст по статусу;
        # «успешный» ответ без JSON — неожиданный формат
        if error != QNetworkReply.NetworkError.NoError:
            raise YandexMusicError(_friendly_error(reply)) from None
        raise YandexMusicError(UNEXPECTED_MSG) from None
    if not isinstance(payload, dict):
        raise YandexMusicError(UNEXPECTED_MSG)
    # ошибки API приходят и в теле HTTP-ответа ({"error": {...}})
    if isinstance(payload.get("error"), dict):
        name = str(payload["error"].get("name") or "").casefold()
        if "not-found" in name or "not found" in name:
            raise YandexMusicError(_NOT_FOUND_MSG)
        if "unavailable for legal" in name:
            raise YandexMusicError(_GEO_MSG)
        message = payload["error"].get("message") or payload["error"].get("name")
        raise YandexMusicError(f"Яндекс Музыка: {message or 'ошибка запроса'}.")
    if error != QNetworkReply.NetworkError.NoError:
        # HTTP-ошибка, но тело — не описание ошибки API
        raise YandexMusicError(_friendly_error(reply))
    return payload


# --- Разбор ссылок ---------------------------------------------------------
def is_yandex_music_host(host: str) -> bool:
    """Хост Яндекс Музыки (music.yandex.ru|by|kz|uz|com|tr).

    Прочие хосты *.yandex.* (почта, диск, афиша…) — не музыка.
    """
    return bool(_HOST_RE.fullmatch((host or "").casefold()))


def resolve_album_id(link_text: str) -> str:
    """id альбома из ссылки Яндекс Музыки; не ссылка на альбом →
    YandexMusicError с текстом для пользователя."""
    text = link_text.strip()
    if not text:
        raise YandexMusicError("Вставьте ссылку на альбом Яндекс Музыки.")
    # голый id (скопировали прямо из адресной строки)
    if text.isdigit():
        return text
    if "://" not in text:
        text = "https://" + text
    parsed = QUrl(text)
    if not parsed.isValid() or not parsed.host():
        raise YandexMusicError(NOT_ALBUM_MSG)

    host = parsed.host().casefold()
    if not is_yandex_music_host(host):
        raise YandexMusicError(NOT_ALBUM_MSG)
    match = _ALBUM_PATH.search(parsed.path())
    if match:
        return match.group(1)
    # плейлисты (/users/…/playlists/…), исполнители, подборки — не альбомы
    raise YandexMusicError(NOT_ALBUM_MSG)


# --- Разбор ответа ---------------------------------------------------------
def _append_version(title: str, version: str) -> str:
    """Название с версией издания («Deluxe», «Live») в скобках.

    Пустая версия или уже входящая в название — без изменений.
    """
    version = (version or "").strip()
    if not version:
        return title
    if version.casefold() in (title or "").casefold():
        return title
    return f"{title} ({version})"


def _cover_url(entry: dict) -> str | None:
    """URL обложки из coverUri/ogImage: плейсхолдер %%size%% заменяется
    на крупный размер (как в приложении Яндекса)."""
    raw = entry.get("coverUri") or entry.get("ogImage") or ""
    raw = str(raw).strip()
    if not raw:
        return None
    if "%%size%%" in raw:
        raw = raw.replace("%%size%%", "400x400")
    return raw


def _dedup(names: list[str]) -> list[str]:
    """Список имён без повторов (порядок сохраняется)."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _parse_album(payload: dict, requested_id: str) -> "YandexMusicAlbum":
    """Ответ /albums/<id>/with-tracks → YandexMusicAlbum."""
    result = payload.get("result")
    if not isinstance(result, dict):
        raise YandexMusicError(UNEXPECTED_MSG)
    if str(result.get("type") or "album") == "podcast":
        raise YandexMusicError(_PODCAST_MSG)

    title = str(result.get("title") or "").strip()
    title = _append_version(title, str(result.get("version") or ""))
    if not title:
        raise YandexMusicError("Яндекс Музыка не вернула название альбома.")

    # жанр у Яндекса — английское имя («rock») — тот же словарь,
    # что и для Deezer; неизвестные жанры остаются как есть
    from app.services.deezer import map_genre  # локальный импорт

    genre = map_genre(str(result.get("genre") or ""))

    artist_names = _dedup([
        str(entry.get("name") or "").strip()
        for entry in result.get("artists") or []
        if isinstance(entry, dict)
    ])

    tracks: list[YandexMusicTrack] = []
    entries = result.get("tracks") or [
        entry for volume in result.get("volumes") or []
        if isinstance(volume, list) for entry in volume
    ]
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        base_title = str(raw.get("title") or "").strip()
        track_title = _append_version(base_title, str(raw.get("version") or ""))
        if not track_title:
            continue
        names = _dedup([
            str(entry.get("name") or "").strip()
            for entry in raw.get("artists") or []
            if isinstance(entry, dict)
        ])
        if not names:
            # у трека нет исполнителей (бывает у редких записей) —
            # остаются исполнители альбома
            names = list(artist_names)
        track_id = str(raw.get("id") or "")
        duration = raw.get("durationMs")
        tracks.append(YandexMusicTrack(
            title=track_title,
            artists=names,
            track_id=track_id if track_id.isascii() and track_id.isdigit() else "",
            base_title=base_title,
            duration_ms=duration if type(duration) is int and duration > 0 else 0,
        ))

    if not tracks:
        raise YandexMusicError(
            "В альбоме Яндекс Музыки не нашлось треков."
        )

    album_id = str(result.get("id") or "").strip() or requested_id
    return YandexMusicAlbum(
        title=title,
        year=str(result.get("year") or ""),
        genre=genre,
        cover_url=_cover_url(result),
        artist_names=artist_names,
        tracks=tracks,
        photos={},
        album_id=f"yandex:{album_id}",
    )


# --- Публичный интерфейс --------------------------------------------------
def fetch_album(album_id: str) -> YandexMusicAlbum:
    """id альбома (число) → данные альбома.

    Одного запроса /albums/<id>/with-tracks достаточно: в ответе и
    шапка альбома, и треки с полными списками исполнителей.
    """
    album_id = (album_id or "").strip()
    if not album_id.isdigit():
        raise YandexMusicError(NOT_ALBUM_MSG)
    payload = _get_json(f"{API_BASE}/albums/{album_id}/with-tracks")
    return _parse_album(payload, album_id)


def request_playback_album(album_id: str) -> QNetworkReply:
    if not (album_id.isascii() and album_id.isdigit()):
        raise YandexMusicError(NOT_ALBUM_MSG)
    return _manager().get(_json_request(f"{API_BASE}/albums/{album_id}/with-tracks"))


def read_playback_album(reply: QNetworkReply, album_id: str) -> YandexMusicAlbum:
    return _parse_album(_read_json(reply), album_id)


def load_album_from_link(link_text: str) -> YandexMusicAlbum:
    """Ссылка → данные альбома (разобрать ссылку + запросить API)."""
    album_id = resolve_album_id(link_text)
    return fetch_album(album_id)


def save_image_bytes(raw: bytes) -> str | None:
    """Сохранить скачанную картинку в data/covers (путь от корня)."""
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
