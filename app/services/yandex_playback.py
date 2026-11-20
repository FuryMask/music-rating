"""Match Yandex Music catalog tracks and open its desktop client."""

import os
import sys
from pathlib import Path

from app.models import Album
from app.services.desktop_launch import launch_without_activation
from app.services.desktop_playback import MediaSnapshot, PlaybackTrack, WindowsMediaSession, _normalized
from app.services.yandex_music import YandexMusicAlbum, YandexMusicError, YandexMusicTrack


def match_album_tracks(album: Album, catalog: YandexMusicAlbum) -> list[PlaybackTrack]:
    source, _, album_id = catalog.album_id.partition(":")
    if source != "yandex" or not (album_id.isascii() and album_id.isdigit()):
        raise YandexMusicError("Яндекс Музыка вернула неверный идентификатор издания.")
    by_title: dict[str, list[YandexMusicTrack]] = {}
    for item in catalog.tracks:
        if item.track_id:
            by_title.setdefault(_normalized(item.title), []).append(item)
    result = []
    for local in album.tracks:
        artists = {_normalized(name) for name in (
            [artist.name for artist in local.artists] or album.artist_names
        ) if name.strip()}
        candidates = [
            item for item in by_title.get(_normalized(local.title), ())
            if not artists or artists.intersection(map(_normalized, item.artists))
        ]
        if len({item.track_id for item in candidates}) != 1:
            raise YandexMusicError(f"Не удалось однозначно сопоставить «{local.title}» с альбомом в Яндекс Музыке.")
        item = candidates[0]
        result.append(PlaybackTrack(
            f"yandexmusic://album/{album_id}/track/{item.track_id}", item.title,
            item.base_title, tuple(item.artists), item.duration_ms,
        ))
    return result


def yandex_executable_paths() -> tuple[Path, ...]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if sys.platform != "win32" or not local_app_data:
        return ()
    folder = Path(local_app_data) / "Programs" / "YandexMusic"
    return tuple(folder / name for name in ("Яндекс Музыка.exe", "YandexMusic.exe"))


def launch_yandex_desktop(uri: str) -> None:
    executables = yandex_executable_paths()
    if not executables:
        raise YandexMusicError("Для прослушивания нужен настольный клиент Яндекс Музыки для Windows.")
    for executable in executables:
        if executable.is_file():
            if launch_without_activation(
                executable, ["--enable-features=UiaProvider", "--force-renderer-accessibility", uri],
            ):
                return
            raise YandexMusicError("Не удалось запустить настольную Яндекс Музыку.")
    raise YandexMusicError("Не найдена Яндекс Музыка в %LOCALAPPDATA%\\Programs\\YandexMusic.")


def _is_yandex_app(app_id: str) -> bool:
    app_id = app_id.casefold().replace("/", "\\")
    return (
        app_id == "ru.yandex.desktop.music"
        or app_id.endswith((
            "\\programs\\yandexmusic\\яндекс музыка.exe",
            "\\programs\\yandexmusic\\yandexmusic.exe",
        ))
    )


class YandexDesktopSession(WindowsMediaSession):
    def __init__(self) -> None:
        super().__init__("Яндекс Музыка", _is_yandex_app)
