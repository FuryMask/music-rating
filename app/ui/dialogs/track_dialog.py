"""Диалоги «Новый трек» и «Новый исполнитель» — внутри приложения.

Как это устроено (по ТЗ):
  • TrackDialogOverlay — полнооконный оверлей поверх мастера: его фон —
    РАЗМЫТЫЙ снимок содержимого окна (grab + QGraphicsBlurEffect), поэтому
    «на фоне появляется блюр изображения»;
  • карточка трека (#dialogCard, скруглённые края) появляется в центре:
    поднимается с низа экрана, при этом её прозрачность растёт 0 % → 100 %;
    к моменту, когда она на своём месте, она уже полностью непрозрачна;
  • внутри: «Название трека:», «Исполнители:» (поиск ПО БАЗЕ с
    автодополнением) и справа «плюсик»; под ними — плитки исполнителей
    (те же ArtistChip, переносятся FlowLayout-ом); исполнители,
    закреплённые за альбомом, выбраны сразу;
  • плюсик открывает такое же по стилю окно «Новый исполнитель»
    (тот же функционал, что и в мастере: имя, жанр, фото). Карточка
    трека при этом съезжает вправо и делит центр экрана с новым окном.
    Подъём и затухание повторяются при каждом открытии и закрытии;
  • Esc закрывает сначала окно исполнителя, потом окно трека
    (обрабатывает мастер, см. create_album._handle_escape).

Ничего системного: это дочерние QWidget, а не QDialog.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    QStringListModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import STARTER_GENRES, ArtistDraft, TrackDraft
from app.store import STORE
from app.ui.widgets.artist_chip import ArtistChip
from app.ui.widgets.combo_box import DarkComboBox, style_completion_popup
from app.ui.widgets.cover_picker import CoverPickerCard
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import SmoothScrollArea
from app.ui.dialogs.exit_confirm_dialog import _make_blurred

TRACK_CARD_SIZE = (430, 400)   # карточка «Новый трек»
ARTIST_CARD_SIZE = (380, 440)  # карточка «Новый исполнитель»
SPLIT_GAP = 28                 # просвет между карточками в сплит-режиме

RISE_MS = 320   # подъём с низа + проявление
MOVE_MS = 300   # съезд карточки трека вправо/обратно
FADE_MS = 200   # растворение окна исполнителя

BLUR_RADIUS = 26  # сила блюра фона



class DialogPlusButton(HoverButton):
    """Плюсик «создать исполнителя» — плюс нарисован линиями."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=8)
        self.setObjectName("dialogPlusButton")
        self.setFixedSize(36, 36)
        self.setToolTip("Создать нового исполнителя")
        self.setIcon(line_icon("plus"))


