"""Домашняя страница — первая страница рабочей зоны.

Секции (сверху вниз):
  1. Недавно оценённые — самые свежие оценки, которые помещаются
     в один ряд по ширине окна.
  2. Оценённые альбомы — альбомы с оценкой, новые карточки
     добавляются в начало; в ряду максимум 7 + плитка «Смотреть все»,
     если альбомов больше семи.
  3. Неоценённые альбомы — альбомы без оценки, новее — раньше;
     максимум 7 + плитка «Смотреть все».
  4. Исполнители — все исполнители базы, новее — раньше;
     максимум 7 + плитка «Смотреть все».

Клики:
  • карточка альбома → сигнал album_opened (страница альбома);
  • карточка исполнителя → сигнал artist_opened (страница
    исполнителя с дискографией);
  • плитка «Смотреть все» → сигнал view_all с режимом
    ("rated" / "unrated" / "artists") — главное окно открывает
    полный список (см. pages/collection_page.py).

set_cards() перестраивает секции; refresh() вызывается после каждого
изменения базы (создание/удаление альбома). Заглушки больше нет —
до первых данных сегменты показывают «Пока пусто».
"""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from app.models import Album, Artist
from app.store import STORE
from app.ui.pages.collection_page import MODE_ARTISTS, MODE_RATED, MODE_UNRATED
from app.ui.widgets import AlbumCard, ArtistCard, Section, ViewAllTile
from app.ui.widgets.album_card import CARD_SIZE
from app.ui.widgets.drop_animation import run_drop_in
from app.ui.widgets.motion import BASE_MS, SmoothScrollArea
from app.ui.widgets.section import CARD_SPACING, EDGE_PAD

PAGE_MARGIN = 28          # отступы страницы от краёв рабочей зоны
SECTION_GAP = 24          # расстояние между секциями
ROW_CAP = 7               # максимум альбомов/исполнителей в ряду


class HomePage(SmoothScrollArea):
    """Главная страница; клики по карточкам — сигналы навигации."""

    album_opened = Signal(object)   # Album — клик по карточке альбома
    artist_opened = Signal(object)  # Artist — клик по карточке исполнителя
    view_all = Signal(str)          # режим полного списка

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget(self)
        container.setObjectName("homeContent")
        self.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(SECTION_GAP)

        self.section_recent = Section("Недавно оценённые", [], container)
        self.section_rated = Section("Оценённые альбомы", [], container)
        self.section_unrated = Section("Неоценённые альбомы", [], container)
        self.section_artists = Section("Исполнители", [], container)

        layout.addWidget(self.section_recent)
        layout.addWidget(self.section_rated)
        layout.addWidget(self.section_unrated)
        layout.addWidget(self.section_artists)
        layout.addStretch(1)

        self._signature = None
        self._recent_albums: list[Album] = []
        self._recent_count = 0
        self._recent_resize = QTimer(self, singleShot=True, interval=0)
        self._recent_resize.timeout.connect(self._refresh_recent)
        self.viewport().installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._recent_resize.start()
        return super().eventFilter(watched, event)

    # --- Появление страницы (Task 39) ---
    def play_entrance(self) -> None:
        """Карточки всех секций «раскрываются» каскадом.

        Вызывается главным окном, когда главная становится видимой
        (возврат «назад», переключение режима). Первый показ окна
        анимирует разделы целиком (см. drop_animation в MainWindow) —
        здесь только карточки, чтобы не спорить с той анимацией.
        """
        if not self.isVisible():
            return
        cards: list[QWidget] = []
        for section in (self.section_recent, self.section_rated,
                        self.section_unrated, self.section_artists):
            cards.extend(section.cards())
        run_drop_in(cards, ms=BASE_MS + 20, offset=14, stagger=22)

    # --- Перестройка по данным базы ---
    def _data_signature(self) -> tuple:
        """Отпечаток данных, от которых зависят секции главной.

        Позволяет НЕ пересобирать десятки карточек, если ничего не
        изменилось (обычный возврат на главную — Task 45). В отпечаток
        входят поля, влияющие на внешний вид: название, обложка, оценка,
        дата оценки, имя/фото/аватар исполнителя.
        """
        albums = tuple(
            (a.id, a.title, a.rating, a.rated_at, a.cover_path)
            for a in STORE.albums
        )
        artists = tuple(
            (a.name, a.genre, a.photo_path, a.avatar_path)
            for a in STORE.artists
        )
        return albums, artists

    def refresh(self, force: bool = False) -> None:
        """Перестроить секции, если данные изменились (или force=True)."""
        signature = self._data_signature()
        if not force and signature == self._signature:
            return  # ничего не поменялось — карточки уже актуальны
        rated = [a for a in STORE.albums if a.rating is not None]
        self._recent_albums = sorted(rated, key=lambda a: a.rated_at or "", reverse=True)
        unrated = [a for a in reversed(STORE.albums) if a.rating is None]
        # «Исполнители» — новее — раньше
        artists = list(reversed(STORE.artists))

        self._refresh_recent(force=True)
        self.section_rated.set_cards(self._album_cards(list(reversed(rated)), MODE_RATED))
        self.section_unrated.set_cards(self._album_cards(unrated, MODE_UNRATED))
        self.section_artists.set_cards(self._artist_cards(artists))
        # Пересчитываем отпечаток ПОСЛЕ сборки: artist_avatar_path()
        # мог назначить аватар-обложку, и следующий вызов не должен
        # из-за этого пересобирать секции ещё раз
        self._signature = self._data_signature()

    def _refresh_recent(self, force: bool = False) -> None:
        width = self.viewport().width() - 2 * (PAGE_MARGIN + EDGE_PAD)
        capacity = max(0, (width + CARD_SPACING) // (CARD_SIZE + CARD_SPACING))
        count = min(capacity, len(self._recent_albums))
        if force or count != self._recent_count:
            self._recent_count = count
            self.section_recent.set_cards([self._album_card(album) for album in self._recent_albums[:count]])

    def _album_card(self, album: Album) -> AlbumCard:
        card = AlbumCard(album)
        card.clicked.connect(self.album_opened.emit)
        return card

    def _album_cards(self, albums: list[Album], mode: str) -> list[QWidget]:
        cards: list[QWidget] = [self._album_card(album) for album in albums[:ROW_CAP]]
        if len(albums) > ROW_CAP:
            tile = ViewAllTile()
            tile.clicked.connect(lambda: self.view_all.emit(mode))
            cards.append(tile)
        return cards

    def _artist_cards(self, artists: list[Artist]) -> list[QWidget]:
        cards: list[QWidget] = []
        for artist in artists[:ROW_CAP]:
            card = ArtistCard(artist)
            card.clicked.connect(self.artist_opened.emit)
            cards.append(card)
        if len(artists) > ROW_CAP:
            tile = ViewAllTile()
            tile.clicked.connect(lambda: self.view_all.emit(MODE_ARTISTS))
            cards.append(tile)
        return cards
