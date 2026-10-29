"""Публичный API Deezer — автоматическое заполнение альбома по ссылке.

Deezer не требует ни регистрации, ни ключей: достаточно id альбома,
который извлекается из вставленной ссылки (в том числе из короткой
link.deezer.com — финальный адрес узнаётся по редиректу).

Клиент синхронный (внутри QNetworkAccessManager + локальный
QEventLoop) и вызывается из UI-потока: пока идёт запрос, цикл
событий продолжает обрабатывать ввод и перерисовку, поэтому
интерфейс не замерзает.

Особенность API: в ответе /album/{id} у треков есть только главный
артист, поэтому для КАЖДОГО трека дополнительно запрашивается
/track/{id} — оттуда берутся ВСЕ исполнители (включая фитов) и их
фото. Запросы уходят пачкой параллельно и ждутся в одном цикле
событий; ошибка отдельного трека не отменяет загрузку альбома.

Базовый URL переопределяется переменной окружения
MUSICRATING_DEEZER_API — это используют тесты с локальным моком.
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

API_BASE = os.environ.get("MUSICRATING_DEEZER_API", "https://api.deezer.com")
REQUEST_TIMEOUT_MS = 12000

_ALBUM_PATH = re.compile(r"/album/(\d+)")
NOT_ALBUM_MSG = (
    "Это не ссылка на альбом Deezer. Пример: "
    "https://www.deezer.com/album/123456"
)
_NO_CONNECTION_MSG = "Нет соединения с Deezer. Проверьте интернет."


class DeezerError(Exception):
    """Ошибка сети/ссылки/ответа API — текст показывается пользователю."""


@dataclass
class DeezerTrack:
    """Трек из ответа Deezer: название + имена исполнителей."""

    title: str
    artists: list[str] = field(default_factory=list)


@dataclass
class DeezerAlbum:
    """Данные альбома, полученные с Deezer (см. fetch_album)."""

    title: str = ""
    year: str = ""
    genre: str = ""
    cover_url: str | None = None
    artist_names: list[str] = field(default_factory=list)  # авторы альбома
    tracks: list[DeezerTrack] = field(default_factory=list)
    photos: dict[str, str] = field(default_factory=dict)   # имя → URL фото
    album_id: str = ""   # id альбома — запоминается у созданного альбома,
                         # чтобы ссылку нельзя было использовать второй раз

    def download_image(self, url: str | None) -> str | None:
        """Скачать картинку этого источника (у SpotifyAlbum такой же
        метод — код мастера не зависит от сервиса)."""
        if not url:
            return None
        return download_image(url)


# Английские названия жанров Deezer → жанры приложения (русские)
_GENRE_MAP = {
    "rock": "Рок",
    "pop": "Поп",
    "rap/hip hop": "Хип-хоп",
    "hip hop": "Хип-хоп",
    "rap": "Хип-хоп",
    "electronic": "Электроника",
    "dance": "Электроника",
    "jazz": "Джаз",
    "classical": "Классика",
    "metal": "Метал",
    "punk": "Панк",
    "indie": "Инди",
    "alternative": "Альтернатива",
    "folk": "Фолк",
    "soul": "Соул",
    "r&b": "R&B",
    "reggae": "Регги",
    "country": "Кантри",
    "blues": "Блюз",
    "soundtrack": "Саундтрек",
}


def map_genre(raw: str) -> str:
    """Жанр Deezer → жанр приложения; неизвестные остаются как есть."""
    name = raw.strip()
    if not name:
        return ""
    return _GENRE_MAP.get(name.casefold(), name)


# --- Низкий уровень: синхронные запросы -----------------------------------
_nam: QNetworkAccessManager | None = None


def _manager() -> QNetworkAccessManager:
    global _nam
    if _nam is None:
        _nam = QNetworkAccessManager()
        # короткие ссылки link.deezer.com: автоматически идти по редиректам
        _nam.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )
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
        return "Deezer отказал в доступе к этому адресу."
    return "Не удалось связаться с Deezer. Проверьте интернет."


def _get_bytes(url: str) -> tuple[bytes, str]:
    """Синхронный GET: ждём завершения в локальном цикле событий.

    Возвращает (тело ответа, финальный URL — после редиректов).
    """
    loop = QEventLoop()
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(REQUEST_TIMEOUT_MS)
    reply = _manager().get(request)
    reply.finished.connect(loop.quit)
    loop.exec()

    error = reply.error()
    final_url = reply.url().toString()
    payload = bytes(reply.readAll())
    reply.deleteLater()
    if error != QNetworkReply.NetworkError.NoError:
        raise DeezerError(_friendly_error(reply))
    return payload, final_url


def _get_many_json(urls: list[str]) -> list[dict]:
    """Параллельные GET-запросы: один цикл событий на все ответы.

    Возвращает список той же длины: ошибка или не-JSON отдельного
    запроса даёт {} на его месте — падение одной детали не отменяет
    загрузку всего альбома.
    """
    if not urls:
        return []
    loop = QEventLoop()
    replies: list[QNetworkReply] = []
    for url in urls:
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        replies.append(_manager().get(request))
    remaining = len(replies)

    def _one_finished() -> None:
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            loop.quit()

    for reply in replies:
        reply.finished.connect(_one_finished)
    loop.exec()

    results: list[dict] = []
    for reply in replies:
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        raw = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()
        payload: dict = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict) and not parsed.get("error"):
                payload = parsed
        results.append(payload)
    return results


def _get_json(url: str) -> dict:
    raw, _ = _get_bytes(url)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DeezerError("Deezer вернул неожиданный ответ.") from None
    if not isinstance(payload, dict):
        raise DeezerError("Deezer вернул неожиданный ответ.")
    if payload.get("error"):
        message = payload["error"].get("message") or "ошибка запроса"
        raise DeezerError(f"Deezer: {message}.")
    return payload


def _resolve_short_link(url: str) -> str:
    """Финальный адрес короткой ссылки (редирект делает QNetworkManager)."""
    _, final_url = _get_bytes(url)
    return final_url


# --- Публичный интерфейс --------------------------------------------------
def resolve_album_id(link_text: str) -> str:
    """id альбома из ссылки Deezer; не ссылка на альбом → DeezerError."""
    text = link_text.strip()
    if not text:
        raise DeezerError("Вставьте ссылку на альбом Deezer.")
    if "://" not in text:
        text = "https://" + text
    parsed = QUrl(text)
    if not parsed.isValid() or not parsed.host():
        raise DeezerError(NOT_ALBUM_MSG)

    host = parsed.host().casefold()
    if host == "deezer.com" or host.endswith(".deezer.com"):
        if host.startswith("link."):
            parsed = QUrl(_resolve_short_link(text))
        match = _ALBUM_PATH.search(parsed.path())
        if match:
            return match.group(1)
        raise DeezerError(NOT_ALBUM_MSG)
    if host == "deezer.page.link":
        match = _ALBUM_PATH.search(QUrl(_resolve_short_link(text)).path())
        if match:
            return match.group(1)
        raise DeezerError(NOT_ALBUM_MSG)
    raise DeezerError(NOT_ALBUM_MSG)


def _artist_photo(entry: dict) -> str | None:
    """Лучший из доступных URL фото исполнителя."""
    return (
        entry.get("picture_xl")
        or entry.get("picture_big")
        or entry.get("picture_medium")
    )


def _track_contributors(raw_track: dict) -> tuple[list[str], dict[str, str]]:
    """Имена всех исполнителей трека + их фото из записи трека.

    Порядок — как в ответе API: главный артист первым, фиты после.
    Поле contributors отдаёт /track/{id}; некоторые ответы содержат
    artists (алиас); если нет ни того, ни другого — остаётся главный
    артист из artist.
    """
    names: list[str] = []
    photos: dict[str, str] = {}
    entries = raw_track.get("contributors") or raw_track.get("artists") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if name not in names:
            names.append(name)
        pic = _artist_photo(entry)
        if pic:
            photos.setdefault(name, pic)
    if not names:
        name = str((raw_track.get("artist") or {}).get("name") or "").strip()
        if name:
            names.append(name)
    return names, photos


def fetch_album(album_id: str) -> DeezerAlbum:
    """Запросить альбом у Deezer и собрать DeezerAlbum.

    Дозагрузка /track/{id}: в ответе /album/{id} у треков указан
    только главный артист, а фиты живут в деталях трека. Запросы
    уходят пачкой параллельно (см. _get_many_json).
    """
    data = _get_json(f"{API_BASE}/album/{album_id}")

    title = str(data.get("title") or "").strip()
    if not title:
        raise DeezerError("Deezer не вернул название альбома.")

    year = str(data.get("release_date") or "")[:4]
    cover = (
        data.get("cover_big")
        or data.get("cover_xl")
        or data.get("cover_medium")
    )
    genre = ""
    genres = (data.get("genres") or {}).get("data") or []
    if genres and isinstance(genres[0], dict):
        genre = map_genre(str(genres[0].get("name") or ""))

    photos: dict[str, str] = {}
    artist_names: list[str] = []
    contributors = data.get("contributors") or []
    if not contributors and isinstance(data.get("artist"), dict):
        contributors = [data["artist"]]
    for entry in contributors:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or name in artist_names:
            continue
        artist_names.append(name)
        pic = _artist_photo(entry)
        if pic:
            photos.setdefault(name, pic)

    tracks: list[DeezerTrack] = []
    need_details: list[int] = []   # индексы треков без списка исполнителей
    detail_ids: list[str] = []     # их id для /track/{id}
    for raw_track in (data.get("tracks") or {}).get("data") or []:
        if not isinstance(raw_track, dict):
            continue
        track_title = str(raw_track.get("title") or "").strip()
        if not track_title:
            continue
        names, more_photos = _track_contributors(raw_track)
        for name, pic in more_photos.items():
            photos.setdefault(name, pic)
        index = len(tracks)
        tracks.append(DeezerTrack(title=track_title, artists=names))
        track_id = str(raw_track.get("id") or "").strip()
        # В списке альбома один артист → у деталей могут быть фиты
        if len(names) <= 1 and track_id:
            need_details.append(index)
            detail_ids.append(track_id)

    if detail_ids:
        details = _get_many_json(
            [f"{API_BASE}/track/{track_id}" for track_id in detail_ids]
        )
        for index, payload in zip(need_details, details):
            if not payload:
                continue  # детали не скачались — остаётся главный артист
            names, more_photos = _track_contributors(payload)
            if names:
                tracks[index].artists = names
            for name, pic in more_photos.items():
                photos.setdefault(name, pic)

    return DeezerAlbum(
        title=title,
        year=year,
        genre=genre,
        cover_url=cover if isinstance(cover, str) else None,
        artist_names=artist_names,
        tracks=tracks,
        photos=photos,
        album_id=album_id,
    )


def load_album_from_link(link_text: str) -> DeezerAlbum:
    """Ссылка → данные альбома (разобрать ссылку + запросить API)."""
    album_id = resolve_album_id(link_text)
    return fetch_album(album_id)


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
        raw, _ = _get_bytes(url)
    except DeezerError:
        return None
    return save_image_bytes(raw)


def search_url(kind: str, query: str, limit: int = 5) -> str:
    """URL поиска Deezer (для фоновой дозагрузки картинок)."""
    return f"{API_BASE}/search/{kind}?{urlencode({'q': query, 'limit': limit})}"
