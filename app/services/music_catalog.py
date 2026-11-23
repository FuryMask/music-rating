"""Request catalog data using the current Music Rating cloud session."""

import json
import time
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.services.cloud_library import CloudSession, PROJECT_URL, PUBLISHABLE_KEY


class CatalogError(Exception):
    pass


class MusicCatalog(QObject):
    def __init__(self, session: Callable[[], CloudSession | None], parent: QObject) -> None:
        super().__init__(parent)
        self._session = session
        self._manager = QNetworkAccessManager(self)

    def _access_token(self) -> str:
        session = self._session()
        if session and (not session.expires_at or session.expires_at > time.time()):
            return session.access_token
        return ""

    def available(self) -> bool:
        return bool(self._access_token())

    def request(self, action: str, **params) -> dict:
        token = self._access_token()
        if not token:
            raise CatalogError("Войдите в облачный аккаунт Music Rating и повторите загрузку.")
        request = QNetworkRequest(QUrl(f"{PROJECT_URL}/functions/v1/music-catalog"))
        request.setTransferTimeout(25000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        request.setRawHeader(b"apikey", PUBLISHABLE_KEY.encode())
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self._manager.post(request, json.dumps({"action": action, **params}).encode())
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        if not reply.isFinished():
            loop.exec()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        raw = bytes(reply.readAll())
        reply.deleteLater()
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if ok and status == 200 and isinstance(data, dict):
            return data
        code = data.get("code") if isinstance(data, dict) else None
        if status == 401:
            message = "Облачный сеанс истёк. Войдите в Music Rating снова."
        elif status == 403:
            message = "Для этого аккаунта не открыт доступ к общей библиотеке Music Rating."
        elif code == "not_found":
            message = "Музыкальный сервис не нашёл эту запись."
        elif status == 404:
            message = "Функция music-catalog не опубликована в Supabase. Обратитесь к администратору Music Rating."
        elif code == "missing_credentials":
            message = "В Supabase не заполнены секреты этого музыкального сервиса. Проверьте Edge Functions → Secrets."
        elif code == "credentials_rejected":
            message = "Музыкальный сервис отклонил общий ключ. Проверьте значения секретов в Supabase."
        elif code == "provider_forbidden":
            message = ("Spotify запретил доступ к каталогу. Проверьте статус приложения в Spotify Developer Dashboard."
                       if action == "spotify-album" else "Genius запретил запрос к каталогу.")
        elif code in ("membership_unavailable", "not_configured"):
            message = "Функция Supabase не может проверить доступ к общей библиотеке. Проверьте настройки проекта."
        elif status == 429:
            message = "Музыкальный сервис ограничил число запросов. Повторите попытку позже."
        else:
            message = "Не удалось загрузить данные из облачного каталога. Повторите попытку позже."
        raise CatalogError(message)
