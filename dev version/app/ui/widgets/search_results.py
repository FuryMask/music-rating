"""Панель результатов поиска под строкой поиска.

По запросу показываются совпадения по альбомам, ТРЕКАМ и исполнителям:
  ┌────────────────────────────────────────────────┐
  │ (обложка)  After Hours                альбом   │
  │ (обложка)  Time                       трек с «After Hours» │
  │ (фото)     The Weeknd            исполнитель   │
  └────────────────────────────────────────────────┘
Строка = маленькая обложка/круглое фото (32px) + название + справа
у правого края тип результата приглушённым цветом.

Строка ТРЕКА (Task 31): обложка альбома + название трека + справа
«трек с «Альбом»» — по клику открывается альбом (сигнал
album_activated).

ВСЕ строки кликабельны (ховер — подсветка фона):
  • строка альбома → сигнал album_activated → страница альбома;
  • строка трека → тот же сигнал album_activated (альбом трека);
  • строка исполнителя → сигнал artist_activated → страница
    исполнителя с дискографией.

Исполнители в результатах — двух видов:
  1. чьё имя совпало с запросом;
  2. АВТОРЫ/СОАВТОРЫ найденных альбомов: если набрать название
     альбома, поднимутся и его исполнители. Фиты в треках чужих
     альбомов так НЕ поднимаются — только artist_names альбома.

Панель — простой дочерний виджет главного окна (не отдельное окно):
позиционирует и показывает/скрывает его MainWindow в зависимости от
текста поиска. Совпадение — без учёта регистра, подстрокой.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.models import Album, Artist
from app.store import STORE
from app.ui.widgets.cover_view import CoverView

PANEL_LIMIT = 5       # максимум результатов каждого типа
ROW_HEIGHT = 48       # высота строки результата
THUMB_SIZE = 32       # сторона миниатюры
PANEL_PAD = 6         # внутренние поля панели
ROW_GAP = 2           # расстояние между строками

ALBUM_LABEL = "альбом"
ARTIST_LABEL = "исполнитель"
TRACK_LABEL_MAX = 24  # предел названия альбома в подписи «трек с «…»»


def track_type_label(album: Album) -> str:
    """Правая подпись строки трека: «трек с «After Hours»».

    Длинное название альбома сокращается многоточием, чтобы подпись
    не съедала всё место названия трека.
    """
    title = album.title
    if len(title) > TRACK_LABEL_MAX:
        title = title[: TRACK_LABEL_MAX - 1].rstrip() + "…"
    return f"трек с «{title}»"


class SearchRow(QWidget):
    """Строка результата: миниатюра + название + тип справа."""

    activated = Signal()  # клик (только кликабельные строки)

    def __init__(self, title: str, type_label: str, thumbnail: CoverView,
                 clickable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchRow" if clickable else "searchRowPlain")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ROW_HEIGHT)
        self._clickable = clickable
        self._title = title
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 12, 8)
        row.setSpacing(10)
        row.addWidget(thumbnail)

        self.lbl_name = QLabel(title, self)
        self.lbl_name.setObjectName("searchRowName")
        row.addWidget(self.lbl_name, 1)

        self.lbl_type = QLabel(type_label, self)
        self.lbl_type.setObjectName("searchRowType")
        row.addWidget(self.lbl_type)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Длинные названия сокращаются многоточием
        available = (
            self.width() - 8 - 12 - THUMB_SIZE - 10
            - self.lbl_type.sizeHint().width() - 10
        )
        fm = QFontMetrics(self.lbl_name.font())
        self.lbl_name.setText(fm.elidedText(
            self._title, Qt.TextElideMode.ElideRight, max(40, available)
        ))

    def mousePressEvent(self, event) -> None:
        if self._clickable:
            self.activated.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class SearchResultsPanel(QWidget):
    """Список результатов под строкой поиска; собирается по запросу."""

    album_activated = Signal(object)   # Album — клик по строке альбома
    artist_activated = Signal(object)  # Artist — клик по строке исполнителя

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(PANEL_PAD, PANEL_PAD, PANEL_PAD, PANEL_PAD)
        self._layout.setSpacing(ROW_GAP)

        self.lbl_empty = QLabel("Ничего не найдено", self)
        self.lbl_empty.setObjectName("searchEmpty")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setFixedHeight(ROW_HEIGHT - 12)
        self.lbl_empty.hide()

    # --- Построение по запросу ---
    def update_for(self, query: str) -> None:
        """Пересобрать строки по тексту поиска; пустой запрос — скрыть.

        Совпадение по названию альбома поднимает и его исполнителей
        (авторов/соавторов, без фитов в чужих треках). Треки ищутся
        по названию; клик по строке трека открывает его альбом.
        """
        self._clear_rows()
        query = query.strip().casefold()
        if not query:
            self.hide()
            return

        matched_albums = [
            album for album in STORE.albums
            if query in album.title.casefold()
        ]
        albums = matched_albums[:PANEL_LIMIT]

        # Треки: совпадение по названию трека; строка несёт обложку
        # и подпись «трек с «Альбом»», клик открывает альбом
        matched_tracks: list[tuple[Album, object]] = []
        for album in STORE.albums:
            for track in album.tracks:
                if query in track.title.casefold():
                    matched_tracks.append((album, track))
        tracks = matched_tracks[:PANEL_LIMIT]

        # Исполнители: сначала авторы/соавторы найденных альбомов,
        # затем те, чьё имя само совпало с запросом; без дубликатов
        artist_rows: list[Artist] = []
        seen: set[str] = set()
        for album in matched_albums:
            for name in album.artist_names:
                low = name.casefold()
                if low in seen:
                    continue
                artist = STORE.find_artist(name)
                if artist is not None:
                    seen.add(low)
                    artist_rows.append(artist)
        for artist in STORE.artists:
            low = artist.name.casefold()
            if low in seen:
                continue
            if query in low:
                seen.add(low)
                artist_rows.append(artist)
        artists = artist_rows[:PANEL_LIMIT]

        for album in albums:
            row = SearchRow(
                album.title, ALBUM_LABEL,
                self._thumbnail(
                    letter=album.cover_letter, color=album.cover_color,
                    path=album.cover_path, circle=False,
                ),
                clickable=True, parent=self,
            )
            row.activated.connect(
                lambda album=album: self.album_activated.emit(album)
            )
            self._layout.addWidget(row)

        for album, track in tracks:
            row = SearchRow(
                track.title, track_type_label(album),
                self._thumbnail(
                    letter=album.cover_letter, color=album.cover_color,
                    path=album.cover_path, circle=False,
                ),
                clickable=True, parent=self,
            )
            row.activated.connect(
                lambda album=album: self.album_activated.emit(album)
            )
            self._layout.addWidget(row)

        for artist in artists:
            row = SearchRow(
                artist.name, ARTIST_LABEL,
                self._thumbnail(
                    letter=artist.display_letter, color=artist.display_color,
                    path=STORE.artist_avatar_path(artist), circle=True,
                ),
                clickable=True, parent=self,
            )
            row.activated.connect(
                lambda artist=artist: self.artist_activated.emit(artist)
            )
            self._layout.addWidget(row)

        if not albums and not tracks and not artists:
            self._layout.addWidget(self.lbl_empty)
            self.lbl_empty.show()
            self.setFixedHeight(self.lbl_empty.height() + PANEL_PAD * 2)
        else:
            count = len(albums) + len(tracks) + len(artists)
            self.setFixedHeight(
                count * ROW_HEIGHT + (count - 1) * ROW_GAP + PANEL_PAD * 2
            )

    # --- Внутреннее ---
    def _clear_rows(self) -> None:
        """Убрать прежние строки (подсказка «Ничего не найдено» живая)."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is self.lbl_empty:
                continue
            widget.hide()
            widget.deleteLater()
        self.lbl_empty.hide()

    def _thumbnail(self, letter: str, color: str, path: str | None,
                   circle: bool) -> CoverView:
        """Миниатюра 32px: фото (если есть) или цветная заглушка."""
        view = CoverView(
            self, letter=letter, color=color,
            radius=THUMB_SIZE / 2 if circle else 6,
        )
        view.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        resolved = STORE.resolve(path)
        if resolved is not None:
            pixmap = QPixmap(str(resolved))
            if not pixmap.isNull():
                view.set_photo(pixmap)
        return view
