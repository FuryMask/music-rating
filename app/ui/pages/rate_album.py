"""Мастер оценивания альбома — полнооконный оверлей в 3 этапа.

Открывается со страницы альбома (кнопка «Оценить?») или из окна
«Вы успешно создали альбом, хотите оценить его сейчас?» после
создания. Шаги:
  1. УЧАСТНИКИ — выбор оценивающих (STORE.raters — это
     ЗАРЕГИСТРИРОВАННЫЕ АККАНТЫ, см. dialogs/profile_dialog.py;
     плитки пересобираются при каждом открытии). Хотя бы один —
     он получит свой столбец на шаге 2. Плитки при выборе плавно
     увеличиваются (RaterChip).
  2. ОЦЕНИВАНИЕ — треклист альбома (как на шаге 3 создания) со
     столбцом на каждого участника: в клетке оценка 0–11 с шагом 0.1
     (запятая и точка равнозначны; выше 11 ввести НЕВОЗМОЖНО — ввод
     отбрасывает RateCellValidator). Оценка 11 — СЕКРЕТНАЯ: у каждого
     участника максимум одна за альбом (клетка подсвечивается,
     вторая «11» в столбце не принимается). Внизу — строка «Средняя
     оценка»: средняя альбома каждого участника (по заполненным
     клеткам, пересчитывается на лету; максимум 10).
  3. ИТОГИ — обложка, название, «год · жанр» и средняя оценка
     альбома (как на странице альбома — под годом и жанром), ниже —
     статистика: средняя и любимый трек каждого участника (при
     равенстве — самый последний в треклисте) и любимый трек всех
     (наивысшая средняя, при равенстве — самый последний). В строках
     статистики «любимый трек» выравнивается по невидимой вертикали.

Оценки сохраняются кнопкой «Готово» (STORE.rate_album): средняя
альбома попадает в карточки и на страницу альбома. «Отмена»/Esc при
заполненных клетках открывает подтверждение выхода (см.
dialogs/exit_confirm_dialog.py) — «Выйти» закрывает мастер.
"""

from PySide6.QtCore import (
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QPainter,
    QPixmap,
    QKeySequence,
    QShortcut,
    QValidator,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import Album, AlbumRatings
from app.store import STORE
from app.theme import BG_MAIN, rating_color, themed_color
from app.ui.dialogs.exit_confirm_dialog import ExitConfirmOverlay
from app.ui.dialogs.playback_choice_dialog import PlaybackChoiceDialog
from app.ui.pages.listen_and_rate import ListenAndRatePage
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import HOVER_MS, HoverButton
from app.ui.widgets.motion import SmoothScrollArea
from app.ui.widgets.track_row import TRACK_INDEX_WIDTH, TRACK_ROW_HEIGHT

COVER_RADIUS = 12
SUMMARY_COVER = 180              # обложка на этапе «Итоги»
RATE_CELL_W = 56                 # ширина клетки оценки
RATE_CELL_H = 30                 # высота клетки оценки
RATE_ARTISTS_W = 150             # ширина колонки исполнителей трека
RATE_STEP_NAMES = ["Участники", "Оценки", "Итоги"]
SECRET_VALUE = 11.0              # «секретная» оценка
RATE_MAX = 11.0                  # максимум клетки (11 — секретная)
RATE_TITLE_MAX = 480             # перенос длинного названия на «Итогах»
STATS_COLUMN_GAP = 14            # просвет до колонки «любимый трек»
STATS_LEFT_PAD = 6               # запас ширины левой колонки статистики


class RateCellValidator(QValidator):
    """Клетка оценки: разрешает ТОЛЬКО число 0–11 с одной десятой.

    Шаг 0.1 (не больше одного знака после точки/запятой), значения
    выше 11 ввести невозможно — лишний символ отбрасывается ещё на
    вводе (Task 19, п. 5). Запятая и точка равнозначны.
    """

    def validate(self, text: str, pos: int):
        cleaned = text.strip().replace(",", ".")
        if not cleaned:
            return (QValidator.State.Acceptable, text, pos)
        head, dot, tail = cleaned.partition(".")
        if (
            not head.isdigit()
            or (dot and (len(tail) > 1 or (bool(tail) and not tail.isdigit())))
        ):
            return (QValidator.State.Invalid, text, pos)
        try:
            value = float(cleaned)
        except ValueError:
            return (QValidator.State.Invalid, text, pos)
        if value > RATE_MAX:
            return (QValidator.State.Invalid, text, pos)
        return (QValidator.State.Acceptable, text, pos)


class RaterChip(HoverButton):
    """Плитка участника: масштаб отрисовки отражает выбор и наведение."""

    CHIP_HEIGHT = 40

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent, outline_radius=13)
        self.setCheckable(True)
        self.setMinimumHeight(self.CHIP_HEIGHT)
        self.toggled.connect(lambda _checked: self._animate_scale(HOVER_MS))

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(QSize(0, self.CHIP_HEIGHT))

    def _scale_active(self) -> bool:
        return super()._scale_active() or self.isChecked()


