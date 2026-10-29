"""Карточка альбома.

Анатомия:
  ┌──────────────┐
  │              │  квадратная обложка (CoverView),
  │   Обложка    │  скруглённая
  │              │
  └──────────────┘
  Название альбома
  8.3              ← оценка 0–10, шаг 0.1; цвет по шкале
                     (0–3.9 красный, 4–6.9 жёлтый, 7–8.9 зелёный,
                     9–10 голубовато-синий)

Карточка интерактивная (Hoverable): белая обводка + увеличение
на 10 % за 250 мс при наведении.

Внутри нет layout: дети позиционируются вручную в resizeEvent,
а sizeHint зафиксирован константой — поэтому layout-родитель
никогда не переезжает во время ховер-анимации.
"""

from PySide6.QtCore import QSize, Signal
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from app.models import Album
from app.store import STORE
from app.theme import rating_color
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import Hoverable

CARD_SIZE = 160      # сторона квадратной обложки
COVER_RADIUS = 12    # скругление углов обложки
TITLE_HEIGHT = 40    # запас под 2 строки названия
RATING_HEIGHT = 18
CARD_HEIGHT = CARD_SIZE + 8 + TITLE_HEIGHT + 2 + RATING_HEIGHT  # 228


class AlbumCard(Hoverable, QWidget):
    """Карточка альбома; клик открывает страницу альбома."""

    clicked = Signal(object)  # Album этой карточки

    def __init__(self, album: Album, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.album = album
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.cover = CoverView(
            self, letter=album.cover_letter,
            color=album.cover_color, radius=COVER_RADIUS,
        )
        path = STORE.resolve(album.cover_path)
        if path is not None:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.cover.set_photo(pixmap)

        self.title = QLabel(album.title, self)
        self.title.setObjectName("albumTitle")
        self.title.setWordWrap(True)

        self.rating = QLabel(album.rating_text, self)
        self.rating.setObjectName("albumRating")
        # Цвет оценки по шкале: красный/жёлтый/зелёный/голубовато-синий
        self.rating.setStyleSheet(
            f"color: {rating_color(album.rating)};"
        )

        # Обводку рисует CoverView (ребёнок), поэтому на себе не рисуем
        self.init_hover(outline_radius=COVER_RADIUS, outline_on_self=False)

    # --- Фиксированные хинты: layout-родитель стабильнее во время ховера ---
    def sizeHint(self) -> QSize:
        return QSize(CARD_SIZE, CARD_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(CARD_SIZE, CARD_HEIGHT)

    def _on_hover_progress(self, value: float) -> None:
        self.cover.set_outline(value)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        self.cover.setGeometry(0, 0, w, w)  # квадратная обложка
        self.title.setGeometry(0, w + 8, w, TITLE_HEIGHT)
        self.rating.setGeometry(0, w + 8 + TITLE_HEIGHT + 2, w, RATING_HEIGHT)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.album)
        super().mousePressEvent(event)
