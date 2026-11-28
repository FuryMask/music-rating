"""Полные списки «Смотреть все» — открываются по плитке на главной.

Режимы (CollectionPage.show_mode):
  "recent"  — «Недавно оценённые»: оценённые альбомы начиная с
              последнего оценённого и до первого оценённого
              (rated_at по убыванию);
  "rated"   — «Оценённые альбомы»: альбомы с оценкой, новее — раньше;
  "unrated" — «Неоценённые альбомы»: альбомы без оценки, новее — раньше;
  "albums"  — «Альбомы»: вся медиатека, новее — раньше;
  "artists" — «Исполнители»: все исполнители базы, новее — раньше
              (как и с обычными альбомами).

Сверху — кнопка «назад» и заголовок; ниже — сетка карточек с
переносом (FlowLayout): клик открывает страницу альбома/исполнителя.
Пустой список — приглушённое «Пока пусто».
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.store import STORE
from app.ui.pages.album_detail import BackButton
from app.ui.widgets.album_card import AlbumCard
from app.ui.widgets.artist_card import ArtistCard
from app.ui.widgets.drop_animation import run_drop_in
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.motion import SmoothScrollArea

GRID_MARGIN = 8     # запас сетки карточек под ховер-увеличение
GRID_MARGIN_TOP = 12  # сверху больше: карточка растёт вверх на ~11px
                      # (10 % от высоты 228), при 8px край «пропадал»

MODE_RECENT = "recent"
MODE_RATED = "rated"
MODE_UNRATED = "unrated"
MODE_ALBUMS = "albums"
MODE_ARTISTS = "artists"

MODE_TITLES = {
    MODE_RECENT: "Недавно оценённые",
    MODE_RATED: "Оценённые альбомы",
    MODE_UNRATED: "Неоценённые альбомы",
    MODE_ALBUMS: "Альбомы",
    MODE_ARTISTS: "Исполнители",
}


class CollectionPage(SmoothScrollArea):
    """Страница полного списка (режим — один из MODE_*)."""

    back_clicked = Signal()
    album_opened = Signal(object)   # Album — клик по карточке альбома
    artist_opened = Signal(object)  # Artist — клик по карточке исполнителя

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("collectionPage")
        self.mode: str = MODE_ALBUMS  # текущий режим (для стека навигации)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget(self)
        container.setObjectName("collectionContent")  # фон-градиент (QSS)
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(20)

        # --- Кнопка «назад» + заголовок ---
        self.btn_back = BackButton(container)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        head = QHBoxLayout()
        head.addWidget(self.btn_back)
        head.addSpacing(12)
        self.lbl_title = QLabel(container)
        self.lbl_title.setObjectName("detailTitle")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        root.addLayout(head)

        # --- Сетка карточек ---
        self.grid_holder = QWidget(container)
        self.grid = FlowLayout(self.grid_holder, spacing=16)
        self.grid.setContentsMargins(
            GRID_MARGIN, GRID_MARGIN_TOP, GRID_MARGIN, 0
        )
        root.addWidget(self.grid_holder)

        self.lbl_empty = QLabel("Пока пусто", container)
        self.lbl_empty.setObjectName("emptyHint")
        self.lbl_empty.hide()

        root.addStretch(1)

    # --- Режимы ---
    def show_mode(self, mode: str) -> None:
        """Заполнить страницу списком выбранного режима."""
        self.mode = mode
        self.lbl_title.setText(MODE_TITLES.get(mode, ""))
        self._clear_grid()

        if mode == MODE_ARTISTS:
            cards: list[QWidget] = [
                self._artist_card(artist)
                for artist in reversed(STORE.artists)
            ]
        else:
            candidates = STORE.albums
            if mode in (MODE_RECENT, MODE_RATED):
                candidates = [a for a in candidates if a.rating is not None]
            elif mode == MODE_UNRATED:
                candidates = [a for a in candidates if a.rating is None]
            date_field = "rated_at" if mode == MODE_RECENT else "created_at"
            albums = sorted(candidates, key=lambda album: getattr(album, date_field) or "", reverse=True)
            cards = [self._album_card(album) for album in albums]

        self._fill(cards)
        # Анимация «падения сверху» (Task 31): карточки, заголовок и
        # кнопка «назад» падают с проявлением за 0.250 с. Отложенный
        # запуск: к моменту таймера страница уже показана и скомпонована
        QTimer.singleShot(0, self.play_drop_animation)

    def play_drop_animation(self) -> None:
        """«Смотреть все» открывается: содержимое падает сверху."""
        widgets: list[QWidget] = [self.btn_back, self.lbl_title]
        widgets.extend(
            self.grid.itemAt(i).widget() for i in range(self.grid.count())
        )
        run_drop_in(widgets, block_container=self)

    # --- Внутреннее ---
    def _fill(self, cards: list[QWidget]) -> None:
        if not cards:
            self.lbl_empty.show()
            self.grid.addWidget(self.lbl_empty)
            return
        self.lbl_empty.hide()
        for card in cards:
            # Явный show(): безродный виджет, добавленный в УЖЕ видимый
            # контейнер через layout, сам не показывается (показ случился
            # бы только при следующем show() страницы — например, при
            # переключении режима, когда страница уже открыта)
            self.grid.addWidget(card)
            card.show()

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.lbl_empty:
                widget.hide()
                widget.deleteLater()
        self.lbl_empty.hide()

    def _album_card(self, album) -> QWidget:
        card = AlbumCard(album)
        card.clicked.connect(self.album_opened.emit)
        return card

    def _artist_card(self, artist) -> QWidget:
        card = ArtistCard(artist)
        card.clicked.connect(self.artist_opened.emit)
        return card