def _fmt(value: float | None) -> str:
    """Оценка строкой: 8.4 / «—» (пусто)."""
    return f"{value:.1f}" if value is not None else "—"


def _parse_cell(text: str) -> float | None:
    """Текст клетки → оценка (None — пусто), ValueError — неверно.

    Запятая и точка равнозначны: пользователь может ввести и «8,5».
    """
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        return None
    return float(cleaned)  # может бросить ValueError


class RateAlbumOverlay(QWidget):
    """Полнооконный интерфейс оценивания альбома (3 этапа)."""

    album_rated = Signal(object)  # Album — «Готово» сохранил оценки

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("rateOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._album: Album | None = None
        self._selected: set[str] = set()      # отмеченные участники
        self._raters: list[str] = []          # столбцы этапа 2
        self._values: list[list[float | None]] = []
        self._cells: list[list[QLineEdit]] = []
        self._avg_labels: list[QLabel] = []
        self._exit_overlay: ExitConfirmOverlay | None = None
        self._player: ListenAndRatePage | None = None
        self._playback_choice: PlaybackChoiceDialog | None = None
        self._player_cells: list[QLineEdit] = []
        self._player_track = -1

        self._surface = QStackedWidget(self)
        self._form = QWidget(self._surface)
        self._surface.addWidget(self._form)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._surface)
        root = QVBoxLayout(self._form)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(20)

        # --- Шапка ---
        header = QHBoxLayout()
        header_col = QVBoxLayout()
        self.lbl_title = QLabel("Оценивание альбома", self)
        self.lbl_title.setObjectName("overlayTitle")
        self.lbl_step = QLabel(self._step_text(0), self)
        self.lbl_step.setObjectName("stepHint")
        header_col.addWidget(self.lbl_title)
        header_col.addWidget(self.lbl_step)
        header.addLayout(header_col)
        header.addStretch(1)
        self.btn_listen = HoverButton(parent=self)
        self.btn_listen.setObjectName("listenControl")
        self.btn_listen.setFixedSize(42, 42)
        self.btn_listen.setIcon(line_icon("note"))
        self.btn_listen.setToolTip("Оценивать с прослушиванием")
        self.btn_listen.setAccessibleName(self.btn_listen.toolTip())
        self.btn_listen.clicked.connect(self._choose_playback)
        self.btn_listen.hide()
        header.addWidget(self.btn_listen, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        # --- Этапы ---
        self.steps = QStackedWidget(self)
        self.steps.addWidget(self._make_raters_step())   # 0: Участники
        self.steps.addWidget(self._make_rating_step())   # 1: Оценки
        self.steps.addWidget(self._make_summary_step())  # 2: Итоги
        root.addWidget(self.steps, 1)

        # --- Подвал ---
        footer = QHBoxLayout()
        self.btn_cancel = HoverButton("Отмена", self)
        self.btn_cancel.setObjectName("ghostButton")
        footer.addWidget(self.btn_cancel)
        footer.addStretch(1)
        self.btn_back = HoverButton("← Назад", self)
        self.btn_back.setObjectName("ghostButton")
        self.btn_back.hide()
        footer.addWidget(self.btn_back)
        self.btn_next = HoverButton("Далее →", self)
        self.btn_next.setObjectName("primaryButton")
        footer.addWidget(self.btn_next)
        root.addLayout(footer)

        # --- Сигналы ---
        self.btn_cancel.clicked.connect(self._request_exit)
        self.btn_back.clicked.connect(
            lambda: self.go_to_step(self.steps.currentIndex() - 1)
        )
        self.btn_next.clicked.connect(self._on_next_clicked)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self._handle_escape
        )

    # ================= Этап 1: участники =================
    def _make_raters_step(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(14)

        title = QLabel("Кто оценивает?", page)
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        # Подсказка зависит от того, есть ли аккаунты-участники
        # (наполняется в _rebuild_rater_chips)
        self.lbl_raters_hint = QLabel("", page)
        self.lbl_raters_hint.setObjectName("emptyHint")
        self.lbl_raters_hint.setWordWrap(True)
        v.addWidget(self.lbl_raters_hint)

        # Плитки участников — переключатели (клик — выбран/нет).
        # Margins раскладки дают запас под рост выбранной плитки —
        # иначе выросшая плитка обрезается краями держателя.
        chips_holder = QWidget(page)
        self.raters_flow = FlowLayout(chips_holder, spacing=10)
        self.raters_flow.setContentsMargins(10, 10, 10, 10)
        v.addWidget(chips_holder)

        self.rater_buttons: dict[str, RaterChip] = {}
        self._rebuild_rater_chips()

        v.addStretch(1)
        return page

    def _rebuild_rater_chips(self) -> None:
        """Пересобрать плитки участников по ТЕКУЩЕМУ списку аккаунтов.

        Список участников — зарегистрированные аккаунты: пользователь
        мог создать новые (или удалить чей-то аккаунт) с прошлого
        открытия мастера — плитки всегда отражают актуальный состав
        (Task 20).
        """
        # Чистим прошлую сборку
        while self.raters_flow.count():
            item = self.raters_flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.rater_buttons = {}
        holder = self.raters_flow.parentWidget()
        for name in STORE.raters:
            btn = RaterChip(name, holder)
            btn.setObjectName("raterChip")
            btn.toggled.connect(
                lambda checked, n=name: self._on_rater_toggled(n, checked)
            )
            self.raters_flow.addWidget(btn)
            self.rater_buttons[name] = btn
        if self.rater_buttons:
            self.lbl_raters_hint.setText(
                "Выберите участников — каждый получит свой столбец оценок."
            )
        else:
            self.lbl_raters_hint.setText(
                "Участники — это аккаунты. Создайте их через кнопку "
                "профиля (левее «+») — имена появятся здесь."
            )

    def _on_rater_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self._selected.add(name)
        else:
            self._selected.discard(name)
        self._update_next_state()

    # ================= Этап 2: оценивание =================
    def _make_rating_step(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Треклист", page)
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)

        # Сегмент как треклист создания: тянется на всё свободное
        # место, при переполнении — прокрутка
        self.grid_frame = QFrame(page)
        self.grid_frame.setObjectName("trackListFrame")
        self.grid_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        frame_v = QVBoxLayout(self.grid_frame)
        frame_v.setContentsMargins(10, 6, 10, 6)
        frame_v.setSpacing(0)
        self.grid_area = SmoothScrollArea(self.grid_frame)
        self.grid_area.setWidgetResizable(True)
        self.grid_area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self.grid_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.grid_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.grid_container = QWidget()
        self.grid_v = QVBoxLayout(self.grid_container)
        self.grid_v.setContentsMargins(0, 0, 0, 0)
        self.grid_v.setSpacing(0)
        self.grid_area.setWidget(self.grid_container)
        frame_v.addWidget(self.grid_area)
        v.addWidget(self.grid_frame, 1)

        # Строка состояния: подсказка про секретную оценку / пустые клетки
        self.lbl_rate_hint = QLabel("", page)
        self.lbl_rate_hint.setObjectName("rateHint")
        self.lbl_rate_hint.hide()
        v.addWidget(self.lbl_rate_hint)
        return page

    # --- Сборка сетки оценок (каждый вход на этап 2) --------------------
    def _build_grid(self) -> None:
        # Состав участников не менялся с прошлой сборки — значения
        # сохраняем (вернулись «Назад» поправить клетки и вернулись)
        if set(self._raters) != self._selected:
            self._raters = [
                name for name in STORE.raters if name in self._selected
            ]
            self._values = [
                [None] * len(self._raters)
                for _ in range(len(self._album.tracks))
            ]

        # Чистим прошлую сборку
        while self.grid_v.count():
            item = self.grid_v.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        # Шапка: Номер | Трек | Исполнители | по клетке на участника
        head_row, _ = self._make_grid_row(
            index_label="№",
            title_text="Трек",
            artists_text="",
            header=True,
        )
        self.grid_v.addWidget(head_row)

        tracks = self._album.tracks
        self._cells = []
        total = len(tracks)
        for t_index, track in enumerate(tracks):
            row, cells = self._make_grid_row(
                index_label=f"{t_index + 1:02d}",
                title_text=track.title,
                artists_text=" · ".join(a.name for a in track.artists) or "—",
                is_last=(t_index == total - 1),
                row_index=t_index,
            )
            # Клетки РЕГИСТРИРУЮТСЯ до setText: setText запускает
            # _on_cell_changed, и без регистрации он падал бы с
            # IndexError (клетки ещё «не существуют» для обработчика).
            self._cells.append(cells)
            # Значения сохранены при возврате «Назад» — показываем их
            # в клетках (setText безопасно перепроверит те же значения)
            for c_index, cell in enumerate(cells):
                value = self._values[t_index][c_index]
                if value is not None:
                    cell.setText(_fmt(value))
            self.grid_v.addWidget(row)

        # Итоговая строка: средняя оценка каждого участника
        averages_holder = QWidget(self.grid_container)
        averages_holder.setObjectName("trackRowLast")
        averages_holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        averages_holder.setFixedHeight(40)
        averages_row = QHBoxLayout(averages_holder)
        averages_row.setContentsMargins(4, 0, 4, 0)
        averages_row.setSpacing(12)
        lbl = QLabel("Средняя оценка", averages_holder)
        lbl.setObjectName("rateAvgLabel")
        averages_row.addWidget(lbl, 1)
        self._avg_labels = []
        for _ in range(len(self._raters)):
            value_lbl = QLabel("—", averages_holder)
            value_lbl.setObjectName("rateAvgValue")
            value_lbl.setFixedWidth(RATE_CELL_W)
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            averages_row.addWidget(value_lbl)
            self._avg_labels.append(value_lbl)
        self.grid_v.addWidget(averages_holder)
        self.grid_v.addStretch(1)

        self._refresh_averages()
        self._update_next_state()

    def _make_grid_row(
        self,
        index_label: str,
        title_text: str,
        artists_text: str,
        header: bool = False,
        is_last: bool = False,
        row_index: int = 0,
    ) -> tuple[QWidget, list[QLineEdit]]:
        """Строка сетки: номер, название, исполнители, клетки оценок.

        Шапка (header=True) — те же колонки с именами участников.
        Клетки оценки есть только в строках треков; возвращаем строку
        и список клеток (пустой для шапки).
        """
        row = QWidget(self.grid_container)
        row.setObjectName(
            "rateHeadRow" if header else (
                "trackRowLast" if is_last else "trackRow"
            )
        )
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(40 if header else TRACK_ROW_HEIGHT)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(12)

        lbl_index = QLabel(index_label, row)
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

        cells: list[QLineEdit] = []
        for c_index, name in enumerate(self._raters):
            if header:
                cell_label = QLabel(name, row)
                cell_label.setObjectName("rateColName")
                cell_label.setFixedWidth(RATE_CELL_W)
                cell_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(cell_label)
            else:
                cell = QLineEdit(row)
                cell.setObjectName("ratingCell")
                cell.setFixedSize(RATE_CELL_W, RATE_CELL_H)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setPlaceholderText("—")
                # Валидатор отбрасывает ввод выше 11 и лишние десятые
                # (ввести оценку больше 11 НЕВОЗМОЖНО — Task 19, п. 5)
                cell.setValidator(RateCellValidator(cell))
                # Значение по умолчанию в лямбде фиксирует индексы
                # строки/столбца на момент сборки
                cell.textChanged.connect(
                    lambda _text, r=row_index, c=c_index:
                    self._on_cell_changed(r, c)
                )
                lay.addWidget(cell)
                cells.append(cell)
        return row, cells

    def _on_cell_changed(self, row: int, column: int) -> None:
        """Клетка изменена: парсим значение, следим за секретной 11."""
        if (
            row >= len(self._cells)
            or column >= len(self._cells[row])
        ):
            return  # сетка ещё собирается — клеток нет (страховка)
        cell = self._cells[row][column]
        text = cell.text()
        state = ""
        try:
            value = _parse_cell(text)
        except ValueError:
            # Промежуточный ввод вида «8,» — нейтрально пусто; мусор
            # вроде букв validator не пропускает, но перестрахуемся
            value = None
            if text.strip().rstrip(".,"):
                state = "bad"

        if value is not None and not (0.0 <= value <= 11.0):
            value = None
            state = "bad"
        if value is not None:
            if value == SECRET_VALUE:
                # Секретная оценка: в столбце она должна быть одна
                others_have_secret = any(
                    self._values[r][column] == SECRET_VALUE
                    for r in range(len(self._values))
                    if r != row
                )
                if others_have_secret:
                    value = None
                    state = "bad"
                    self._show_rate_hint(
                        f"{self._raters[column]} выставил более одного "
                        f"раза оценку 11"
                    )
                else:
                    state = "secret"
            elif state == "":
                self._maybe_hide_rate_hint()

        self._values[row][column] = value
        if value is None and state == "":
            self._maybe_hide_rate_hint()
        self._set_cell_state(cell, state)
        if row == self._player_track and column < len(self._player_cells):
            player_cell = self._player_cells[column]
            self._set_cell_state(player_cell, state)
            if self._player is not None:
                self._player.set_rating_error(any(
                    field.property("state") == "bad" for field in self._player_cells
                ))
        self._refresh_averages()
        self._update_next_state()

    def _set_cell_state(self, cell: QLineEdit, state: str) -> None:
        cell.setProperty("state", state)
        style = cell.style()
        style.unpolish(cell)
        style.polish(cell)

    def _show_rate_hint(self, text: str) -> None:
        self.lbl_rate_hint.setText(text)
        self.lbl_rate_hint.show()

    def _maybe_hide_rate_hint(self) -> None:
        """Подсказка не нужна, если секретных нарушений больше нет."""
        for column in range(len(self._raters)):
            secrets = sum(
                1
                for row in self._values
                if row[column] == SECRET_VALUE
            )
            if secrets > 1:
                return
        self.lbl_rate_hint.hide()

    def _refresh_averages(self) -> None:
        """Средняя оценка альбома каждого участника (нижняя строка)."""
        ratings = AlbumRatings(rater_names=self._raters, values=self._values)
        for column, label in enumerate(self._avg_labels):
            average = ratings.participant_average(column)
            label.setText(_fmt(average))
            label.setStyleSheet(
                f"color: {rating_color(average)};"
                if average is not None
                else ""
            )

    # ================= Этап 3: итоги =================
    def _make_summary_step(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = SmoothScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer.addWidget(scroll)

        self.summary_page = QWidget(scroll)
        scroll.setWidget(self.summary_page)
        v = QVBoxLayout(self.summary_page)
        v.setContentsMargins(12, 8, 12, 12)
        v.setSpacing(16)

        # Обложка + текстовый блок (как на странице альбома)
        info = QHBoxLayout()
        info.setSpacing(28)
        self.summary_cover = CoverView(self.summary_page, radius=COVER_RADIUS)
        self.summary_cover.setFixedSize(SUMMARY_COVER, SUMMARY_COVER)
        info.addWidget(self.summary_cover, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(7)
        self.lbl_summary_title = QLabel(self.summary_page)
        self.lbl_summary_title.setObjectName("detailTitle")
        self.lbl_summary_title.setWordWrap(True)
        self.lbl_summary_title.setMaximumWidth(RATE_TITLE_MAX)
        text_col.addWidget(self.lbl_summary_title)
        self.lbl_summary_meta = QLabel(self.summary_page)
        self.lbl_summary_meta.setObjectName("detailMeta")
        text_col.addWidget(self.lbl_summary_meta)
        # Средняя оценка — ПОД годом и жанром (как на странице альбома)
        self.lbl_summary_rating = QLabel(self.summary_page)
        self.lbl_summary_rating.setObjectName("detailRating")
        text_col.addWidget(self.lbl_summary_rating)
        text_col.addStretch(1)
        info.addLayout(text_col)
        info.addStretch(1)
        v.addLayout(info)

        # --- Статистика ---
        stats_title = QLabel("Статистика", self.summary_page)
        stats_title.setObjectName("sectionTitle")
        v.addWidget(stats_title)

        self.stats_box = QVBoxLayout()
        self.stats_box.setSpacing(8)
        v.addLayout(self.stats_box)
        v.addStretch(1)
        return page

    def _fill_summary(self) -> None:
        """Итоги: шапка альбома + средние/любимые треки участников."""
        album = self._album
        path = STORE.resolve(album.cover_path)
        pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        if not pixmap.isNull():
            self.summary_cover.set_photo(pixmap)
        else:
            self.summary_cover.set_placeholder(
                album.cover_letter, album.cover_color
            )
        self.lbl_summary_title.setText(album.title)
        meta = album.meta_text or "—"
        self.lbl_summary_meta.setText(meta)

        ratings = AlbumRatings(rater_names=self._raters, values=self._values)
        average = ratings.album_average()
        self.lbl_summary_rating.setText(
            f"Оценка альбома: {_fmt(average)}"
        )
        self.lbl_summary_rating.setStyleSheet(
            f"color: {rating_color(average)}; font-weight: 700;"
        )

        # Очистить прошлую статистику
        while self.stats_box.count():
            item = self.stats_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        # «Любимый трек» должен начинаться по невидимой вертикали
        # (Task 19, п. 8): строка = [имя — оценка | любимый трек],
        # ширина левой колонки — общая для всех строк (по самой
        # длинной), поэтому правые части начинаются на одной линии.
        tracks = album.tracks
        left_labels: list[QLabel] = []
        for column, name in enumerate(self._raters):
            average = ratings.participant_average(column)
            favorite = ratings.participant_favorite(column)
            left_text = f"{name} — {_fmt(average)}"
            if favorite is not None:
                right_text = f"любимый трек: «{tracks[favorite].title}»"
            else:
                right_text = "любимый трек: —"

            row = QWidget(self.summary_page)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(STATS_COLUMN_GAP)
            left_lbl = QLabel(left_text, row)
            left_lbl.setObjectName("statsRow")
            right_lbl = QLabel(right_text, row)
            right_lbl.setObjectName("statsRow")
            right_lbl.setWordWrap(True)
            row_lay.addWidget(left_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            row_lay.addWidget(right_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
            self.stats_box.addWidget(row)
            left_labels.append(left_lbl)

        # Общая ширина левой колонки = самая длинная «имя — оценка»
        left_width = 0
        for lbl in left_labels:
            lbl.ensurePolished()  # применить QSS-шрифт до замера
            left_width = max(
                left_width,
                lbl.fontMetrics().horizontalAdvance(lbl.text()),
            )
        for lbl in left_labels:
            lbl.setFixedWidth(left_width + STATS_LEFT_PAD)

        overall = ratings.overall_favorite()
        if overall is not None:
            index, best_average = overall
            highlight = QLabel(
                f"Любимый трек всех: «{tracks[index].title}» "
                f"(средняя {_fmt(best_average)})",
                self.summary_page,
            )
            highlight.setObjectName("statsHighlight")
            highlight.setWordWrap(True)
            self.stats_box.addWidget(highlight)

    # ================= Поведение =================
    def _step_text(self, index: int) -> str:
        return f"Шаг {index + 1} из {len(RATE_STEP_NAMES)} · {RATE_STEP_NAMES[index]}"

    def go_to_step(self, index: int) -> None:
        self._close_player()
        index = max(0, min(index, self.steps.count() - 1))
        if index == 1:
            self._build_grid()
        if index == 2:
            self._fill_summary()
        self.steps.setCurrentIndex(index)
        self.lbl_step.setText(self._step_text(index))
        self.btn_back.setVisible(index > 0)
        self.btn_listen.setVisible(index == 1
                                   and bool(self._album and self._album.tracks))
        last = index == self.steps.count() - 1
        self.btn_next.setText("Готово" if last else "Далее →")
        self._update_next_state()

    def _choose_playback(self) -> None:
        if self._playback_choice is None:
            self._playback_choice = PlaybackChoiceDialog(self)
            self._playback_choice.selected.connect(self._open_player)
        self._playback_choice.open()

    def _open_player(self, provider: str = "yandex") -> None:
        if self.steps.currentIndex() != 1 or not self._album or not self._album.tracks:
            return
        if self._player is None:
            self._player = ListenAndRatePage(self._surface)
            self._surface.addWidget(self._player)
            self._player.closed.connect(self._close_player)
            self._player.completed.connect(self._player_completed)
            self._player.track_changed.connect(self._build_player_cells)
        self._surface.setCurrentWidget(self._player)
        self._player.setFocus()
        self._player.start(self._album, provider)

    def _build_player_cells(self, track: int) -> None:
        self._player_track = track
        self._player_cells.clear()
        while self._player.rating_layout.count():
            item = self._player.rating_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for column, name in enumerate(self._raters):
            holder = QWidget(self._player.rating_holder)
            layout = QHBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            label = QLabel(name, holder)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setObjectName("rateColName")
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            cell = QLineEdit(holder)
            cell.setObjectName("ratingCell")
            cell.setAccessibleName(f"Оценка: {name}")
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setFixedSize(RATE_CELL_W, RATE_CELL_H)
            cell.setPlaceholderText("—")
            cell.setValidator(RateCellValidator(cell))
            original = self._cells[track][column]
            cell.setText(original.text())
            self._set_cell_state(cell, original.property("state") or "")
            cell.textChanged.connect(original.setText)
            layout.addWidget(cell)
            self._player.rating_layout.addWidget(holder)
            self._player_cells.append(cell)
        self._player.set_rating_error(any(
            field.property("state") == "bad" for field in self._player_cells
        ))

    def _close_player(self) -> None:
        if self._playback_choice is not None and self._playback_choice.isVisible():
            self._playback_choice.reject()
        if self._player is not None and self._surface.currentWidget() is self._player:
            self._player.stop()
            self._surface.setCurrentWidget(self._form)
            self._player.restore_windowed()
            self._player_cells.clear()
            self._player_track = -1
            if self.isVisible() and self.btn_listen.isVisible():
                self.btn_listen.setFocus()

    def _player_completed(self) -> None:
        self._close_player()
        if self.btn_next.isEnabled():
            self.go_to_step(2)

    def _on_next_clicked(self) -> None:
        index = self.steps.currentIndex()
        if index == self.steps.count() - 1:
            self._finish()
        else:
            self.go_to_step(index + 1)

    def _finish(self) -> None:
        """«Готово»: оценки в базу, средняя — альбому, окно закрыто."""
        STORE.rate_album(self._album, self._raters, self._values)
        album = self._album
        self.hide()
        self.album_rated.emit(album)

    def _update_next_state(self) -> None:
        index = self.steps.currentIndex()
        if index == 0:
            ready = bool(self._selected)
        elif index == 1:
            ratings = AlbumRatings(
                rater_names=self._raters, values=self._values
            )
            no_bad = not any(
                cell.property("state") == "bad"
                for row_cells in self._cells
                for cell in row_cells
            )
            ready = ratings.filled_count() > 0 and no_bad
        else:
            ready = True
        self.btn_next.setEnabled(ready)

    # --- Выход ------------------------------------------------------------
    def _request_exit(self) -> None:
        if not self.isVisible():
            return
        ratings = AlbumRatings(rater_names=self._raters, values=self._values)
        if ratings.filled_count() > 0 or self._selected:
            if self._exit_overlay is None:
                self._exit_overlay = ExitConfirmOverlay(
                    self,
                    title="Выйти из оценивания?",
                    body="Введённые оценки не сохранятся.",
                    stay_text="Продолжить оценивание",
                )
                # «Выйти» ДОЛЖЕН закрывать мастер (Task 19, п. 11):
                # сигнал приходит от окна подтверждения
                self._exit_overlay.confirmed.connect(self.hide)
            self._exit_overlay.open()
        else:
            self.hide()

    def _handle_escape(self) -> None:
        if not self.isVisible():
            return
        if self._exit_overlay is not None and self._exit_overlay.isVisible():
            self._exit_overlay.close_overlay()
            return
        if self._surface.currentWidget() is self._player:
            if self.window().isFullScreen():
                self._player.restore_windowed()
            else:
                self._close_player()
            return
        self._request_exit()

    # ================= Открытие / закрытие =================
    def open_for(self, album: Album) -> None:
        """Открыть мастер для альбома (чистое состояние)."""
        self._album = album
        self._selected = set()
        self._raters = []
        self._values = []
        self._cells = []
        # Участники — актуальные аккаунты: могли появиться/удалиться
        # с прошлого открытия
        self._rebuild_rater_chips()
        self.lbl_rate_hint.hide()
        if self._exit_overlay is not None and self._exit_overlay.isVisible():
            self._exit_overlay.close_overlay()

        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.go_to_step(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._exit_overlay is not None and self._exit_overlay.isVisible():
            self._exit_overlay.setGeometry(self.rect())

    def hideEvent(self, event) -> None:
        if self.isHidden() and not event.spontaneous():
            self._close_player()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        # Полнооконный оверлей: фон — цвет главного окна
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), themed_color(BG_MAIN))
