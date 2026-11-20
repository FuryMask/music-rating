"""Shared Windows media-session controls for installed music players."""

from __future__ import annotations

import asyncio
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache


class DesktopPlaybackError(Exception):
    pass


@lru_cache(maxsize=4096)
def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return " ".join(re.findall(r"\w+", text))


@dataclass(frozen=True)
class PlaybackTrack:
    uri: str
    title: str
    base_title: str
    artists: tuple[str, ...]
    duration_ms: int

    def matches(self, media: MediaSnapshot) -> bool:
        title = _normalized(media.title)
        if not title or title not in {_normalized(self.title), _normalized(self.base_title)}:
            return False
        reported = f" {_normalized(media.artist)} "
        if not any(f" {_normalized(artist)} " in reported for artist in self.artists
                   if _normalized(artist)):
            return False
        return not (self.duration_ms and media.duration_ms
                    and abs(self.duration_ms - media.duration_ms) > 4000)


@dataclass(frozen=True)
class MediaSnapshot:
    title: str
    artist: str
    position_ms: int
    duration_ms: int
    playing: bool
    can_seek: bool = False


class WindowsMediaSession:
    """Blocking interface for a background worker, never the Qt GUI thread."""

    def __init__(self, app_name, is_app) -> None:
        self._manager = None
        self.app_name = app_name
        self._is_app = is_app

    def read(self, track: PlaybackTrack, command: str | None = None, *,
             seek_ms: int | None = None) -> tuple[MediaSnapshot | None, bool]:
        if sys.platform != "win32":
            raise DesktopPlaybackError("Управление настольным плеером доступно только в Windows.")
        try:
            from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SessionManager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
            )
        except ImportError as error:
            raise DesktopPlaybackError("Установите зависимости: python -m pip install -r requirements.txt.") from error

        async def sample():
            if self._manager is None:
                self._manager = await SessionManager.request_async()
            fallback = None
            for session in self._manager.get_sessions():
                if not self._is_app(session.source_app_user_model_id):
                    continue
                try:
                    media = await session.try_get_media_properties_async()
                    info = session.get_playback_info()
                    timeline = session.get_timeline_properties()
                except OSError:
                    continue
                if media is None:
                    continue
                playing = info.playback_status == Status.PLAYING
                duration = (timeline.end_time - timeline.start_time).total_seconds() * 1000
                position = (timeline.position - timeline.start_time).total_seconds() * 1000
                updated = timeline.last_updated_time
                if playing and updated.year > 2000 and (duration > 0 or position > 0):
                    elapsed = (datetime.now(timezone.utc) - updated.replace(tzinfo=timezone.utc)).total_seconds()
                    position += max(0, elapsed) * 1000 * (info.playback_rate or 1)
                snapshot = MediaSnapshot(media.title, media.artist, max(0, round(position)),
                                         max(0, round(duration)), playing,
                                         bool(info.controls and info.controls.is_playback_position_enabled))
                if not track.matches(snapshot):
                    if fallback is None or playing:
                        fallback = snapshot
                    continue
                if command == "pause":
                    return snapshot, await session.try_pause_async()
                if command == "play":
                    return snapshot, await session.try_play_async()
                if command == "next":
                    if not info.controls or not info.controls.is_next_enabled:
                        return snapshot, False
                    return snapshot, await session.try_skip_next_async()
                if command == "seek":
                    if not snapshot.can_seek or seek_ms is None:
                        return snapshot, False
                    ticks = round(timeline.start_time.total_seconds() * 10_000_000) + seek_ms * 10_000
                    return snapshot, await session.try_change_playback_position_async(ticks)
                return snapshot, True
            return fallback, command is None

        async def bounded_read():
            return await asyncio.wait_for(sample(), 3.0)

        try:
            init_apartment(ApartmentType.MULTI_THREADED)
            try:
                return asyncio.run(bounded_read())
            finally:
                uninit_apartment()
        except (OSError, TimeoutError) as error:
            self._manager = None
            raise DesktopPlaybackError(f"Windows не ответила. Проверьте, что открыт плеер {self.app_name}.") from error
