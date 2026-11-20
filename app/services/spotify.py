"""Web API Spotify — второй источник автозаполнения альбома по ссылке.

Работает по тем же принципам, что и сервис Deezer (см. services/deezer.py):
синхронные запросы через QNetworkAccessManager + локальный QEventLoop
из UI-потока — интерфейс не замерзает.

Отличия от Deezer:
  • нужен OAuth-токен: Client Credentials (POST /api/token с
    Authorization: Basic base64(client_id:client_secret)). Токен живёт
    около часа и кэшируется в памяти процесса; новый запрашивается
    заранее (за 2 минуты до истечения);
  • ключи (Client ID / Client Secret) читаются из
    data/spotify_credentials.json (пишет окно ввода ключей) либо из
    переменных окружения MUSICRATING_SPOTIFY_CLIENT_ID /
    MUSICRATING_SPOTIFY_CLIENT_SECRET (приоритет — для тестов);
  • жанры у альбомов/артистов Spotify больше не отдаются (поле
    убрано из API в 2024) — жанр остаётся пустым, пользователь
    выбирает сам;
  • фото исполнителей приходят только из одиночных запросов
    /v1/artists/{id}: батч /v1/artists?ids= в Development Mode
    отвечает 403. Количество запросов ограничено (см. константу),
    у крупных сборок фото долетают не всем;
  • ссылки: open.spotify.com/album/{id} (в т.ч. с intl-сегментом),
    spotify:album:{id} и короткие spotify.link — короткая решается
    редиректом (браузерный User-Agent обязателен: без него сервер
    отвечает HTML-страницей, а не редиректом), с фолбэком на поиск
    адреса альбома прямо в HTML;
  • Spotify недоступен из России (сервис сам ушёл из РФ, домены
    блокируются): если у пользователя есть прокси/VPN с выходом
    не из РФ, его можно указать в окне ключей — ВСЕ запросы к
    Spotify (токен, API, обложки) пойдут через него, а Deezer и
    YouTube Music продолжат работать напрямую. Прокси хранится
    рядом с ключами в data/spotify_credentials.json (поле «proxy»).

Пагинация треков: в ответе /v1/albums/{id} сразу приходят до 50
треков; остальные добираются по абсолютной ссылке tracks.next.

Ссылка запоминается за альбомом с префиксом «spotify:» (id Deezer —
без префикса): один и тот же id у разных сервисов не конфликтует.

Для тестов адреса переопределяются переменными окружения:
MUSICRATING_SPOTIFY_API (каталог) и MUSICRATING_SPOTIFY_TOKEN_URL.
"""

import base64
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkProxy,
    QNetworkReply,
    QNetworkRequest,
)

API_BASE = os.environ.get(
    "MUSICRATING_SPOTIFY_API", "https://api.spotify.com"
)
TOKEN_URL = os.environ.get(
    "MUSICRATING_SPOTIFY_TOKEN_URL", "https://accounts.spotify.com/api/token"
)
REQUEST_TIMEOUT_MS = 12000
TOKEN_EXPIRY_MARGIN_S = 120     # обновлять токен заранее, с запасом
MAX_ARTIST_PHOTO_LOOKUPS = 30   # кап запросов фото (у сборок их десятки)
MAX_TRACK_PAGES = 10            # кап страниц треклиста (по 50 треков)
# spotify.link без браузерного UA отдаёт HTML вместо редиректа
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_ALBUM_PATH = re.compile(r"/album/([A-Za-z0-9]+)")
_URI_ALBUM = re.compile(r"^spotify:album:([A-Za-z0-9]+)\s*$", re.IGNORECASE)
# адрес альбома, спрятанный в теле короткой страницы (fallback)
_ALBUM_IN_BODY = re.compile(
    r"open\.spotify\.com/(?:intl-[^/\s\"'<>]+/)?album/([A-Za-z0-9]+)"
)

NOT_ALBUM_MSG = (
    "Это не ссылка на альбом Spotify. Пример: "
    "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"
)
_NO_CONNECTION_MSG = "Нет соединения со Spotify. Проверьте интернет."
# Тексты, означающие, что Spotify НЕ ДОСТУПЕН (сеть/блокировка, а не
# неверная ссылка/ключи) — окно создания по ним открывает страницу
# ключей с полем прокси
CONNECTION_MESSAGES = (
    _NO_CONNECTION_MSG,
    "Не удалось связаться со Spotify. Проверьте интернет.",
)
NO_CREDENTIALS_MSG = "Укажите ключи Spotify, чтобы загружать альбомы по ссылкам."
BAD_CREDENTIALS_MSG = (
    "Spotify не принял ключи: проверьте Client ID и Client Secret."
)
UNEXPECTED_MSG = "Spotify вернул неожиданный ответ."


