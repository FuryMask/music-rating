"""Проверка и загрузка Windows-установщика из GitHub Releases."""

import hashlib
import hmac
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDir, QObject, QProcess, QTemporaryDir, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.version import INSTALLER_NAME, RELEASE_REPOSITORY, VERSION

_LIMIT = 2 * 1024**3
_RELEASE_API = f"https://api.github.com/repos/{RELEASE_REPOSITORY}/releases/latest"
_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}")


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str


def find_update(payload: dict, current_version: str = VERSION) -> Release | None:
    """Выбрать стабильный релиз с проверяемым Windows-установщиком."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not _VERSION.fullmatch(tag.removeprefix("v")):
        return None
    version = tag.removeprefix("v")
    if tuple(map(int, version.split("."))) <= tuple(map(int, current_version.split("."))):
        return None
    url = f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{tag}/{INSTALLER_NAME}"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != INSTALLER_NAME:
            continue
        size, digest = asset.get("size"), asset.get("digest")
        if (asset.get("state") == "uploaded" and asset.get("browser_download_url") == url
                and type(size) is int and 0 < size < _LIMIT
                and isinstance(digest, str) and re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest)):
            return Release(version, url, size, digest[7:].lower())
    return None


class Updates(QObject):
    available = Signal(str)
    progress = Signal(int)
    failed = Signal(str)
    installer_started = Signal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.release: Release | None = None
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(4 * 60 * 60 * 1000)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        if sys.platform == "win32":
            QTimer.singleShot(600, self.check)
            self._timer.start()

    def _get(self, url: str, *, metadata: bool = False) -> QNetworkReply:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"MusicRating/{VERSION}".encode("ascii"))
        request.setTransferTimeout(15_000 if metadata else 60_000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        if metadata:
            request.setRawHeader(b"Accept", b"application/vnd.github+json")
        self._reply = self._network.get(request)
        return self._reply

    def check(self) -> None:
        if self._reply is not None:
            return
        reply = self._get(_RELEASE_API, metadata=True)

        def finish() -> None:
            self._reply = None
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    self.release = find_update(json.loads(bytes(reply.readAll())))
                    self.available.emit(self.release.version if self.release else "")
                elif reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == 404:
                    self.release = None
                    self.available.emit("")
            except (ValueError, UnicodeError):
                pass
            finally:
                reply.deleteLater()

        reply.finished.connect(finish)

    def install(self) -> None:
        release = self.release
        if self._reply is not None or release is None or sys.platform != "win32":
            return
        temporary = QTemporaryDir(QDir.temp().filePath("MusicRating-Update-XXXXXX"))
        if not temporary.isValid():
            self.failed.emit("Не удалось создать папку для обновления.")
            return
        installer = Path(temporary.filePath(INSTALLER_NAME))
        try:
            stream = installer.open("xb")
        except OSError:
            self.failed.emit("Не удалось открыть файл для обновления.")
            return

        reply = self._get(release.url)
        digest = hashlib.sha256()
        received = 0
        write_failed = False
        last_percent = 0
        self.progress.emit(0)

        def read() -> None:
            nonlocal received, write_failed, last_percent
            while not write_failed and reply.bytesAvailable():
                chunk = bytes(reply.read(256 * 1024))
                if not chunk:
                    break
                received += len(chunk)
                try:
                    if received > release.size or stream.write(chunk) != len(chunk):
                        raise OSError
                except OSError:
                    write_failed = True
                    if not reply.isFinished():
                        reply.abort()
                    return
                digest.update(chunk)
                percent = received * 100 // release.size
                if percent != last_percent:
                    last_percent = percent
                    self.progress.emit(percent)

        def finish() -> None:
            nonlocal write_failed
            read()
            self._reply = None
            try:
                stream.close()
            except OSError:
                write_failed = True
            error = reply.error()
            reply.deleteLater()
            if write_failed or error != QNetworkReply.NetworkError.NoError:
                self.failed.emit("Не удалось скачать обновление. Попробуйте ещё раз.")
            elif received != release.size or not hmac.compare_digest(digest.hexdigest(), release.digest):
                self.failed.emit("Проверка файла обновления не прошла.")
            else:
                started, _ = QProcess.startDetached(str(installer), [], str(installer.parent))
                if started:
                    temporary.setAutoRemove(False)
                    self.installer_started.emit()
                    return
                self.failed.emit("Не удалось запустить установщик.")
            self.available.emit(release.version)

        reply.readyRead.connect(read)
        reply.finished.connect(finish)
