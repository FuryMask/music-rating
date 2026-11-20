"""Карточка исполнителя на главной странице и в списках.

Анатомия:
      ╭──────────────╮
     │    (фото)      │   круглая обложка/заглушка (CoverView
      ╰──────────────╯   с радиусом в половину стороны)
     Имя исполнителя
     8.4              ← средняя оценка его альбомов, цвет по шкале

Вместо жанра под именем показывается средняя оценка всех альбомов
исполнителя (STORE.artist_average_rating). Фиты в чужих треках на
среднее НЕ влияют — считаются только альбомы, где исполнитель
автор (artist_names). Если оценённых альбомов нет — «—»
приглушённым цветом.

Task 39: фото так же «дышит» при наведении (приближение 5 %), имя
становится белым — карточка ведёт себя как альбомная.

Клик по карточке открывает страницу исполнителя с дискографией
(сигнал clicked ловит главная страница / список «Исполнители»)."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from app.models import Artist
from app.store import STORE
from app.theme import TEXT_MUTED, rating_color
from app.ui.widgets import art_cache
from app.ui.widgets.album_card import CARD_HEIGHT, CARD_SIZE
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import Hoverable

NAME_HEIGHT = 20
RATING_HEIGHT = 16
NAME_COLOR = "#e8e8ee"
NAME_COLOR_HOVER = "#ffffff"


class ArtistCard(Hoverable, QWidget):
    """Круглая карточка исполнителя; клик открывает его страницу."""

    clicked = Signal(object)  # Artist этой карточки

    def __init__(self, artist: Artist, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.artist = artist
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.photo = CoverView(
            self, letter=artist.display_letter,
            color=artist.display_color, radius=CARD_SIZE / 2,  # круг
        )
        # Фото: своё; если нет — аватар-обложка (один раз, см. store)
        pixmap = art_cache.load_pixmap(
            STORE.resolve(STORE.artist_avatar_path(artist))
        )
        if pixmap is not None:
            self.photo.set_photo(pixmap)

        self.name = QLabel(artist.name, self)
        self.name.setObjectName("artistName")
        self.name.setStyleSheet(f"color: {NAME_COLOR};")

        # Средняя оценка альбомов исполнителя вместо жанра
        average = STORE.artist_average_rating(artist.name)
        self.rating = QLabel(
            f"{average:.1f}" if average is not None else "—", self
        )
        self.rating.setObjectName("artistRating")
        self.rating.setStyleSheet(
            f"color: {rating_color(average) if average is not None else TEXT_MUTED};"
        )

        # Обводку рисует CoverView (ребёнок), на себе не рисуем
        self.init_hover(outline_radius=CARD_SIZE / 2, outline_on_self=False)

    # --- Фиксированные хинты: высота как у карточки альбома ---
    def sizeHint(self) -> QSize:
        return QSize(CARD_SIZE, CARD_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(CARD_SIZE, CARD_HEIGHT)

    def _on_hover_progress(self, value: float) -> None:
        self.photo.set_outline(value)

    def _apply_hover(self, on: bool) -> None:
        changed = on != self._hovered
        super()._apply_hover(on)
        if changed:
            self._update_name_color()

    def _reset_hover(self) -> None:
        super()._reset_hover()
        self._update_name_color()

    def _update_name_color(self) -> None:
        style = f"color: {NAME_COLOR_HOVER if self._hovered else NAME_COLOR};"
        if self.name.styleSheet() != style:
            self.name.setStyleSheet(style)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        self.photo.setGeometry(0, 0, w, w)
        self.name.setGeometry(0, w + 10, w, NAME_HEIGHT)
        self.rating.setGeometry(0, w + 10 + NAME_HEIGHT + 2, w, RATING_HEIGHT)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.artist)
        super().mousePressEvent(event)
