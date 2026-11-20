"""Open Spotify albums in the Windows client and follow its media session."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from app.services.desktop_launch import launch_without_activation
from app.services.desktop_playback import DesktopPlaybackError, PlaybackTrack, WindowsMediaSession

SPOTIFY_PACKAGE = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0"


def spotify_executable_paths() -> tuple[Path, ...]:
    app_data = os.environ.get("APPDATA")
    return (Path(app_data) / "Spotify" / "Spotify.exe",) if sys.platform == "win32" and app_data else ()


def _is_spotify_app(app_id: str) -> bool:
    app_id = app_id.replace("/", "\\").casefold()
    return (app_id in ("spotify", "spotify.exe")
            or app_id.partition("!")[0] == SPOTIFY_PACKAGE.casefold()
            or any(app_id == str(path).casefold() for path in spotify_executable_paths()))


class SpotifyDesktopSession(WindowsMediaSession):
    def __init__(self) -> None:
        super().__init__("Spotify", _is_spotify_app)


def spotify_album_uri(album_id: str) -> str:
    if not (album_id.isascii() and album_id.isalnum()):
        raise DesktopPlaybackError("Не удалось прочитать идентификатор альбома Spotify.")
    return f"spotify:album:{album_id}"


def spotify_playback_tracks(album, album_id: str) -> list[PlaybackTrack]:
    uri = spotify_album_uri(album_id)
    return [
        PlaybackTrack(uri, track.title, track.title,
                      tuple(artist.name for artist in track.artists) or tuple(album.artist_names), 0)
        for track in album.tracks
    ]


def launch_spotify_desktop(uri: str) -> None:
    if sys.platform != "win32":
        raise DesktopPlaybackError("Для прослушивания нужен настольный Spotify для Windows.")
    for path in spotify_executable_paths():
        if path.is_file() and launch_without_activation(path, [f"--protocol-uri={uri}"]):
            return
    if not QDesktopServices.openUrl(QUrl(uri)):
        raise DesktopPlaybackError("Не удалось открыть настольный Spotify. Проверьте установку клиента.")
