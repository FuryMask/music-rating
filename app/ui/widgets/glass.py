"""Painted glass and line icons for the Qt interface."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer

from app.theme import themed_color


_ICONS = {
    "update": "M20 10a8 8 0 0 0-14-4L4 8m0-5v5h5M4 14a8 8 0 0 0 14 4l2-2m0 5v-5h-5",
    "home": "M3 10l9-7 9 7M6 9v11h12V9m-8 11v-6h4v6",
    "recent": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4v5l4 2",
    "albums": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "artists": "M12 4a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM4 20c0-7 16-7 16 0",
    "note": "M12 17V4c4 0 4 5 8 5m-8 8c0 3-8 5-8 1s8-6 8-1z",
    "account": "M6 5h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z M9 8a2 2 0 1 1 0 4 2 2 0 0 1 0-4z M6.5 16c0-3.5 5-3.5 5 0 M14 10h3.5m-3.5 4h3.5",
    "cloud-mode": "M7 15H6a3.5 3.5 0 1 1 .7-6.9 5.5 5.5 0 0 1 10.5.4A3.3 3.3 0 0 1 18 15h-1M12 11v10m-3-3 3 3 3-3",
    "add-album": "M12 4a8 8 0 1 0 8 8 M16 6h6m-3-3v6M10 12a2 2 0 1 0 4 0 2 2 0 1 0-4 0",
    "close": "M6 6l12 12M18 6 6 18",
    "check": "M5 12l4.5 4.5L19 7",
    "plus": "M5 12h14M12 5v14",
    "back": "M19 12H5m0 0 6-6m-6 6 6 6",
    "play": "M8 5v14l11-7z",
    "pause": "M9 5v14m6-14v14",
    "arrow-right": "M5 12h14m0 0-6-6m6 6-6 6",
    "chevron-down": "M6 9l6 6 6-6",
    "fullscreen": "M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5",
    "windowed": "M4 9h5V4m6 0v5h5M4 15h5v5m6 0v-5h5",
    "search": "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zm5 11.5 4.5 4.5",
}


def line_icon(name: str, size: int = 20) -> QIcon:
    svg = QSvgRenderer((
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="none" stroke="#c5dcff" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round" d="{_ICONS[name]}"/></svg>'
    ).encode("ascii"))
    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        svg.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def paint_glass(widget, radius: float, *, vertical: bool = False) -> None:
    bounds = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    if bounds.isEmpty():
        return
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    shape = QPainterPath()
    shape.addRoundedRect(bounds, radius, radius)
    body = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    body.setColorAt(0, themed_color(QColor(133, 163, 226, 65)))
    body.setColorAt(0.54, themed_color(QColor(86, 110, 158, 36)))
    body.setColorAt(1, themed_color(QColor(147, 111, 187, 52)))
    painter.fillPath(shape, body)
    light = QRadialGradient(bounds.topLeft() + QPointF(bounds.width() * 0.2, 0),
                            max(1, bounds.width() * (1.3 if vertical else 0.42)))
    light.setColorAt(0, themed_color(QColor(196, 225, 255, 40)))
    light.setColorAt(1, themed_color(QColor(196, 225, 255, 0)))
    painter.fillPath(shape, light)
    rim = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    rim.setColorAt(0, themed_color(QColor(227, 242, 255, 148)))
    rim.setColorAt(0.28, themed_color(QColor(201, 221, 255, 49)))
    rim.setColorAt(0.73, themed_color(QColor(197, 211, 255, 27)))
    rim.setColorAt(1, themed_color(QColor(224, 203, 255, 99)))
    painter.strokePath(shape, QPen(rim, 1))

