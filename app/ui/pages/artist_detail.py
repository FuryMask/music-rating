"""Страница исполнителя — открывается кликом по его карточке/имени.

По ТЗ:
  • слева сверху кнопка со стрелкой налево — выход на главную;
  • ниже — КРУГЛОЕ фото артиста (или заглушка с первой буквой),
    справа от него имя (крупно) и основной жанр приглушённым цветом —
    тот же принцип, что на странице альбома (фото + название +
    строка метаданных);
  • ещё ниже — «Дискография»: карточки всех альбомов, где исполнитель
    указан АВТОРОМ или СОАВТОРОМ (artist_names). Фиты в треках чужих
    альбомов дискографию НЕ наполняют;
  • жанр, не указанный при создании, определяется автоматически:
    жанр, которого среди альбомов исполнителя больше всего
    (см. store.artist_main_genre).

Клик по карточке альбома открывает страницу альбома (сигнал
album_opened ловит главное окно). Страница живёт в QStackedWidget
рабочей зоны: верхняя полоса и сайдбар остаются на месте. Страница
прокручивается по вертикали — дискография может не влезать.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.models import Artist
from app.store import STORE
from app.ui.pages.album_detail import BackButton
from app.ui.widgets import art_cache
from app.ui.widgets.album_card import AlbumCard
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.drop_animation import run_drop_in
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import SmoothScrollArea

PHOTO_SIZE = 200        # сторона круглого фото артиста
GRID_MARGIN = 8         # запас сетки карточек под ховер-увеличение
GRID_MARGIN_TOP = 12    # сверху больше: карточка растёт вверх на ~11px
                        # (10 % от высоты 228), при 8px край «пропадал»


class ArtistDetailPage(SmoothScrollArea):
    """Страница исполнителя: фото, имя, жанр и дискография."""

    back_clicked = Signal()
    album_opened = Signal(object)  # Album — клик по карточке дискографии
    edit_requested = Signal(object)  # Artist — кнопка «Редактировать»

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("artistPage")
        self._artist: Artist | None = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget(self)
        container.setObjectName("artistContent")  # фон-градиент (QSS)
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(24)

        # --- Кнопка «назад» слева, «Редактировать» справа ---
        self.btn_back = BackButton(container)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        self.btn_edit = HoverButton("Редактировать", container)
        self.btn_edit.setObjectName("editAlbumButton")
        self.btn_edit.setToolTip("Изменить имя, фото и жанр исполнителя")
        self.btn_edit.clicked.connect(
            lambda: self.edit_requested.emit(self._artist)
        )
        back_row = QHBoxLayout()
        back_row.addWidget(self.btn_back)
        back_row.addStretch(1)
        back_row.addWidget(self.btn_edit)
        root.addLayout(back_row)

        # --- Фото + имя + жанр (как на странице альбома) ---
        info_row = QHBoxLayout()
        info_row.setSpacing(28)

        self.photo = CoverView(self, radius=PHOTO_SIZE / 2)  # круг
        self.photo.setFixedSize(PHOTO_SIZE, PHOTO_SIZE)
        info_row.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)

        text_holder = QWidget(container)
        text_col = QVBoxLayout(text_holder)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(7)

        self.lbl_name = QLabel(text_holder)
        self.lbl_name.setObjectName("detailTitle")
        self.lbl_name.setWordWrap(True)
        text_col.addWidget(self.lbl_name)

        self.lbl_genre = QLabel(text_holder)
        self.lbl_genre.setObjectName("detailMeta")
        text_col.addWidget(self.lbl_genre)

        text_col.addStretch(1)

        info_row.addWidget(text_holder, 0, Qt.AlignmentFlag.AlignVCenter)
        info_row.addStretch(1)
        root.addLayout(info_row)

        # --- Дискография ---
        self.lbl_discography = QLabel("Дискография", container)
        self.lbl_discography.setObjectName("sectionTitle")
        root.addWidget(self.lbl_discography)

        self.grid_holder = QWidget(container)
        self.grid = FlowLayout(self.grid_holder, spacing=16)
        self.grid.setContentsMargins(
            GRID_MARGIN, GRID_MARGIN_TOP, GRID_MARGIN, 0
        )
        root.addWidget(self.grid_holder)

        self.lbl_empty = QLabel(
            "Пока пусто — альбомов с участием исполнителя ещё нет",
            container,
        )
        self.lbl_empty.setObjectName("emptyHint")
        self.lbl_empty.hide()

        root.addStretch(1)

    # --- Данные ---
    @property
    def artist(self) -> Artist | None:
        """Исполнитель, показанный на странице (для стека навигации)."""
        return self._artist

    def set_artist(self, artist: Artist) -> None:
        """Показать исполнителя (клик по его карточке/имени)."""
        self._artist = artist

        # Фото: своё; если его нет — аватар-обложка (выбирается один
        # раз, см. store.artist_avatar_path); и только потом заглушка
        pixmap = art_cache.load_pixmap(
            STORE.resolve(STORE.artist_avatar_path(artist))
        )
        if pixmap is not None:
            self.photo.set_photo(pixmap)
        else:
            self.photo.set_placeholder(
                artist.display_letter, artist.display_color
            )

        self.lbl_name.setText(artist.name)
        # Жанр: указанный при создании либо авто-подсчёт по альбомам
        self.lbl_genre.setText(STORE.artist_main_genre(artist.name) or "—")

        self._rebuild_discography()
        # Анимация «падения сверху» (Task 31): «Дискография» открывается
        # с падением карточек и шапки за 0.250 с; отложенный запуск —
        # к моменту таймера страница показана и скомпонована
        QTimer.singleShot(0, self.play_drop_animation)

    def play_drop_animation(self) -> None:
        """Страница исполнителя открывается: содержимое падает сверху."""
        widgets: list[QWidget] = [
            self.btn_back, self.btn_edit, self.photo,
            self.lbl_name, self.lbl_genre, self.lbl_discography,
        ]
        widgets.extend(
            self.grid.itemAt(i).widget() for i in range(self.grid.count())
        )
        run_drop_in(widgets, block_container=self)

    def _rebuild_discography(self) -> None:
        """Карточки альбомов, где исполнитель — автор/соавтор."""
        flow = self.grid
        while flow.count():
            item = flow.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.lbl_empty:
                widget.hide()
                widget.deleteLater()

        if self._artist is None:
            albums = []
        else:
            albums = STORE.artist_albums(self._artist.name)

        if not albums:
            self.lbl_empty.show()
            flow.addWidget(self.lbl_empty)
            return

        self.lbl_empty.hide()
        for album in albums:
            card = AlbumCard(album)
            card.clicked.connect(self.album_opened.emit)
            # Явный show(): см. комментарий в collection_page._fill
            flow.addWidget(card)
            card.show()
