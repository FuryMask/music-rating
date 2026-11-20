"""Фоновая дозагрузка ФОТО исполнителей с Deezer — вместо заглушек.

При старте приложения (через мгновение после показа окна) запускается
цепочка фоновых запросов: исполнители без фото ищутся в Deezer по
имени (только точное совпадение), лучшие совпадения скачиваются в
data/covers и сразу появляются в интерфейсе.

ОБЛОЖКИ АЛЬБОМОВ НЕ ДОЗАГРУЖАЮТСЯ: обложка появляется у альбома
только если пользователь сам выбрал файл или альбом создан по ссылке
Deezer (там обложка приходит вместе с данными альбома). Раньше
дозагрузка подбирала обложки и вручную созданным альбомам — альбом
«сам» получал картинку, которую пользователь не добавлял.

Полностью асинхронно (цепочка сигналов QNetworkAccessManager) —
интерфейс не блокируется. Нет сети — тихо пропускаем (попытка
повторится при следующем запуске), заглушки-буквы остаются.
"""

import json
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from app.services.deezer import API_BASE, REQUEST_TIMEOUT_MS, save_image_bytes
from app.store import STORE


def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


class ArtBackfiller(QObject):
    """Очередь «исполнители без фото» → Deezer.

    Сигналы:
      changed  — очередная картинка сохранена в базу (обновить UI);
      finished — очередь исчерпана; True, если что-то скачали.
    """

    changed = Signal()
    finished = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._nam.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )
        self._queue: list[object] = []
        self._changed = False
        self._running = False

    # --- Управление -------------------------------------------------------
    def start(self) -> None:
        """Собрать очередь и начать (повторный вызов до конца — игнор)."""
        if self._running:
            return
        artists = [a for a in STORE.artists if not a.photo_path]
        if not artists:
            self.finished.emit(False)
            return
        self._queue = list(artists)
        self._changed = False
        self._running = True
        self._probe()

    def _request(self, url: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        return request

    # --- Цепочка: проба сети → обработка очереди ---------------------------
    def _probe(self) -> None:
        """Дешёвый запрос: сеть недоступна — сразу завершаемся молча."""
        reply = self._nam.get(self._request(
            f"{API_BASE}/search/artist?{urlencode({'q': 'a', 'limit': 1})}"
        ))
        reply.finished.connect(lambda: self._probe_done(reply))

    def _probe_done(self, reply: QNetworkReply) -> None:
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        reply.deleteLater()
        if not ok:
            self._running = False
            self.finished.emit(False)
            return
        self._next()

    def _next(self) -> None:
        if not self._queue:
            self._running = False
            self.finished.emit(self._changed)
            return
        artist = self._queue.pop(0)
        url = f"{API_BASE}/search/artist?{urlencode({'q': artist.name, 'limit': 5})}"
        reply = self._nam.get(self._request(url))
        reply.finished.connect(lambda: self._artist_search_done(reply, artist))

    # --- Исполнители --------------------------------------------------------
    def _artist_search_done(self, reply: QNetworkReply, artist) -> None:
        payload = self._json(reply)
        photo_url = None
        for entry in payload.get("data") or []:
            if not isinstance(entry, dict):
                continue
            if _norm(entry.get("name") or "") != _norm(artist.name):
                continue  # только точное совпадение имени
            photo_url = (
                entry.get("picture_xl")
                or entry.get("picture_big")
                or entry.get("picture_medium")
            )
            if isinstance(photo_url, str) and photo_url:
                break
            photo_url = None
        if photo_url:
            self._download(photo_url, lambda path: self._artist_saved(artist, path))
        else:
            self._next()

    def _artist_saved(self, artist, path: str) -> None:
        STORE.update_artist_photo(artist, path)
        self._changed = True
        self.changed.emit()
        self._next()

    # --- Скачивание ----------------------------------------------------------
    def _download(self, url: str, on_saved) -> None:
        reply = self._nam.get(self._request(url))
        reply.finished.connect(lambda: self._download_done(reply, on_saved))

    def _download_done(self, reply: QNetworkReply, on_saved) -> None:
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        raw = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()
        path = save_image_bytes(raw) if raw else None
        if path:
            on_saved(path)
        else:
            self._next()

    def _json(self, reply: QNetworkReply) -> dict:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return {}
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
