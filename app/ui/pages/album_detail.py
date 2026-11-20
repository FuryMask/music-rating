"""Страница альбома — открывается в рабочей зоне по клику на карточку.

По ТЗ:
  • слева сверху кнопка со стрелкой налево — выход (на шаг назад);
  • под ней обложка альбома;
  • справа от обложки НАД названием — откуда альбом: «Создано с
    помощью» + ЛОГОТИП Deezer (если альбом создан по ссылке) или
    «Создано вручную»; ниже — название, исполнители, «год · жанр»,
    ниже — оценка (цвет по шкале; только когда альбом оценён в
    мастере оценивания);
  • НА УРОВНЕ ОБЛОЖКИ, в самом правом краю — сообщение «Этот альбом
    ещё не оценили» и синяя кнопка «Оценить?» (сигнал
    rate_requested): так начинается мастер оценивания. Видны только
    пока у альбома нет оценки (Task 22);
  • ПОД ШАПКОЙ — треклист или ОЦЕНКИ (Task 22):
      – альбом НЕ оценён → обычный треклист (№, название,
        исполнители трека);
      – альбом оценён → сетка оценок, как на шаге «Оценки» мастера
        оценивания: шапка с именами участников, в строках треков —
        оценки каждого (секретная 11 подсвечена золотым), внизу —
        «Средняя оценка» каждого участника. Всё только для чтения;
  • имена исполнителей КЛИКАБЕЛЬНЫ: клик открывает страницу
    исполнителя (сигнал artist_opened ловит главное окно);
  • справа сверху «Выгрузить» (НЕАКТИВНА — сетевые функции отложены;
    подсказка «В разработке»), «Редактировать» (открывает мастер с
    заполненными данными, сигнал edit_requested) и «Удалить»
    (подтверждение, сигнал delete_requested).

Страница живёт в QStackedWidget рабочей зоны: верхняя полоса и
сайдбар остаются на месте.
"""

from pathlib import Path
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.models import Album, AlbumRatings
from app.store import STORE
from app.theme import ACCENT, rating_color
from app.ui.pages.rate_album import (
    RATE_ARTISTS_W,
    RATE_CELL_H,
    RATE_CELL_W,
    SECRET_VALUE,
)
from app.ui.widgets import art_cache
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.drop_animation import run_drop_in
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import BASE_MS, SmoothScrollArea
from app.ui.widgets.track_row import TRACK_INDEX_WIDTH, TRACK_ROW_HEIGHT

COVER_RADIUS = 12
DETAIL_COVER = 200     # сторона обложки на странице альбома
DETAIL_TITLE_MAX = 520  # максимальная ширина названия до переноса
RATE_SIDE_PAD = 8      # запас по краям блока «Оценить?» под ховер-рост
GRID_HEAD_H = 40       # высота шапки и итоговой строки сетки оценок

# Логотипы источников для строки «Создано с помощью …» (файлы рядом
# с кодом приложения; если файла нет — строка показывается без лого)
DEEZER_LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "deezer_logo.png"
)
SPOTIFY_LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "spotify_logo.png"
)
YTMUSIC_LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "ytmusic_logo.png"
)
GENIUS_LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "genius_logo.png"
)
YANDEX_LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "yandex_music_logo.png"
)


def _fmt_rating(value: float | None) -> str:
    """Оценка строкой: 8.4 / «—» (клетка не заполнена)."""
    return f"{value:.1f}" if value is not None else "—"


