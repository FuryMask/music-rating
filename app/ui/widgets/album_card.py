"""Карточка альбома.

Анатомия:
  ┌──────────────┐
  │              │  квадратная обложка (CoverView),
  │   Обложка    │  скруглённая; при наведении фото мягко
  │              │  приближается, по краю — белая обводка
  └──────────────┘
  Название альбома              ← при наведении становится белым
  ( 8.3 )                       ← оценка 0–10 в цветной «пилюле»:
                                  цвет по шкале (0–3.9 красный, 4–6.9
                                  жёлтый, 7–8.9 зелёный, 9–10 синий),
                                  фон — тот же цвет с прозрачностью

Карточка интерактивная (Hoverable): белая обводка, рост на 10 % за
250 мс, «пружина» нажатия. Внутри нет layout: дети позиционируются
вручную в resizeEvent, а sizeHint зафиксирован константой — поэтому
layout-родитель никогда не переезжает во время ховер-анимации.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from app.models import Album
from app.store import STORE
from app.theme import rating_color
from app.ui.widgets import art_cache
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import Hoverable

CARD_SIZE = 160      # сторона квадратной обложки
COVER_RADIUS = 16    # скругление углов обложки
TITLE_HEIGHT = 40    # запас под 2 строки названия
RATING_HEIGHT = 18
CARD_HEIGHT = CARD_SIZE + 8 + TITLE_HEIGHT + 2 + RATING_HEIGHT  # 228

TITLE_COLOR = "#e8e8ee"
TITLE_COLOR_HOVER = "#ffffff"
BADGE_PAD_X = 7      # отступ текста внутри «пилюли» оценки
BADGE_HEIGHT = 18


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
        pixmap = art_cache.load_pixmap(STORE.resolve(album.cover_path))
        if pixmap is not None:
            self.cover.set_photo(pixmap)

        self.title = QLabel(album.title, self)
        self.title.setObjectName("albumTitle")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"color: {TITLE_COLOR};")

        self.rating = QLabel(album.rating_text, self)
        self.rating.setObjectName("albumRating")
        # Цвет оценки по шкале: красный/жёлтый/зелёный/голубовато-синий
        self.rating.setStyleSheet(
            f"color: {rating_color(album.rating)};"
        )
        # Текст сдвинут внутрь «пилюли», которую рисует paintEvent;
        # у неоценённого альбома пилюли нет — «—» просто приглушённая
        self.rating.setContentsMargins(
            BADGE_PAD_X if album.rating is not None else 0, 0, 0, 0
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
        self.update()  # «пилюля» оценки чуть ярче при наведении

    def _apply_hover(self, on: bool) -> None:
        changed = on != self._hovered
        super()._apply_hover(on)
        if changed:
            self._update_title_color()

    def _reset_hover(self) -> None:
        super()._reset_hover()
        self._update_title_color()

    def _update_title_color(self) -> None:
        style = f"color: {TITLE_COLOR_HOVER if self._hovered else TITLE_COLOR};"
        if self.title.styleSheet() != style:
            self.title.setStyleSheet(style)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        self.cover.setGeometry(0, 0, w, w)  # квадратная обложка
        self.title.setGeometry(0, w + 8, w, TITLE_HEIGHT)
        self.rating.setGeometry(0, w + 8 + TITLE_HEIGHT + 2, w, RATING_HEIGHT)

    # --- «Пилюля» оценки ------------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_rating_badge()

    def _paint_rating_badge(self) -> None:
        """Скруглённая плашка под оценкой (цвет — по шкале, с альфой)."""
        text = self.rating.text()
        if not text or self.album.rating is None:
            return
        color = QColor(rating_color(self.album.rating))
        metrics = QFontMetrics(self.rating.font())
        width = min(
            self.width(),
            metrics.horizontalAdvance(text) + BADGE_PAD_X * 2,
        )
        top = self.rating.y() + (self.rating.height() - BADGE_HEIGHT) / 2.0
        rect = QRectF(0, top, width, BADGE_HEIGHT)

        boost = 0.45 * self._hover_progress
        fill = QColor(color)
        fill.setAlpha(int(30 + 26 * boost))
        border = QColor(color)
        border.setAlpha(int(58 + 42 * boost))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                7, 7)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.album)
        super().mousePressEvent(event)