class TrackDialogOverlay(QWidget):
    """Оверлей с блюр-фоном, карточкой трека и карточкой исполнителя."""

    track_added = Signal(object)  # TrackDraft — подтверждён в мастере
    artist_created = Signal(str)  # имя — база пополнилась (обновить поиск)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("trackOverlay")
        self._bg: QPixmap | None = None
        self._groups: dict[QWidget, QParallelAnimationGroup] = {}
        self._track_artists: list[ArtistDraft] = []
        self._artist_photo_path: str | None = None
        self._artist_open = False

        self.track_card = self._make_track_card()
        self.artist_card = self._make_artist_card()
        self.artist_card.hide()
        self.track_card.hide()

    # ==================================================================
    # Карточка трека
    # ==================================================================
    def _make_track_card(self) -> QWidget:
        card = QWidget(self)
        card.setObjectName("dialogCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedSize(*TRACK_CARD_SIZE)

        self._track_fx = QGraphicsOpacityEffect(card)
        self._track_fx.setOpacity(1.0)
        card.setGraphicsEffect(self._track_fx)

        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(14)

        header = QLabel("Новый трек", card)
        header.setObjectName("dialogTitle")
        v.addWidget(header)

        lbl_title = QLabel("Название трека:", card)
        lbl_title.setObjectName("fieldLabel")
        v.addWidget(lbl_title)

        self.input_track_title = QLineEdit(card)
        self.input_track_title.setPlaceholderText("Название трека")
        v.addWidget(self.input_track_title)

        lbl_artists = QLabel("Исполнители:", card)
        lbl_artists.setObjectName("fieldLabel")
        v.addWidget(lbl_artists)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.input_track_artist = QLineEdit(card)
        self.input_track_artist.setPlaceholderText("Поиск исполнителя")
        search_row.addWidget(self.input_track_artist, 1)
        self.btn_new_artist = DialogPlusButton(card)
        search_row.addWidget(self.btn_new_artist)
        v.addLayout(search_row)

        self.lbl_track_hint = QLabel("", card)
        self.lbl_track_hint.setObjectName("errorHint")
        self.lbl_track_hint.hide()
        v.addWidget(self.lbl_track_hint)

        # Плитки исполнителей трека — те же чипы, с переносом строк
        self.chips_area = SmoothScrollArea(card)
        self.chips_area.setFixedHeight(88)
        self.chips_area.setWidgetResizable(True)
        self.chips_area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self.chips_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chips_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.chips_container = QWidget()
        self.chips_flow = FlowLayout(self.chips_container, spacing=12)
        self.chips_flow.setContentsMargins(6, 6, 6, 6)
        self.chips_hint = QLabel(
            "Пока пусто — исполнители необязательны", self.chips_container
        )
        self.chips_hint.setObjectName("emptyHint")
        self.chips_area.setWidget(self.chips_container)
        v.addWidget(self.chips_area)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_track_cancel = HoverButton("Отменить", card)
        self.btn_track_cancel.setObjectName("ghostButton")
        self.btn_track_add = HoverButton("Добавить", card)
        self.btn_track_add.setObjectName("primaryButton")
        self.btn_track_add.setEnabled(False)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_track_cancel)
        buttons.addWidget(self.btn_track_add)
        v.addLayout(buttons)

        # --- Поведение ---
        self._setup_completer()
        self.input_track_title.textChanged.connect(self._sync_track_add_state)
        self.input_track_title.returnPressed.connect(self._commit_on_enter)
        self.input_track_artist.textChanged.connect(self.lbl_track_hint.hide)
        self.input_track_artist.returnPressed.connect(self._add_existing)
        self.btn_new_artist.clicked.connect(self._open_artist)
        self.btn_track_cancel.clicked.connect(self.close)
        self.btn_track_add.clicked.connect(self._commit_track)
        return card

    def _setup_completer(self) -> None:
        """Автодополнение поиска исполнителей именами из базы."""
        self._completer = QCompleter(STORE.artist_names(), self.input_track_artist)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        style_completion_popup(self._completer)
        self._completer.activated.connect(self._add_existing)
        self.input_track_artist.setCompleter(self._completer)

    def _refresh_completer(self) -> None:
        self._completer.setModel(
            QStringListModel(STORE.artist_names(), self._completer)
        )

    # ==================================================================
    # Карточка «Новый исполнитель»
    # ==================================================================
    def _make_artist_card(self) -> QWidget:
        card = QWidget(self)
        card.setObjectName("dialogCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedSize(*ARTIST_CARD_SIZE)

        self._artist_fx = QGraphicsOpacityEffect(card)
        self._artist_fx.setOpacity(1.0)
        card.setGraphicsEffect(self._artist_fx)

        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(12)

        header = QLabel("Новый исполнитель", card)
        header.setObjectName("dialogTitle")
        v.addWidget(header)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        lbl_name = QLabel("Имя исполнителя:", card)
        lbl_name.setObjectName("inlineLabel")
        name_row.addWidget(lbl_name)
        self.input_artist_name = QLineEdit(card)
        self.input_artist_name.setPlaceholderText("Имя исполнителя")
        name_row.addWidget(self.input_artist_name, 1)
        v.addLayout(name_row)

        genre_row = QHBoxLayout()
        genre_row.setSpacing(8)
        lbl_genre = QLabel("Основной жанр:", card)
        lbl_genre.setObjectName("inlineLabel")
        genre_row.addWidget(lbl_genre)
        self.combo_artist_genre = DarkComboBox(card)
        self.combo_artist_genre.setEditable(True)
        self.combo_artist_genre.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert
        )
        self.combo_artist_genre.addItems(STARTER_GENRES)
        self.combo_artist_genre.setCurrentIndex(-1)
        self.combo_artist_genre.lineEdit().setPlaceholderText("Например, Рок")
        genre_row.addWidget(self.combo_artist_genre, 1)
        v.addLayout(genre_row)

        self.lbl_artist_hint = QLabel("", card)
        self.lbl_artist_hint.setObjectName("errorHint")
        self.lbl_artist_hint.hide()
        v.addWidget(self.lbl_artist_hint)

        # Фото исполнителя (необязательно) — как в мастере
        photo_col = QVBoxLayout()
        photo_col.setSpacing(8)
        self.artist_photo = CoverPickerCard(
            card, dialog_title="Выберите фото исполнителя"
        )
        photo_col.addWidget(self.artist_photo, 0, Qt.AlignmentFlag.AlignHCenter)
        caption = QLabel("Фото (необязательно)", card)
        caption.setObjectName("emptyHint")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        photo_col.addWidget(caption)
        v.addLayout(photo_col)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_artist_cancel = HoverButton("Отменить", card)
        self.btn_artist_cancel.setObjectName("ghostButton")
        self.btn_artist_add = HoverButton("Добавить", card)
        self.btn_artist_add.setObjectName("primaryButton")
        self.btn_artist_add.setEnabled(False)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_artist_cancel)
        buttons.addWidget(self.btn_artist_add)
        v.addLayout(buttons)

        # --- Поведение ---
        self.input_artist_name.textChanged.connect(self._sync_artist_add_state)
        self.input_artist_name.returnPressed.connect(
            lambda: self.btn_artist_add.click()
        )
        self.btn_artist_cancel.clicked.connect(self._cancel_artist)
        self.btn_artist_add.clicked.connect(self._commit_new_artist)
        self.artist_photo.cover_picked.connect(self._on_artist_photo)
        return card

    # ==================================================================
    # Данные трека: поиск / плитки
    # ==================================================================
    def _in_track_artists(self, name: str) -> bool:
        low = name.strip().casefold()
        return any(a.name.casefold() == low for a in self._track_artists)

    def _add_existing(self, name: str | None = None) -> None:
        """Добавить исполнителя ТОЛЬКО если он есть в базе."""
        text = (
            name if name is not None else self.input_track_artist.text()
        ).strip()
        if not text:
            return
        artist = STORE.find_artist(text)
        if artist is None:
            self.lbl_track_hint.setText(
                "Такого исполнителя нет в базе — создайте его через «+»."
            )
            self.lbl_track_hint.show()
            return
        if self._in_track_artists(artist.name):
            self.lbl_track_hint.setText(
                "Этот исполнитель уже добавлен к треку."
            )
            self.lbl_track_hint.show()
            return
        self._track_artists.append(ArtistDraft(
            name=artist.name,
            genre=artist.genre,
            photo_path=artist.photo_path,
            existing=True,
        ))
        self.input_track_artist.clear()
        self.lbl_track_hint.hide()
        self._rebuild_chips()

    def _remove_track_artist(self, artist: ArtistDraft) -> None:
        self._track_artists = [
            a for a in self._track_artists if a is not artist
        ]
        self._rebuild_chips()

    def _rebuild_chips(self) -> None:
        flow = self.chips_flow
        while flow.count():
            item = flow.takeAt(0)
            widget = item.widget()
            # подсказку не удаляем — она переиспользуется
            if widget is not None and widget is not self.chips_hint:
                widget.hide()
                widget.deleteLater()
        if not self._track_artists:
            self.chips_hint.show()
            flow.addWidget(self.chips_hint)
        else:
            self.chips_hint.hide()
            for artist in self._track_artists:
                chip = ArtistChip(artist, self.chips_container)
                chip.removed.connect(self._remove_track_artist)
                flow.addWidget(chip)

    # ==================================================================
    # Состояния кнопок и полей
    # ==================================================================
    def _sync_track_add_state(self, *_args) -> None:
        self.btn_track_add.setEnabled(
            bool(self.input_track_title.text().strip())
        )

    def _commit_on_enter(self) -> None:
        if self.btn_track_add.isEnabled():
            self._commit_track()

    def _sync_artist_add_state(self, *_args) -> None:
        self.btn_artist_add.setEnabled(
            bool(self.input_artist_name.text().strip())
        )

    def _on_artist_photo(self, path: str) -> None:
        self._artist_photo_path = path

    def _reset_artist_fields(self) -> None:
        self.input_artist_name.clear()
        self.combo_artist_genre.setCurrentIndex(-1)
        self.combo_artist_genre.lineEdit().clear()
        self.artist_photo.clear_photo()
        self._artist_photo_path = None
        self.lbl_artist_hint.hide()
        self._sync_artist_add_state()

    def _reset_all(self) -> None:
        """Чистое состояние перед каждым открытием."""
        self._track_artists = []
        self.input_track_title.clear()
        self.input_track_artist.clear()
        self.lbl_track_hint.hide()
        self._sync_track_add_state()
        self._reset_artist_fields()
        self._rebuild_chips()
        self._refresh_completer()

    # ==================================================================
    # Геометрия и анимации
    # ==================================================================
    def _single_track_pos(self) -> QPoint:
        """Позиция карточки трека — по центру оверлея."""
        return QPoint(
            (self.width() - TRACK_CARD_SIZE[0]) // 2,
            (self.height() - TRACK_CARD_SIZE[1]) // 2,
        )

    def _split_positions(self) -> tuple[QPoint, QPoint]:
        """Сплит-режим: трек справа от центра, исполнитель слева."""
        cx = self.width() // 2
        track_x = cx + SPLIT_GAP // 2
        artist_x = max(8, track_x - SPLIT_GAP - ARTIST_CARD_SIZE[0])
        track_y = (self.height() - TRACK_CARD_SIZE[1]) // 2
        artist_y = (self.height() - ARTIST_CARD_SIZE[1]) // 2
        return QPoint(track_x, track_y), QPoint(artist_x, artist_y)

    def _stop_card_anim(self, card: QWidget) -> None:
        old = self._groups.pop(card, None)
        if old is not None:
            old.stop()
            old.deleteLater()

    def _animate_card(self, card: QWidget, fx: QGraphicsOpacityEffect,
                      target: QPoint, fade_to: float, ms: int,
                      on_done=None) -> None:
        """Позиция + прозрачность параллельно; прежние анимации гасятся."""
        self._stop_card_anim(card)

        pos_anim = QPropertyAnimation(card, b"pos", card)
        pos_anim.setDuration(ms)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        pos_anim.setStartValue(card.pos())
        pos_anim.setEndValue(target)

        fade_anim = QPropertyAnimation(fx, b"opacity", card)
        fade_anim.setDuration(ms)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(fx.opacity())
        fade_anim.setEndValue(fade_to)

        group = QParallelAnimationGroup(card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)
        def finish() -> None:
            self._groups.pop(card, None)
            group.deleteLater()
            if on_done is not None:
                on_done()

        group.finished.connect(finish)
        self._groups[card] = group
        group.start()

    def _stop_animations(self) -> None:
        for card in (self.track_card, self.artist_card):
            self._stop_card_anim(card)

    # ==================================================================
    # Открытие / закрытие
    # ==================================================================
    def open(self, preset_artists: list[ArtistDraft] | None = None) -> None:
        """Показать: блюр-фон → карточка трека поднимается из низа.

        preset_artists — исполнители, закреплённые за альбомом: они
        сразу выбраны в треке (можно оставить или убрать крестиком).
        """
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        self._reset_all()
        if preset_artists:
            # Копии: чипы трека независимы от чипов шага «Исполнители»
            self._track_artists = [
                ArtistDraft(
                    name=a.name,
                    genre=a.genre,
                    photo_path=a.photo_path,
                    existing=True,
                )
                for a in preset_artists
            ]
            self._rebuild_chips()
        self._artist_open = False
        self.artist_card.hide()

        self.show()
        self.raise_()

        target = self._single_track_pos()
        self._track_fx.setOpacity(0.0)
        self.track_card.move(target.x(), self.height() + 8)
        self.track_card.show()
        self._animate_card(self.track_card, self._track_fx, target, 1.0, RISE_MS)
        self.input_track_title.setFocus()

    def close(self) -> None:
        """Закрыть целиком (сброс полей — сделает следующий open)."""
        self._stop_animations()
        self._artist_open = False
        self.artist_card.hide()
        self.track_card.hide()
        self.hide()
        self._reset_all()

    def handle_escape(self) -> None:
        """Esc: сначала окно исполнителя, затем — окно трека."""
        if self.artist_card.isVisible():
            self._cancel_artist()
            return
        self.close()

    # ==================================================================
    # Сплит-режим: окно исполнителя рядом
    # ==================================================================
    def _open_artist(self) -> None:
        if self._artist_open:
            self.input_artist_name.setFocus()
            return
        self._artist_open = True
        track_target, artist_target = self._split_positions()
        # Карточка трека съезжает вправо и делит центр с новым окном
        self._animate_card(
            self.track_card, self._track_fx, track_target, 1.0, MOVE_MS
        )
        if not self.artist_card.isVisible():
            self._artist_fx.setOpacity(0.0)
            self.artist_card.move(artist_target.x(), self.height() + 8)
            self.artist_card.show()
        self.artist_card.raise_()
        self._animate_card(
            self.artist_card, self._artist_fx, artist_target, 1.0, RISE_MS
        )
        self.input_artist_name.setFocus()

    def _cancel_artist(self) -> None:
        self._reset_artist_fields()
        self._close_artist()

    def _close_artist(self) -> None:
        if not self._artist_open:
            return
        self._artist_open = False
        _, artist_target = self._split_positions()
        self._animate_card(
            self.artist_card, self._artist_fx,
            artist_target + QPoint(0, 48), 0.0, FADE_MS,
            on_done=self.artist_card.hide,
        )
        # Карточка трека возвращается в центр
        self._animate_card(
            self.track_card, self._track_fx,
            self._single_track_pos(), 1.0, MOVE_MS,
        )

    def _commit_new_artist(self) -> None:
        name = self.input_artist_name.text().strip()
        if not name:
            return
        if self._in_track_artists(name):
            self.lbl_artist_hint.setText(
                "Этот исполнитель уже добавлен к треку."
            )
            self.lbl_artist_hint.show()
            return
        genre = self.combo_artist_genre.currentText().strip()
        photo = self._artist_photo_path
        # Новый исполнитель сразу попадает в базу — как в мастере
        STORE.add_artist(name, genre=genre, photo_path=photo)
        self.artist_created.emit(name)
        self._track_artists.append(ArtistDraft(
            name=name, genre=genre, photo_path=photo, existing=False,
        ))
        self._rebuild_chips()
        self._reset_artist_fields()
        self._close_artist()

    # ==================================================================
    # Подтверждение трека
    # ==================================================================
    def _commit_track(self) -> None:
        title = self.input_track_title.text().strip()
        if not title:
            return
        self.track_added.emit(TrackDraft(
            title=title, artists=list(self._track_artists),
        ))
        self.close()

    # ==================================================================
    # Отрисовка и геометрия
    # ==================================================================
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._bg is not None:
            painter.drawPixmap(self.rect(), self._bg)
        else:
            painter.fillRect(self.rect(), QColor("#141414"))
        # лёгкое затемнение — карточки читаются контрастнее
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.isVisible():
            return
        # Окно изменили размер — мгновенно ставим карточки на места
        self._stop_animations()
        if self._artist_open:
            track_target, artist_target = self._split_positions()
            self.track_card.move(track_target)
            self.artist_card.move(artist_target)
            self._track_fx.setOpacity(1.0)
            self._artist_fx.setOpacity(1.0)
        elif self.track_card.isVisible():
            self.artist_card.hide()
            self.track_card.move(self._single_track_pos())
            self._track_fx.setOpacity(1.0)

    def mousePressEvent(self, event) -> None:
        # Клик по фону ничего не делает (закрытие — по кнопкам/Esc)
        event.accept()