class BackButton(HoverButton):
    """Кнопка «назад»: стрелка налево нарисована линиями."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=10)
        self.setObjectName("backButton")
        self.setFixedSize(40, 40)
        self.setToolTip("Назад")
        self.setIcon(line_icon("back"))


class AlbumDetailPage(QWidget):
    """Страница альбома в рабочей зоне."""

    back_clicked = Signal()
    delete_requested = Signal(object)  # Album — «Удалить» → подтверждение
    edit_requested = Signal(object)    # Album — «Редактировать» → мастер
    rate_requested = Signal(object)    # Album — «Оценить?» → мастер оценки
    artist_opened = Signal(str)        # имя исполнителя — клик по ссылке

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("albumPage")
        # Без этого флага QSS-фон страницы (мягкий градиент) не рисуется
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._album: Album | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(20)

        # --- Кнопка «назад» слева, «Выгрузить»/«Редактировать»/«Удалить»
        # справа ---
        self.btn_back = BackButton(self)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        # «Выгрузить» — публикация альбома в облако; сетевые функции
        # пока отложены. Кнопка НЕАКТИВНА (setEnabled(False) — клики
        # невозможны), но подсказка при наведении работает: Qt
        # доставляет ToolTip и отключённым виджетам (проверено).
        # Отдельный стиль #uploadAlbumButton:disabled — серая, как
        # неактивные поля мастера.
        self.btn_upload = HoverButton("Выгрузить", self)
        self.btn_upload.setObjectName("uploadAlbumButton")
        self.btn_upload.setToolTip("В разработке")
        self.btn_upload.setEnabled(False)
        self.btn_upload.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_edit = HoverButton("Редактировать", self)
        self.btn_edit.setObjectName("editAlbumButton")
        self.btn_edit.setToolTip("Изменить данные альбома")
        self.btn_edit.clicked.connect(
            lambda: self.edit_requested.emit(self._album)
        )
        self.btn_delete = HoverButton("Удалить", self)
        self.btn_delete.setObjectName("deleteAlbumButton")
        self.btn_delete.setToolTip("Удалить альбом из библиотеки")
        self.btn_delete.clicked.connect(
            lambda: self.delete_requested.emit(self._album)
        )
        back_row = QHBoxLayout()
        # Зазор между «Выгрузить»/«Редактировать» и «Удалить» — ЗДЕСЬ, а
        # не margin в QSS: обводка ховера рисуется по всей ширине
        # виджета, и margin-right в QSS делал её длиннее самой кнопки
        # (Task 19)
        back_row.setSpacing(10)
        back_row.addWidget(self.btn_back)
        back_row.addStretch(1)
        back_row.addWidget(self.btn_upload)   # слева от «Редактировать»
        back_row.addWidget(self.btn_edit)
        back_row.addWidget(self.btn_delete)
        root.addLayout(back_row)

        # --- Обложка + блок информации справа от неё ---
        info_row = QHBoxLayout()
        info_row.setSpacing(28)

        # Надпись «old» НАД обложкой (на всех альбомах, без условий) —
        # обложка обёрнута в колонку: надпись сверху, обложка под ней
        cover_holder = QWidget(self)
        cover_col = QVBoxLayout(cover_holder)
        cover_col.setContentsMargins(0, 0, 0, 0)
        cover_col.setSpacing(5)
        self.lbl_old_mark = QLabel("old", cover_holder)
        self.lbl_old_mark.setObjectName("oldCoverMark")
        cover_col.addWidget(self.lbl_old_mark)

        self.cover = CoverView(
            cover_holder, radius=COVER_RADIUS,
        )
        self.cover.setFixedSize(DETAIL_COVER, DETAIL_COVER)
        cover_col.addWidget(self.cover)
        info_row.addWidget(cover_holder, 0, Qt.AlignmentFlag.AlignTop)

        # Текстовый блок центрируется по вертикали относительно обложки
        text_holder = QWidget(self)
        text_col = QVBoxLayout(text_holder)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(7)

        # Откуда альбом: «Создано с помощью» + логотип (по ссылке
        # Deezer) или «Создано вручную» — над названием. Текст СЛЕВА,
        # логотип СПРАВА, само слово «Deezer» в тексте не пишется —
        # его заменяет пиктограмма (Task 20). Логотип — ОТДЕЛЬНОЙ
        # QLabel-пиктограммой: rich-text <img> внутри одной надписи
        # даёт ненадёжный sizeHint, и строка обрезалась.
        self.source_icon = QLabel(text_holder)
        self.source_icon.setObjectName("detailSource")
        self.lbl_source = QLabel(text_holder)
        self.lbl_source.setObjectName("detailSource")
        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(7)
        source_row.addWidget(self.lbl_source)   # текст слева…
        source_row.addWidget(self.source_icon)  # …логотип справа
        source_row.addStretch(1)
        text_col.addLayout(source_row)

        self.lbl_title = QLabel(text_holder)
        self.lbl_title.setObjectName("detailTitle")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setMaximumWidth(DETAIL_TITLE_MAX)
        text_col.addWidget(self.lbl_title)

        # Имена исполнителей — ссылки на их страницы (rich text)
        self.lbl_artists = QLabel(text_holder)
        self.lbl_artists.setObjectName("detailArtists")
        self.lbl_artists.setMaximumWidth(DETAIL_TITLE_MAX)
        self.lbl_artists.setWordWrap(True)
        self.lbl_artists.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_artists.setOpenExternalLinks(False)
        self.lbl_artists.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.lbl_artists.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_artists.setToolTip("Нажмите на имя, чтобы открыть страницу исполнителя")
        self.lbl_artists.linkActivated.connect(self._open_artist_link)
        text_col.addWidget(self.lbl_artists)

        self.lbl_meta = QLabel(text_holder)
        self.lbl_meta.setObjectName("detailMeta")
        text_col.addWidget(self.lbl_meta)

        # Оценка альбома (цвет по шкале) — под «год · жанр»; видна
        # только когда альбом оценён (мастер оценивания)
        self.lbl_rating = QLabel(text_holder)
        self.lbl_rating.setObjectName("detailRating")
        self.lbl_rating.hide()
        text_col.addWidget(self.lbl_rating)

        text_col.addStretch(1)

        info_row.addWidget(text_holder, 0, Qt.AlignmentFlag.AlignVCenter)
        info_row.addStretch(1)

        # --- «Этот альбом ещё не оценили» + синяя кнопка «Оценить?» —
        # на уровне обложки, В САМОМ ПРАВОМ краю (Task 22, п. 4).
        # Поля держателя — запас под ховер-рост кнопки, иначе её края
        # срезаются границей держателя
        self.rate_side = QWidget(self)
        rate_v = QVBoxLayout(self.rate_side)
        rate_v.setContentsMargins(
            RATE_SIDE_PAD, RATE_SIDE_PAD, RATE_SIDE_PAD, RATE_SIDE_PAD
        )
        rate_v.setSpacing(12)
        self.lbl_not_rated = QLabel("Этот альбом ещё не оценили", self.rate_side)
        self.lbl_not_rated.setObjectName("notRatedHint")
        self.lbl_not_rated.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        rate_v.addWidget(self.lbl_not_rated)
        self.btn_rate = HoverButton("Оценить?", self.rate_side)
        self.btn_rate.setObjectName("rateNowButton")
        self.btn_rate.setToolTip("Открыть оценивание альбома")
        self.btn_rate.clicked.connect(
            lambda: self.rate_requested.emit(self._album)
        )
        rate_v.addWidget(self.btn_rate, 0, Qt.AlignmentFlag.AlignHCenter)
        info_row.addWidget(self.rate_side, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(info_row)

        # --- Треклист или сетка оценок (Task 22, п. 4) -------------
        # Сегмент как треклист мастера: тянется на всё свободное
        # место, при переполнении — прокрутка. Наполнение меняется
        # в _rebuild_tracks: у неоценённого альбома — обычный
        # треклист, у оценённого — сетка оценок участников
        self.tracks_frame = QFrame(self)
        self.tracks_frame.setObjectName("trackListFrame")
        self.tracks_frame.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        frame_v = QVBoxLayout(self.tracks_frame)
        frame_v.setContentsMargins(10, 6, 10, 6)
        frame_v.setSpacing(0)
        self.tracks_area = SmoothScrollArea(self.tracks_frame)
        self.tracks_area.setWidgetResizable(True)
        self.tracks_area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self.tracks_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tracks_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tracks_container = QWidget()
        self.tracks_v = QVBoxLayout(self.tracks_container)
        self.tracks_v.setContentsMargins(0, 0, 0, 0)
        self.tracks_v.setSpacing(0)
        self.tracks_area.setWidget(self.tracks_container)
        frame_v.addWidget(self.tracks_area)
        root.addWidget(self.tracks_frame, 1)

    # --- Данные ---
    @property
    def album(self) -> Album | None:
        """Альбом, показанный на странице (для стека навигации)."""
        return self._album

    def set_album(self, album: Album) -> None:
        """Показать альбом (клик по карточке на главной)."""
        self._album = album

        pixmap = art_cache.load_pixmap(STORE.resolve(album.cover_path))
        if pixmap is not None:
            self.cover.set_photo(pixmap)
        else:
            self.cover.set_placeholder(album.cover_letter, album.cover_color)

        self.lbl_title.setText(album.title)
        self.lbl_artists.setText(self._artists_html(album))
        self.lbl_meta.setText(album.meta_text)
        self._set_source(album)
        self._sync_rating(album)
        self._rebuild_tracks(album)
        # Появление содержимого (Task 39): строки треклиста/оценок
        # «всплывают» каскадом. Отложенно — страницу сейчас покажет
        # главное окно, и к моменту таймера строки уже видимы
        QTimer.singleShot(0, self.play_entrance)

    def play_entrance(self) -> None:
        """Каскадное появление строк нижнего сегмента."""
        if not self.isVisible():
            return
        rows: list[QWidget] = []
        for index in range(self.tracks_v.count()):
            widget = self.tracks_v.itemAt(index).widget()
            if widget is not None:
                rows.append(widget)
        run_drop_in(rows, ms=BASE_MS - 20, offset=10, stagger=24)

    # --- Откуда альбом ----------------------------------------------------
    def _set_source(self, album: Album) -> None:
        """Строка над названием: «Создано с помощью <лого>» или вручную.

        Лого выбирается по source_id: «spotify:<id>» — Spotify,
        «ytmusic:<id>» — YouTube Music, «genius:<id>» — Genius,
        «yandex:<id>» — Яндекс Музыка, иначе — Deezer (у альбомов,
        созданных по ссылке, он).
        """
        pixmap = None
        text = "Создано вручную"
        if album.source_id:
            text = "Создано с помощью"
            if album.source_id.startswith("spotify:"):
                logo_path = SPOTIFY_LOGO_PATH
                logo_height = 14   # квадратная иконка
            elif album.source_id.startswith("ytmusic:"):
                logo_path = YTMUSIC_LOGO_PATH
                logo_height = 14   # круглый значок, как у Spotify
            elif album.source_id.startswith("genius:"):
                logo_path = GENIUS_LOGO_PATH
                logo_height = 14   # круглый значок, как у Spotify
            elif album.source_id.startswith("yandex:"):
                logo_path = YANDEX_LOGO_PATH
                logo_height = 14   # круглый значок, как у Spotify
            else:
                logo_path = DEEZER_LOGO_PATH
                logo_height = 13
            if logo_path.exists():
                logo = QPixmap(str(logo_path))
                if not logo.isNull():
                    pixmap = logo.scaledToHeight(
                        logo_height, Qt.TransformationMode.SmoothTransformation
                    )
        if pixmap is not None:
            self.source_icon.setPixmap(pixmap)
            self.source_icon.show()
        else:
            self.source_icon.hide()
        self.lbl_source.setText(text)

    # --- Оценка: строка под «год · жанр» + блок «Оценить?» справа ---
    def _sync_rating(self, album: Album) -> None:
        """Показать оценку или предложение оценить (взаимно исключны)."""
        if album.rating is not None:
            self.lbl_rating.setText(f"Оценка: {album.rating:.1f}")
            self.lbl_rating.setStyleSheet(f"color: {rating_color(album.rating)};")
            self.lbl_rating.show()
            self.rate_side.hide()
        else:
            self.lbl_rating.hide()
            self.rate_side.show()

    # --- Треклист / сетка оценок ------------------------------------------
    def _rebuild_tracks(self, album: Album) -> None:
        """Пересобрать нижний сегмент страницы под состояние альбома.

        Оценён (есть matrix оценок участников) — сетка оценок, как
        на шаге «Оценки» мастера: шапка с именами, оценки в строках
        треков (только чтение), «Средняя оценка» каждого внизу.
        Иначе — обычный треклист.
        """
        while self.tracks_v.count():
            item = self.tracks_v.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        ratings = album.ratings
        has_grid = (
            ratings is not None
            and bool(ratings.rater_names)
            and len(ratings.values) == len(album.tracks)
        )
        rater_names = ratings.rater_names if has_grid else []

        # Шапка: Номер | Трек (+ имена участников у сетки оценок)
        self.tracks_v.addWidget(self._make_track_row(
            index_text="№", title_text="Трек", artists_text="",
            header=True, rater_names=rater_names,
        ))

        tracks = album.tracks
        total = len(tracks)
        for t_index, track in enumerate(tracks):
            self.tracks_v.addWidget(self._make_track_row(
                index_text=f"{t_index + 1:02d}",
                title_text=track.title,
                artists_text=(
                    " · ".join(a.name for a in track.artists) or "—"
                ),
                is_last=(t_index == total - 1),
                values=(
                    ratings.values[t_index] if has_grid else None
                ),
            ))

        if has_grid:
            self.tracks_v.addWidget(self._make_averages_row(ratings))
        self.tracks_v.addStretch(1)

    def _make_track_row(
        self,
        index_text: str,
        title_text: str,
        artists_text: str,
        header: bool = False,
        is_last: bool = False,
        rater_names: list[str] | None = None,
        values: list[float | None] | None = None,
    ) -> QWidget:
        """Строка сегмента: номер, название, исполнители трека.

        header=True — шапка (имена участников вместо исполнителей);
        values — оценки трека по столбцам участников (None — обычная
        строка треклиста без клеток). Всё только для чтения.
        """
        row = QWidget(self.tracks_container)
        row.setObjectName(
            "rateHeadRow" if header else (
                "trackRowLast" if is_last else "trackRow"
            )
        )
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(GRID_HEAD_H if header else TRACK_ROW_HEIGHT)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(12)

        lbl_index = QLabel(index_text, row)
        lbl_index.setObjectName("trackIndex")
        lbl_index.setFixedWidth(TRACK_INDEX_WIDTH)
        lay.addWidget(lbl_index)

        lbl_title = QLabel(title_text, row)
        lbl_title.setObjectName(
            "rateHeadTitle" if header else "trackRowTitle"
        )
        lay.addWidget(lbl_title, 1)

        if not header:
            lbl_artists = QLabel(artists_text, row)
            lbl_artists.setObjectName("trackArtists")
            lbl_artists.setFixedWidth(RATE_ARTISTS_W)
            lay.addWidget(lbl_artists)

        if header:
            for name in (rater_names or []):
                name_lbl = QLabel(name, row)
                name_lbl.setObjectName("rateColName")
                name_lbl.setFixedWidth(RATE_CELL_W)
                name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(name_lbl)
        elif values is not None:
            for value in values:
                value_lbl = QLabel(_fmt_rating(value), row)
                value_lbl.setObjectName("rateAvgValue")
                value_lbl.setFixedSize(RATE_CELL_W, RATE_CELL_H)
                value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if value == SECRET_VALUE:
                    # Секретная 11 подсвечена, как в мастере оценивания
                    value_lbl.setStyleSheet(
                        f"color: {ACCENT}; font-weight: 700;"
                    )
                lay.addWidget(value_lbl)
        return row

    def _make_averages_row(self, ratings: AlbumRatings) -> QWidget:
        """Итоговая строка сетки: средняя оценка каждого участника."""
        holder = QWidget(self.tracks_container)
        holder.setObjectName("trackRowLast")
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setFixedHeight(GRID_HEAD_H)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(12)
        lbl = QLabel("Средняя оценка", holder)
        lbl.setObjectName("rateAvgLabel")
        lay.addWidget(lbl, 1)
        for column in range(len(ratings.rater_names)):
            average = ratings.participant_average(column)
            value_lbl = QLabel(_fmt_rating(average), holder)
            value_lbl.setObjectName("rateAvgValue")
            value_lbl.setFixedWidth(RATE_CELL_W)
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if average is not None:
                value_lbl.setStyleSheet(f"color: {rating_color(average)};")
            lay.addWidget(value_lbl)
        return holder

    # --- Кликабельные исполнители ---
    @staticmethod
    def _artists_html(album: Album) -> str:
        """Исполнители одной строкой, каждое имя — ссылка «artist:<имя>»."""
        if not album.artist_names:
            return "—"
        parts = [
            f'<a href="artist:{quote(name)}" '
            f'style="color: #c9c9d2; text-decoration: none;">'
            f"{escape(name)}</a>"
            for name in album.artist_names
        ]
        return " · ".join(parts)

    def _open_artist_link(self, href: str) -> None:
        """Клик по имени исполнителя на странице альбома."""
        if self._album is None:
            return
        name = unquote(href.removeprefix("artist:"))
        if name:
            self.artist_opened.emit(name)