class SpotifyError(Exception):
    """Ошибка сети/ссылки/ключей/ответа API — текст виден пользователю."""


# --- Ключи приложения -----------------------------------------------------
def credentials_path() -> Path:
    """Файл с ключами (переопределяется переменной окружения — тесты)."""
    override = os.environ.get("MUSICRATING_SPOTIFY_CREDENTIALS")
    if override:
        return Path(override)
    from app.store import DATA_DIR  # локальный импорт: без циклов

    return DATA_DIR / "spotify_credentials.json"


def load_credentials() -> tuple[str, str] | None:
    """(client_id, client_secret) или None, если ключей ещё нет.

    Переменные окружения сильнее файла — ими пользуются тесты.
    """
    env_id = os.environ.get("MUSICRATING_SPOTIFY_CLIENT_ID")
    env_secret = os.environ.get("MUSICRATING_SPOTIFY_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    try:
        payload = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    client_id = str(payload.get("client_id") or "").strip()
    if not client_id:
        return None
    if protected := payload.get("client_secret_dpapi"):
        from app.services.windows_credentials import unprotect_secret

        try:
            return client_id, unprotect_secret(protected)
        except (OSError, ValueError, TypeError):
            return None
    if client_secret := str(payload.get("client_secret") or "").strip():
        try:
            save_credentials(client_id, client_secret, str(payload.get("proxy") or ""))
        except OSError:
            return None
        return client_id, client_secret
    return None


def save_credentials(
    client_id: str,
    client_secret: str,
    proxy: str | None = None,
) -> None:
    """Сохранить ключи локально (файл не попадает в архив проекта).

    proxy: строка прокси или "" (напрямую); None — оставить прежнее
    значение (старые вызовы без прокси его не затирают).
    """
    from tempfile import NamedTemporaryFile

    from app.services.windows_credentials import protect_secret

    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "client_id": client_id.strip(),
        "client_secret_dpapi": protect_secret(client_secret.strip()),
        "proxy": load_proxy() if proxy is None else proxy.strip(),
    }
    with NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as stream:
        staged = Path(stream.name)
        try:
            json.dump(payload, stream, indent=2)
            stream.close()
            staged.replace(path)
        finally:
            stream.close()
            staged.unlink(missing_ok=True)


def load_proxy() -> str:
    """Прокси Spotify из файла ключей ("" — запросы идут напрямую)."""
    try:
        payload = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("proxy") or "").strip() if isinstance(payload, dict) else ""


# --- Прокси (для сетей, где Spotify заблокирован) --------------------------
# хост прокси: домен/IPv4/IPv6-в-скобках; QUrl принимает любую UTF-8
# строку как IDN-хост — отсекаем «мусор» руками
_PROXY_HOST = re.compile(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9\-.]*[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])"
)


def parse_proxy(text: str) -> tuple[QNetworkProxy | None, str]:
    """Строка прокси → QNetworkProxy.

    Понимает http://host:port, socks5://user:pass@host:port и
    сокращённую запись host:port (считается http). Пустая строка —
    напрямую: (None, ""). Не разобрали — (None, текст ошибки).
    """
    raw = (text or "").strip()
    if not raw:
        return None, ""
    if not raw.isascii():
        # QUrl превращает любую UTF-8 строку в punycode-хост (xn--…) —
        # кириллица и прочий «мусор» в адресе прокси недопустимы
        return None, "Прокси: укажите адрес, например http://127.0.0.1:8080."
    candidate = raw if "://" in raw else "http://" + raw
    url = QUrl(candidate)
    scheme = url.scheme().casefold()
    if scheme == "socks5":
        proxy_type = QNetworkProxy.ProxyType.Socks5Proxy
        default_port = 1080
    elif scheme in ("http", "https"):
        proxy_type = QNetworkProxy.ProxyType.HttpProxy
        default_port = 8080
    else:
        return None, "Прокси: поддерживаются http:// и socks5://."
    host = url.host()
    if not host or not _PROXY_HOST.match(host):
        return None, "Прокси: укажите адрес, например http://127.0.0.1:8080."
    port = url.port(default_port)
    if port <= 0:
        return None, "Прокси: укажите порт, например http://127.0.0.1:8080."
    proxy = QNetworkProxy(proxy_type, host, port)
    if url.userName():
        proxy.setUser(url.userName())
    if url.password():
        proxy.setPassword(url.password())
    return proxy, ""


