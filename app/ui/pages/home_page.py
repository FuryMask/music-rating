"""Домашняя страница — первая страница рабочей зоны.

Секции (сверху вниз):
  1. Недавно оценённые — очередь оценённых альбомов: свежая оценка
     встаёт на первую позицию, остальные сдвигаются вправо; в ряду
     максимум 7 + плитка «Смотреть все», если оценённых больше семи
     (более старые оценки остаются за плиткой).
  2. Оценённые альбомы — все созданные альбомы, новые карточки
     добавляются в начало; в ряду максимум 7 + плитка «Смотреть все»,
     если альбомов больше семи.
  3. Исполнители — все исполнители базы, новее — раньше;
     максимум 7 + плитка «Смотреть все».

Клики:
  • карточка альбома → сигнал album_opened (страница альбома);
  • карточка исполнителя → сигнал artist_opened (страница
    исполнителя с дискографией);
  • плитка «Смотреть все» → сигнал view_all с режимом
    ("recent" / "albums" / "artists") — главное окно открывает
    полный список (см. pages/collection_page.py).

set_cards() перестраивает секции; refresh() вызывается после каждого
изменения базы (создание/удаление альбома). Заглушки больше нет —
до первых данных сегменты показывают «Пока пусто».
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from app.models import Album, Artist
from app.store import STORE
from app.ui.widgets import AlbumCard, ArtistCard, Section, ViewAllTile
from app.ui.widgets.drop_animation import run_drop_in
from app.ui.widgets.motion import BASE_MS, SmoothScrollArea

PAGE_MARGIN = 28          # отступы страницы от краёв рабочей зоны
SECTION_GAP = 24          # расстояние между секциями
ROW_CAP = 7               # максимум альбомов/исполнителей в ряду


class HomePage(SmoothScrollArea):
    """Главная страница; клики по карточкам — сигналы навигации."""

    album_opened = Signal(object)   # Album — клик по карточке альбома
    artist_opened = Signal(object)  # Artist — клик по карточке исполнителя
    view_all = Signal(str)          # "recent"/"albums"/"artists" — плитка

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
        self.section_artists = Section("Исполнители", [], container)

        layout.addWidget(self.section_recent)
        layout.addWidget(self.section_rated)
        layout.addWidget(self.section_artists)
        layout.addStretch(1)

        self._signature = None
        self.refresh()

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
                        self.section_artists):
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
        # Очередь «Недавно оценённых»: последняя оценённый — первым.
        # Среза до 7 здесь НЕТ — если оценённых больше семи, плитку
        # «Смотреть все» добавит _album_cards (как в других секциях)
        recent = sorted(rated, key=lambda a: a.rated_at or "", reverse=True)
        # «Оценённые альбомы» — все альбомы, новее — раньше
        albums = list(reversed(STORE.albums))
        # «Исполнители» — новее — раньше
        artists = list(reversed(STORE.artists))

        self.section_recent.set_cards(self._album_cards(recent, "recent"))
        self.section_rated.set_cards(self._album_cards(albums, "albums"))
        self.section_artists.set_cards(self._artist_cards(artists))
        # Пересчитываем отпечаток ПОСЛЕ сборки: artist_avatar_path()
        # мог назначить аватар-обложку, и следующий вызов не должен
        # из-за этого пересобирать секции ещё раз
        self._signature = self._data_signature()

    def _album_cards(self, albums: list[Album], mode: str) -> list[QWidget]:
        cards: list[QWidget] = []
        for album in albums[:ROW_CAP]:
            card = AlbumCard(album)
            card.clicked.connect(self.album_opened.emit)
            cards.append(card)
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
            tile.clicked.connect(lambda: self.view_all.emit("artists"))
            cards.append(tile)
        return cards
