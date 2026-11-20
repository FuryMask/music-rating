"""Плитка исполнителя — маленький чип в «Списке исполнителей».

Анатомия:
  ┌───────────────────┐
  │  Имя исполнителя ✕ │   ✕ — удаление плитки
  └───────────────────┘
Крестик удаления использует ту же анимацию, что и остальные кнопки.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.models import ArtistDraft
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import Hoverable, HoverButton

CHIP_HEIGHT = 34      # высота плитки
REMOVE_SIZE = 22      # сторона крестика удаления


class ChipRemoveButton(HoverButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=6)
        self.setObjectName("chipRemove")
        self.setFixedSize(REMOVE_SIZE, REMOVE_SIZE)
        self.setToolTip("Удалить исполнителя")
        self.setIcon(line_icon("close", 15))


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