_proxy: QNetworkProxy | None = None   # None — напрямую (как в системе)


def apply_proxy(text: str) -> str:
    """Направить ВСЕ запросы Spotify через прокси ("" — напрямую).

    Возвращает "" при успехе или текст ошибки (прокси не применён).
    Задаётся ДО первого запроса или меняет прокси на лету: менеджер
    у сервиса один — через него идут и токен, и API, и картинки.
    """
    global _proxy
    proxy, error = parse_proxy(text)
    if error:
        return error
    _proxy = proxy
    if _nam is not None:
        # QNetworkProxy() без аргументов — системное поведение по умолчанию
        _nam.setProxy(proxy if proxy is not None else QNetworkProxy())
    return ""


# --- Низкий уровень: синхронные запросы -----------------------------------
_nam: QNetworkAccessManager | None = None


def _manager() -> QNetworkAccessManager:
    global _nam
    if _nam is None:
        _nam = QNetworkAccessManager()
        # короткие ссылки: автоматически идти по редиректам
        _nam.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )
        if _proxy is not None:
            _nam.setProxy(_proxy)
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
        return "Spotify отказал в доступе к этому адресу."
    return "Не удалось связаться со Spotify. Проверьте интернет."


def _request(url: str, token: str | None = None) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setTransferTimeout(REQUEST_TIMEOUT_MS)
    if token:
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
    return request


def _get_bytes(
    url: str,
    token: str | None = None,
    browser_ua: bool = False,
    allow_http_error: bool = False,
) -> tuple[bytes, str]:
    """Синхронный GET: ждём завершения в локальном цикле событий.

    Возвращает (тело ответа, финальный URL — после редиректов).
    Сетевая ошибка (ответа нет вовсе) всегда даёт SpotifyError с
    понятным текстом. HTTP-ошибка (404/401/500) — тоже, КРОМЕ
    allow_http_error=True: тогда тело отдаётся вызывающему целиком
    (_get_json сам разберёт {"error": {...}} и покажет текст API).
    """
    loop = QEventLoop()
    request = _request(url, token)
    if browser_ua:
        request.setRawHeader(b"User-Agent", BROWSER_UA.encode())
    reply = _manager().get(request)
    reply.finished.connect(loop.quit)
    loop.exec()

    error = reply.error()
    status = reply.attribute(
        QNetworkRequest.Attribute.HttpStatusCodeAttribute
    )
    final_url = reply.url().toString()
    payload = bytes(reply.readAll())
    reply.deleteLater()

    if error != QNetworkReply.NetworkError.NoError and status is None:
        raise SpotifyError(_friendly_error(reply))   # настоящая сетевая ошибка
    if error != QNetworkReply.NetworkError.NoError and not allow_http_error:
        raise SpotifyError(_friendly_error(reply))   # 404/401/… без разбора
    return payload, final_url


def _get_many_json(urls: list[str], token: str | None = None) -> list[dict]:
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
        replies.append(_manager().get(_request(url, token)))
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


def _get_json(url: str, token: str | None = None) -> dict:
    raw, _ = _get_bytes(url, token, allow_http_error=True)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SpotifyError(UNEXPECTED_MSG) from None
    if not isinstance(payload, dict):
        raise SpotifyError(UNEXPECTED_MSG)
    if payload.get("error"):
        message = (payload["error"].get("message")
                   if isinstance(payload["error"], dict) else None)
        raise SpotifyError(f"Spotify: {message or 'ошибка запроса'}.")
    return payload


# --- Токен ----------------------------------------------------------------
_token: str | None = None
_token_expires_at: float = 0.0


def invalidate_token() -> None:
    """Забыть кэшированный токен (после смены ключей)."""
    global _token, _token_expires_at
    _token = None
    _token_expires_at = 0.0


