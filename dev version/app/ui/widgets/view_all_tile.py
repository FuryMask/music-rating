"""Плитка «Смотреть все» — восьмая плитка полной секции главной страницы.

Появляется, когда карточек в сегменте больше семи: в ряд выводятся
первые 7, а эта плитка ведёт на полный список: клик (сигнал clicked)
главная страница превращает в открытие страницы «Смотреть все» —
«Недавно оценённые», «Оценённые альбомы» или «Исполнители»
(см. pages/collection_page.py). Ховер — стандарт приложения:
белая обводка + рост на 10 % за 250 мс.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.widgets.album_card import CARD_SIZE
from app.ui.widgets.hoverable import Hoverable

TILE_SIZE = CARD_SIZE  # квадратная плитка вровень с обложками карточек


class ViewAllTile(Hoverable, QWidget):
    """Квадратная плитка «Смотреть все»; клик открывает полный список."""

    clicked = Signal()  # клик — главная страница откроет список

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("viewAllTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.label = QLabel("Смотреть все", self)
        self.label.setObjectName("viewAllLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.init_hover(outline_radius=12, outline_on_self=True)

    def sizeHint(self) -> QSize:
        return QSize(TILE_SIZE, TILE_SIZE)

    def minimumSizeHint(self) -> QSize:
        return QSize(TILE_SIZE, TILE_SIZE)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.label.setGeometry(self.rect())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
