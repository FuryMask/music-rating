"""Плитка исполнителя — маленький чип в «Списке исполнителей».

Анатомия:
  ┌───────────────────┐
  │  Имя исполнителя ✕ │   ✕ — удаление плитки
  └───────────────────┘
Ховер — по единому стандарту приложения: белая обводка + рост
на 10 % за 250 мс (как у плиток альбомов). Сам крестик удаления
БЕЗ обводки и роста — он лишь слегка светлеет под курсором.
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.models import ArtistDraft
from app.ui.widgets.hoverable import Hoverable

CHIP_HEIGHT = 34      # высота плитки
REMOVE_SIZE = 22      # сторона крестика удаления


class ChipRemoveButton(QPushButton):
    """Крестик «удалить» — БЕЗ ховер-обводки и увеличения (по ТЗ).

    Линии рисуются вручную — глиф «✕» шрифтом садится не по
    оптическому центру. Под курсором крестик лишь светлеет.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setObjectName("chipRemove")
        self.setFixedSize(REMOVE_SIZE, REMOVE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Удалить исполнителя")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон/рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#c9c9c9") if self.underMouse() else QColor("#8a8a8a")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        a = 4.5
        painter.drawLine(QPointF(cx - a, cy - a), QPointF(cx + a, cy + a))
        painter.drawLine(QPointF(cx - a, cy + a), QPointF(cx + a, cy - a))


class ArtistChip(Hoverable, QWidget):
    """Одна плитка в «Списке исполнителей».

    Обводка рисуется на самом чипе (дети — имя и крестик — утоплены
    внутрь и не перекрывают край). Крестик при ховере растёт вместе
    с чипом, т.к. перекомпоновывается его layout.
    """

    removed = Signal(object)  # ArtistDraft этой плитки

    def __init__(self, artist: ArtistDraft, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.artist = artist
        self.setObjectName("artistChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.init_hover(outline_radius=8, outline_on_self=True)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(6)

        self.lbl_name = QLabel(artist.name, self)
        self.lbl_name.setObjectName("chipName")
        self.lbl_name.setMaximumWidth(220)
        row.addWidget(self.lbl_name)

        self.btn_remove = ChipRemoveButton(self)
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self.artist))
        row.addWidget(self.btn_remove)

        self.setFixedHeight(CHIP_HEIGHT)