def _fetch_token() -> tuple[str, int]:
    """Client Credentials: POST /api/token → (access_token, expires_in)."""
    creds = load_credentials()
    if creds is None:
        raise SpotifyError(NO_CREDENTIALS_MSG)
    client_id, client_secret = creds
    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")

    loop = QEventLoop()
    request = _request(TOKEN_URL)
    request.setRawHeader(b"Authorization", f"Basic {basic}".encode())
    request.setHeader(
        QNetworkRequest.KnownHeaders.ContentTypeHeader,
        "application/x-www-form-urlencoded",
    )
    body = urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    reply = _manager().post(request, body)
    reply.finished.connect(loop.quit)
    loop.exec()

    error = reply.error()
    status = reply.attribute(
        QNetworkRequest.Attribute.HttpStatusCodeAttribute
    )
    raw = bytes(reply.readAll())
    reply.deleteLater()

    # error() выставляется и при сетевом сбое, и при HTTP-ошибке
    # (400 → ProtocolInvalidOperationError и т.п.): тело читаем в
    # любом случае, сетевым сбоем считаем только ответ БЕЗ статуса
    if error != QNetworkReply.NetworkError.NoError and status is None:
        raise SpotifyError(_friendly_error(reply))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SpotifyError(UNEXPECTED_MSG) from None
    if not isinstance(payload, dict):
        raise SpotifyError(UNEXPECTED_MSG)
    if status == 400 or payload.get("error"):
        # invalid_client — неверные ключи (или не Web API в дашборде)
        raise SpotifyError(BAD_CREDENTIALS_MSG)
    token = str(payload.get("access_token") or "")
    try:
        expires_in = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    if not token:
        raise SpotifyError(UNEXPECTED_MSG)
    return token, expires_in


def _get_token() -> str:
    """Действующий токен из кэша или свежий запрос."""
    global _token, _token_expires_at
    if _token and time.monotonic() < _token_expires_at:
        return _token
    token, expires_in = _fetch_token()
    _token = token
    _token_expires_at = time.monotonic() + max(
        expires_in - TOKEN_EXPIRY_MARGIN_S, 60
    )
    return _token


# --- Публичный интерфейс --------------------------------------------------
def resolve_album_id(link_text: str) -> str:
    """id альбома из ссылки Spotify; не ссылка на альбом → SpotifyError."""
    text = link_text.strip()
    if not text:
        raise SpotifyError("Вставьте ссылку на альбом Spotify.")
    if "://" not in text and not text.casefold().startswith("spotify:"):
        text = "https://" + text

    uri = _URI_ALBUM.match(text)
    if uri:
        return uri.group(1)

    parsed = QUrl(text)
    if not parsed.isValid() or not parsed.host():
        raise SpotifyError(NOT_ALBUM_MSG)

    host = parsed.host().casefold()
    if host.endswith("spotify.com"):
        match = _ALBUM_PATH.search(parsed.path())
        if match:
            return match.group(1)
        raise SpotifyError(NOT_ALBUM_MSG)
    if host in ("spotify.link", "spotify.app.link") or host.endswith(
        ".spotify.link"
    ):
        # короткая ссылка: редирект (браузерный UA!) + фолбэк на тело
        final_url, body = _resolve_short_link(text)
        match = _ALBUM_PATH.search(QUrl(final_url).path())
        if match:
            return match.group(1)
        match = _ALBUM_IN_BODY.search(body.decode("utf-8", errors="ignore"))
        if match:
            return match.group(1)
        raise SpotifyError(NOT_ALBUM_MSG)
    raise SpotifyError(NOT_ALBUM_MSG)


def _resolve_short_link(url: str) -> tuple[str, bytes]:
    """Финальный адрес и тело короткой ссылки (редирект делает QNAM)."""
    return _get_bytes(url, browser_ua=True)


def _best_image(images: list) -> str | None:
    """URL самой крупной картинки из списка images (width → приоритет)."""
    candidates = [
        image for image in images
        if isinstance(image, dict) and image.get("url")
    ]
    if not candidates:
        return None
    return str(max(
        candidates, key=lambda image: image.get("width") or 0
    )["url"])


