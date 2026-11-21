"""Supabase session, library, and artwork requests."""

import hashlib
import json
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from app.store import COVERS_DIR

PROJECT_URL = "https://hmacrjdyeuzwkitdwwfj.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_69jL-HqPgkaMVjGg553nVw_WDsnEX7l"
ARTWORK = "/storage/v1/object/music-rating-artwork"
SHARED_ARTWORK = "/storage/v1/object/music-rating-shared-artwork"
SHARED_STATUS = "/rest/v1/rpc/music_rating_shared_status"
SHARED_UPLOAD = "/rest/v1/rpc/music_rating_shared_upload"


class CloudError(Exception):
    def __init__(self, message: str, *, expired: bool = False, code: str | None = None) -> None:
        super().__init__(message)
        self.expired = expired
        self.code = code


@dataclass(frozen=True)
class CloudSession:
    user_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    expires_at: float = 0
    email: str = ""
    display_name: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class Artwork:
    path: Path
    digest: str
    content_type: str


@dataclass(frozen=True)
class LibraryItem:
    kind: str
    item_id: str
    label: str
    payload: dict
    artwork: tuple[Artwork, ...] = ()
    updated_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.item_id}"

    def record(self) -> dict:
        content = json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"kind": self.kind, "item_id": self.item_id, "payload": self.payload,
                "snapshot_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def snapshot_library(store) -> list[LibraryItem]:
    """Select cloud data explicitly so password hashes, paths and settings stay local."""
    artwork_cache: dict[Path, Artwork] = {}
    covers_root = COVERS_DIR.resolve()

    def attach(payload: dict, fields: dict[str, str | None]) -> tuple[Artwork, ...]:
        images = []
        for field_name, value in fields.items():
            path = store.resolve(value)
            if path is None:
                continue
            path = path.resolve()
            content_type, _ = mimetypes.guess_type(path.name)
            if not path.is_relative_to(covers_root) or not (content_type or "").startswith("image/"):
                continue
            if path not in artwork_cache:
                try:
                    with path.open("rb") as image:
                        digest = hashlib.file_digest(image, "sha256").hexdigest()
                except FileNotFoundError:
                    continue
                artwork_cache[path] = Artwork(path, digest, content_type)
            image = artwork_cache[path]
            payload[field_name] = {"sha256": image.digest, "content_type": image.content_type}
            images.append(image)
        return tuple(images)

    items = []
    for album in store.albums:
        payload = {
            "title": album.title, "year": album.year, "genre": album.genre, "region": album.region,
            "created_at": album.created_at, "source_id": album.source_id,
            "artists": list(album.artist_names),
            "tracks": [{"title": track.title, "artists": [artist.name for artist in track.artists]}
                       for track in album.tracks],
        }
        label = " — ".join(filter(None, (album.title, album.artists_text)))
        images = attach(payload, {"cover": album.cover_path})
        items.append(LibraryItem("album", album.id, label, payload, images))
        ratings = album.ratings
        if album.rating is not None or (ratings is not None and ratings.filled_count()):
            payload = {"album_id": album.id, "average": album.rating, "rated_at": album.rated_at}
            if ratings is not None:
                payload.update({"participants": list(ratings.rater_names),
                                "track_scores": [list(row) for row in ratings.values]})
            details = []
            if album.rating is not None:
                details.append(f"{album.rating:g}")
            if ratings is not None:
                details.extend(f"{name} — {average:g}" for column, name in enumerate(ratings.rater_names)
                               if (average := ratings.participant_average(column)) is not None)
            rating_label = f"{label} · {', '.join(details)}" if details else label
            items.append(LibraryItem("rating", album.id, rating_label, payload))
    for artist in store.artists:
        payload = {"name": artist.name, "genre": artist.genre}
        images = attach(payload, {"photo": artist.photo_path, "avatar": artist.avatar_path})
        items.append(LibraryItem("artist", artist.name, artist.name, payload, images))
    return items


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_SCHEMA_SETUP = "Supabase не видит хранилище Music Rating. Выполните миграцию из RELEASE.md в SQL Editor."
_MESSAGES = {
    "email_not_confirmed": "Почта ещё не подтверждена. Введите код из письма или запросите новый.",
    "otp_expired": "Код неверный или истёк. Запросите новый и используйте код из последнего письма.",
    "invalid_credentials": "Проверьте почту и пароль облачного аккаунта.",
    "weak_password": "Пароль не соответствует требованиям Supabase.",
    "email_address_invalid": "Проверьте адрес электронной почты.",
    "email_address_not_authorized": "Для этого адреса не настроена отправка писем Supabase.",
    "over_email_send_rate_limit": "Превышен лимит писем. Повторите попытку позже.",
    "over_request_rate_limit": "Слишком много запросов. Повторите попытку позже.",
    "signup_disabled": "Регистрация отключена в настройках Supabase.",
    "PGRST202": _SCHEMA_SETUP,
    "PGRST205": _SCHEMA_SETUP,
    "42P01": _SCHEMA_SETUP,
    "42501": "Проверьте права доступа Music Rating в Supabase.",
    "PT403": "Для этого аккаунта не открыт доступ к общей библиотеке Music Rating.",
}


