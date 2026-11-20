"""Кэш декодированных картинок (обложки альбомов и фото исполнителей).

Зачем: каждая карточка при создании делала QPixmap(path) — чтение и
JPEG-декодирование с диска. При возврате на главную пересоздаются
все карточки (десятки), и это давало заметный «прогруз» страницы
(Task 45: home.refresh() занимал ~170 мс, из них значительная часть —
повторное декодирование одних и тех же обложек).

Ключ кэша — абсолютный путь + mtime + размер: заменённый файл
подхватится автоматически, без ручной инвалидации. Размер ограничен;
при переполнении кэш просто очищается (в библиотеке десятки картинок).

QPixmap можно создавать/использовать только в GUI-потоке — все вызовы
идут из UI-кода.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPixmap

_MAX_ITEMS = 128
_CACHE: dict[str, tuple[int, int, QPixmap]] = {}


def load_pixmap(path: str | Path | None) -> QPixmap | None:
    """Вернуть декодированную картинку (с кэшем) или None."""
    if path is None:
        return None
    resolved = Path(path)
    try:
        stat = resolved.stat()
    except OSError:
        return None
    key = str(resolved)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stat.st_mtime_ns \
            and cached[1] == stat.st_size:
        return cached[2]
    pixmap = QPixmap(key)
    if pixmap.isNull():
        return None
    if len(_CACHE) >= _MAX_ITEMS:
        _CACHE.clear()
    _CACHE[key] = (stat.st_mtime_ns, stat.st_size, pixmap)
    return pixmap


def clear() -> None:
    """Сбросить кэш (например, после импорта базы)."""
    _CACHE.clear()