def fetch_album(album_id: str) -> "SpotifyAlbum":
    """Запросить альбом у Spotify и собрать SpotifyAlbum.

    Жанр: поле убрано из API — остаётся пустым. Фото исполнителей:
    одиночные запросы /v1/artists/{id} (батч в Development Mode
    отвечает 403), не больше MAX_ARTIST_PHOTO_LOOKUPS на альбом.
    """
    token = _get_token()
    data = _get_json(f"{API_BASE}/v1/albums/{album_id}", token)

    title = str(data.get("name") or "").strip()
    if not title:
        raise SpotifyError("Spotify не вернул название альбома.")
    year = str(data.get("release_date") or "")[:4]
    cover = _best_image(data.get("images") or [])

    genre = ""
    for raw_genre in data.get("genres") or []:
        genre = map_genre(str(raw_genre))
        if genre:
            break

    photos: dict[str, str] = {}
    artist_names: list[str] = []
    artist_ids: dict[str, str] = {}   # id → имя (уникальные исполнители)
    for entry in data.get("artists") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or name in artist_names:
            continue
        artist_names.append(name)
        artist_id = str(entry.get("id") or "").strip()
        if artist_id:
            artist_ids.setdefault(artist_id, name)

    # Треки: до 50 в первом ответе, дальше — по абсолютной tracks.next
    raw_tracks: list[dict] = []
    next_url = (data.get("tracks") or {}).get("next")
    raw_tracks.extend(
        item for item in (data.get("tracks") or {}).get("items") or []
        if isinstance(item, dict)
    )
    pages = 1
    while next_url and pages < MAX_TRACK_PAGES:
        page = _get_json(str(next_url), token)
        raw_tracks.extend(
            item for item in page.get("items") or []
            if isinstance(item, dict)
        )
        next_url = page.get("next")
        pages += 1

    tracks: list[SpotifyTrack] = []
    for raw_track in raw_tracks:
        track_title = str(raw_track.get("name") or "").strip()
        if not track_title:
            continue
        names: list[str] = []
        for entry in raw_track.get("artists") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in names:
                continue
            names.append(name)
            artist_id = str(entry.get("id") or "").strip()
            if artist_id:
                artist_ids.setdefault(artist_id, name)
        if not names and artist_names:
            names = [artist_names[0]]
        tracks.append(SpotifyTrack(title=track_title, artists=names))

    # Фото: одиночные запросы, кап по количеству
    photo_ids = list(artist_ids)[:MAX_ARTIST_PHOTO_LOOKUPS]
    if photo_ids:
        payloads = _get_many_json(
            [f"{API_BASE}/v1/artists/{artist_id}" for artist_id in photo_ids],
            token,
        )
        for artist_id, payload in zip(photo_ids, payloads):
            image = _best_image((payload or {}).get("images") or [])
            if image:
                photos.setdefault(artist_ids[artist_id], image)

    return SpotifyAlbum(
        title=title,
        year=year,
        genre=genre,
        cover_url=cover,
        artist_names=artist_names,
        tracks=tracks,
        photos=photos,
        album_id=f"spotify:{album_id}",
    )


def load_album_from_link(link_text: str) -> "SpotifyAlbum":
    """Ссылка → данные альбома (разобрать ссылку + запросить API)."""
    album_id = resolve_album_id(link_text)
    return fetch_album(album_id)


def save_image_bytes(raw: bytes) -> str | None:
    """Сохранить скачанную картинку в data/covers (путь от корня)."""
    # Локальный импорт: app.store не зависит от сервисов — цикла нет
    from app.store import COVERS_DIR, DATA_DIR

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
    try:
        raw, _ = _get_bytes(url)
    except SpotifyError:
        return None
    return save_image_bytes(raw)


# Английские названия жанров → жанры приложения; маппинг общий с Deezer
from app.services.deezer import map_genre  # noqa: E402  (общий словарь)


@dataclass
class SpotifyTrack:
    """Трек из ответа Spotify: название + имена исполнителей."""

    title: str
    artists: list[str] = field(default_factory=list)


@dataclass
class SpotifyAlbum:
    """Данные альбома, полученные со Spotify (см. fetch_album)."""

    title: str = ""
    year: str = ""
    genre: str = ""
    cover_url: str | None = None
    artist_names: list[str] = field(default_factory=list)  # авторы альбома
    tracks: list[SpotifyTrack] = field(default_factory=list)
    photos: dict[str, str] = field(default_factory=dict)   # имя → URL фото
    album_id: str = ""   # «spotify:<id>» — запоминается у созданного
                         # альбома, чтобы ссылку нельзя было использовать
                         # второй раз

    def download_image(self, url: str | None) -> str | None:
        """Скачать картинку этого источника (поле мастера — без привязки
        к сервису: у DeezerAlbum такой же метод)."""
        if not url:
            return None
        return download_image(url)