class CloudLibrary:
    def __init__(self, url: str = PROJECT_URL, public_key: str = PUBLISHABLE_KEY) -> None:
        self._url = url.rstrip("/")
        self._public_key = public_key
        self._opener = build_opener(_NoRedirects())

    def _request(self, path: str, *, body=None, session: CloudSession | None = None,
                 content_type: str = "application/json", binary: bool = False):
        headers = {"apikey": self._public_key, "Accept": "*/*" if binary else "application/json"}
        if session is not None:
            headers["Authorization"] = f"Bearer {session.access_token}"
        if body is not None:
            headers["Content-Type"] = content_type
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(self._url + path, data=body, headers=headers)
        try:
            with self._opener.open(request, timeout=15) as response:
                data = response.read()
                return data if binary else (json.loads(data) if data else None)
        except HTTPError as error:
            with error:
                try:
                    info = json.loads(error.read())
                except (ValueError, UnicodeError):
                    info = {}
            code = (info.get("error_code") or info.get("code")) if isinstance(info, dict) else None
            code = code if isinstance(code, str) else None
            if error.code == 401 and session is not None:
                raise CloudError("Сеанс облака истёк. Войдите снова.", expired=True) from None
            fallback = f"Supabase отклонил запрос (HTTP {error.code})."
            raise CloudError(_MESSAGES.get(code, fallback), code=code) from None
        except (URLError, TimeoutError, OSError):
            raise CloudError("Не удалось подключиться к Supabase. Проверьте интернет.") from None
        except (ValueError, UnicodeError):
            raise CloudError("Supabase вернул неожиданный ответ.") from None

    def authenticate(self, email: str, password: str, *, register: bool = False) -> CloudSession | None:
        path = "/auth/v1/signup" if register else "/auth/v1/token?grant_type=password"
        result = self._request(path, body={"email": email, "password": password})
        if register and isinstance(result, dict) and not result.get("access_token"):
            user = result.get("user", result)
            if isinstance(user, dict) and isinstance(user.get("id"), str):
                return None
        return self._parse_session(result)

    def confirm_email(self, email: str, token: str) -> CloudSession:
        result = self._request("/auth/v1/verify", body={"type": "email", "email": email, "token": token})
        return self._parse_session(result)

    def resend_confirmation(self, email: str) -> None:
        self._request("/auth/v1/resend", body={"type": "signup", "email": email})

    def sign_out(self, session: CloudSession) -> None:
        self._request("/auth/v1/logout?scope=local", body={}, session=session)

    def renew(self, session: CloudSession) -> CloudSession:
        if session.access_token and (not session.expires_at or session.expires_at > time.time() + 60):
            return session
        if not session.refresh_token:
            raise CloudError("Сеанс облака истёк. Войдите снова.", expired=True)
        try:
            refreshed = self._parse_session(self._request("/auth/v1/token?grant_type=refresh_token",
                                                          body={"refresh_token": session.refresh_token}))
        except CloudError as error:
            if error.code in ("refresh_token_not_found", "refresh_token_already_used", "session_not_found",
                              "invalid_grant", "bad_jwt", "user_not_found"):
                raise CloudError("Сеанс облака истёк. Войдите снова.", expired=True) from None
            raise
        if refreshed.user_id != session.user_id:
            raise CloudError("Сеанс облака истёк. Войдите снова.", expired=True)
        return refreshed

    @staticmethod
    def _parse_session(result) -> CloudSession:
        if not isinstance(result, dict):
            raise CloudError("Supabase вернул неожиданный ответ при входе.")
        token, user = result.get("access_token"), result.get("user", result)
        if not isinstance(user, dict) or not isinstance(user.get("id"), str):
            raise CloudError("Supabase не вернул идентификатор аккаунта.")
        if not isinstance(token, str) or not token:
            raise CloudError("Supabase не вернул сеанс.")
        try:
            refresh = result.get("refresh_token") or ""
            expiration = result.get("expires_at") or time.time() + float(result.get("expires_in") or 3600)
            if not isinstance(refresh, str):
                raise ValueError
            metadata = user.get("user_metadata")
            name = metadata.get("display_name") or metadata.get("full_name") if isinstance(metadata, dict) else ""
            return CloudSession(str(UUID(user["id"])), token, refresh, float(expiration),
                                user.get("email") or "", name if isinstance(name, str) else "",
                                user.get("created_at") or "")
        except (ValueError, TypeError):
            raise CloudError("Supabase вернул неверный идентификатор аккаунта.") from None

    def shared_status(self, session: CloudSession, *, download: bool = False) -> dict:
        status = self._request(SHARED_STATUS, body={"p_download": download}, session=session)
        if not isinstance(status, dict) or not isinstance(status.get("revision"), str):
            raise CloudError("Supabase вернул некорректную версию библиотеки.")
        return status

    def shared_upload(self, session: CloudSession, items: list[LibraryItem]) -> None:
        images = {image.digest: image for item in items for image in item.artwork}
        for image in images.values():
            data = image.path.read_bytes()
            if hashlib.sha256(data).hexdigest() != image.digest:
                raise CloudError("Обложка или фото изменились. Повторите загрузку.")
            path = f"{SHARED_ARTWORK}/{image.digest}"
            try:
                self._request(path, body=data, session=session, content_type=image.content_type)
            except CloudError as error:
                if error.expired or self.download_artwork(session, image.digest) != data:
                    raise
        if items:
            self._request(SHARED_UPLOAD, body={"p_items": [item.record() for item in items]}, session=session)

    def download_artwork(self, session: CloudSession, digest: str, *, personal: bool = False) -> bytes:
        path = f"{ARTWORK}/{session.user_id}" if personal else SHARED_ARTWORK
        path = path.replace("/object/", "/object/authenticated/", 1)
        return self._request(f"{path}/{digest}", session=session, binary=True)
