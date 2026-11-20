"""Compact scroll handles with native Qt hit testing and drag behavior."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider

from app.theme import themed_color


class SlimScrollBar(QScrollBar):
    def paintEvent(self, event) -> None:
        if self.minimum() == self.maximum():
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        bounds = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, option,
            QStyle.SubControl.SC_ScrollBarSlider, self,
        )
        handle = QRectF(bounds.intersected(self.rect())).adjusted(1, 1, -1, -1)
        if handle.isEmpty():
            return
        color = "#7185a5" if self.isSliderDown() else (
            "#516686" if self.underMouse() else "#344662"
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(themed_color(color))
        radius = min(handle.width(), handle.height()) / 2
        painter.drawRoundedRect(handle, radius, radius)


def install_slim_scrollbars(area) -> None:
    area.setVerticalScrollBar(SlimScrollBar(Qt.Orientation.Vertical, area))
    area.setHorizontalScrollBar(SlimScrollBar(Qt.Orientation.Horizontal, area))
