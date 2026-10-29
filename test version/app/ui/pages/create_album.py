"""Мастер создания альбома — полнооконный оверлей.

Открывается поверх ВСЕГО окна (и над полосой, и над сайдбаром).
Шаги (пользователь описывает их порциями):
  1. Альбом — основная информация + выбор обложки
  2. Исполнители — один или несколько: уже существующие в базе либо
     новые (имя обязательно; жанр и фото — необязательно)
  3. Треклист — треки через внутриприложный диалог (см.
     app/ui/dialogs/track_dialog.py): кнопка «Добавить трек» открывает
     окно с блюр-фоном и подъёмом из низа с проявлением; внутри —
     название, поиск исполнителей по базе и «плюсик», открывающий
     рядом окно создания нового исполнителя (карточка трека при этом
     съезжает вправо). Сегмент списка тянется на всё свободное место
     окна: видно столько строк, сколько помещается, остальные —
     при прокрутке вниз.

После шага 3 кнопка «Создать» (активна, когда добавлен хотя бы один
трек) сохраняет альбом в базу и закрывает мастер.

Выход («Отмена» или Esc) при введённых данных открывает подтверждение
(см. dialogs/exit_confirm_dialog.py): «Выйти из создания альбома?».
Если ничего не введено — мастер закрывается сразу.

Предупреждение о возможном дубле (ручное создание): если название
альбома (и хотя бы один исполнитель — когда они уже выбраны)
совпадают с существующим, на первом шаге снизу по центру появляется
жёлтый текст «Внимание! Возможно такой альбом уже существует…»,
поле «Название» и плитки выбранных исполнителей получают жёлтую
рамку (без восклицательных знаков). Текст лежит в держателе
фиксированной высоты, который занимает ВСЁ свободное место между
«Отменой» и кнопками справа: появление/скрытие не сдвигает кнопки,
а сам текст не обрезается по нижней границе держателя.

Кнопка «← Назад» возвращает на ПРЕДЫДУЩИЙ шаг (с 3-го — на 2-й,
со 2-го — на 1-й), а не на первый.

Автозаполнение с Deezer/Spotify (apply_auto_fill): поля помечаются
цветными восклицательными знаками справа и цветными рамками — жёлтый
«вероятно верно» (название/год/жанр, плитки исполнителей, названия
треков), красный «не заполняется автоматически» (регион). После
окна-предупреждения открывается окно-совет об этих пометках (см.
dialogs/autofill_tip_dialog.py). Метка снятся, как только
пользователь сам меняет значение поля: подсвечено только то,
что пришло из источника и не тронуто руками.

Шаг 1:
  ЛЕВАЯ ЧАСТЬ:  Название (текст), Год (4 цифры), Жанр (выпадающий
                список + свой ввод; НЕОБЯЗАТЕЛЬНО), Регион (RU/WW)
  ПРАВАЯ ЧАСТЬ: карточка-обложка с фотоаппаратом (необязательно);
                верх карточки — на уровне поля «Название».

Шаг 2 (всё выровнено по левой части):
  ( ) Исполнитель уже существует в базе? → поиск ПО БАЗЕ исполнителей
      (app/store.py; с автодополнением) + «Добавить»; если имени в
      базе нет — подсказка, добавить нельзя
  ( ) Ещё нету такого исполнителя? → столбик: Имя исполнителя,
      Основной жанр (необязательно), «Добавить»; новый исполнитель
      сразу попадает в базу и виден в поиске; СПРАВА — карточка фото
      (подпись «Фото», необязательно)
  Снизу: «Список исполнителей:» — плитки с именем и крестиком
  удаления (ховер — как у плиток альбомов).
"""

from PySide6.QtCore import QRegularExpression, QStringListModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import (
    STARTER_GENRES,
    Album,
    AlbumDraft,
    ArtistDraft,
    TrackDraft,
)
from app.services.deezer import DeezerAlbum
from app.services.spotify import SpotifyAlbum
from app.services.ytmusic import YTMusicAlbum
from app.store import STORE
from app.theme import (
    BG_BAR,
    BORDER,
    RATING_YELLOW,
    SELECTION_BG,
    TEXT,
)
from app.ui.dialogs.autofill_tip_dialog import AutofillTipOverlay
from app.ui.dialogs.autofill_warning_dialog import AutofillWarningOverlay
from app.ui.dialogs.exit_confirm_dialog import ExitConfirmOverlay
from app.ui.dialogs.track_dialog import TrackDialogOverlay
from app.ui.widgets.artist_chip import ArtistChip
from app.ui.widgets.combo_box import DarkComboBox
from app.ui.widgets.cover_picker import CoverPickerCard
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.track_row import (
    TRACK_FRAME_EMPTY_H,
    TRACK_ROW_HEIGHT,
    TrackRow,
)

FORM_WIDTH = 420                       # ширина левой колонки с полями
COVER_TOP_OFFSET = 20                  # отступ обложки сверху: её верх
                                       # совпадает с верхом поля «Название»
TRACK_FRAME_PAD_V = 6                  # вертикальные поля сегмента «Треклист»
QWIDGETSIZE_MAX = 16777215             # «без ограничения» высоты виджета
STEP_NAMES = ["Альбом", "Исполнители", "Треки"]
DUP_WARN_HOLDER_H = 44                 # держатель предупреждения: высота
                                       # постоянна — кнопки не прыгают;
                                       # запас под 3 строки 12px текста


class CreateAlbumOverlay(QWidget):
    """Полнооконный интерфейс создания альбома."""

    album_created = Signal(object)  # Album — «Создать» сохранил в базу
    album_updated = Signal(object)  # Album — «Сохранить» обновил альбом

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("createOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.draft = AlbumDraft()
        self._edit_album: Album | None = None  # режим редактирования
        self._artist_photo_path: str | None = None
        self._track_overlay: TrackDialogOverlay | None = None
        self._warn_overlay: AutofillWarningOverlay | None = None
        self._tip_overlay: AutofillTipOverlay | None = None
        self._exit_overlay: ExitConfirmOverlay | None = None
        self._auto_filled = False   # альбом заполнен по ссылке — метки
        self._auto_filling = False  # идёт программное заполнение: правки
                                    # пользователя отличаем от него
        self._dup_active = False    # активно предупреждение о дубле
        # Черновики, добавленные автозаполнением: жёлтым помечаются
        # только они — добавленное руками остаётся обычным
        self._auto_artist_ids: set[int] = set()
        self._auto_track_ids: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(20)

        # --- Шапка ---
        header = QHBoxLayout()
        header_col = QVBoxLayout()
        self.lbl_title = QLabel("Создание альбома", self)
        self.lbl_title.setObjectName("overlayTitle")
        self.lbl_step = QLabel(self._step_text(0), self)
        self.lbl_step.setObjectName("stepHint")
        header_col.addWidget(self.lbl_title)
        header_col.addWidget(self.lbl_step)
        header.addLayout(header_col)
        header.addStretch(1)
        root.addLayout(header)

        # --- Шаги ---
        self.steps = QStackedWidget(self)
        self.steps.addWidget(self._make_album_step())      # 0: Альбом
        self.steps.addWidget(self._make_artists_step())    # 1: Исполнители
        self.steps.addWidget(self._make_tracks_step())     # 2: Треклист
        root.addWidget(self.steps, 1)

        # --- Подвал ---
        footer = QHBoxLayout()
        self.btn_cancel = HoverButton("Отмена", self)
        self.btn_cancel.setObjectName("ghostButton")
        footer.addWidget(self.btn_cancel)

        # Предупреждение о возможном дубле (ручном создании):
        # жёлтый текст без фона по центру, на уровне кнопок.
        # Держатель ФИКСИРОВАННОЙ высоты растягивается на всё
        # свободное место между «Отменой» и кнопками справа
        # (коэффициент растяжения 1 вместо пары addStretch):
        # показ/скрытие текста не меняет высоту подвала — «Отмена»
        # и «Далее» стоят на месте (не прыгают вверх), а ширины
        # держателя хватает, чтобы текст НЕ переносился на 2-3
        # строки и не обрезался его нижней невидимой границей
        self.lbl_dup_warn = QLabel(
            "Внимание! Возможно такой альбом уже существует, "
            "попробуйте найти его в библиотеке.",
            self,
        )
        self.lbl_dup_warn.setObjectName("dupWarning")
        self.lbl_dup_warn.setWordWrap(True)
        self.lbl_dup_warn.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_dup_warn.hide()
        self.dup_warn_holder = QWidget(self)
        holder_v = QVBoxLayout(self.dup_warn_holder)
        holder_v.setContentsMargins(0, 0, 0, 0)
        holder_v.addWidget(self.lbl_dup_warn)
        self.dup_warn_holder.setFixedHeight(DUP_WARN_HOLDER_H)
        self.dup_warn_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        footer.addWidget(self.dup_warn_holder, 1,
                         Qt.AlignmentFlag.AlignVCenter)

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
        self.btn_back.clicked.connect(self._go_back_step)
        self.btn_next.clicked.connect(self._on_next_clicked)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self._handle_escape
        )

        self._rebuild_artist_chips()

    # ---------- Шаг 1: Альбом ----------
    def _make_album_step(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        # Горизонтальные поля 12px: запас, чтобы карточка у правого края
        # при ховер-увеличении (+10 %) не обрезалась границей родителя
        layout.setContentsMargins(12, 8, 12, 0)
        layout.setSpacing(24)

        # ЛЕВАЯ ЧАСТЬ — форма
        form_holder = QWidget(page)
        form_holder.setFixedWidth(FORM_WIDTH)
        form = QVBoxLayout(form_holder)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(14)

        # Бейджи «!» автозаполнения (жёлтый/красный, справа от поля);
        # в ручном режиме скрыты — там только рамки при дубликате
        self.badge_title = self._make_mark_badge(form_holder)
        self.badge_year = self._make_mark_badge(form_holder)
        self.badge_genre = self._make_mark_badge(form_holder)
        self.badge_region = self._make_mark_badge(form_holder)

        self.input_title = QLineEdit(form_holder)
        self.input_title.setPlaceholderText("Название альбома")
        form.addWidget(self._field(
            "Название", self.input_title, badge=self.badge_title
        ))

        self.input_year = QLineEdit(form_holder)
        self.input_year.setPlaceholderText("1994")
        self.input_year.setMaxLength(4)
        self.input_year.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,4}"))
        )
        form.addWidget(self._field(
            "Год", self.input_year, badge=self.badge_year
        ))

        # Жанр: выпадающий список + свободный ввод своего варианта
        self.combo_genre = DarkComboBox(form_holder)
        self.combo_genre.setEditable(True)
        self.combo_genre.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_genre.addItems(STARTER_GENRES)
        self.combo_genre.setCurrentIndex(-1)
        self.combo_genre.lineEdit().setPlaceholderText("Например, Рок")
        self.combo_genre.setMaxVisibleItems(12)
        form.addWidget(self._field(
            "Жанр", self.combo_genre, optional=True, badge=self.badge_genre
        ))

        # Регион: RU / WW (исключающий выбор)
        region_row = QHBoxLayout()
        region_row.setSpacing(8)
        self.btn_ru = HoverButton("RU", form_holder, outline_radius=8)
        self.btn_ww = HoverButton("WW", form_holder, outline_radius=8)
        for b in (self.btn_ru, self.btn_ww):
            b.setObjectName("regionButton")
            b.setCheckable(True)
            b.setFixedSize(84, 36)
        self.btn_ru.setChecked(True)
        self._region_group = QButtonGroup(self)
        self._region_group.setExclusive(True)
        self._region_group.addButton(self.btn_ru, 0)
        self._region_group.addButton(self.btn_ww, 1)
        region_row.addWidget(self.btn_ru)
        region_row.addWidget(self.btn_ww)
        region_row.addWidget(self.badge_region)  # красный «!» справа
        region_row.addStretch(1)
        form.addWidget(self._field("Регион", region_row))

        form.addStretch(1)
        layout.addWidget(form_holder)

        layout.addStretch(1)  # просвет между левой и правой частью

        # ПРАВАЯ ЧАСТЬ — карточка обложки (необязательно),
        # верх — на уровне поля «Название»
        cover_col = QVBoxLayout()
        cover_col.setSpacing(8)
        cover_col.addSpacing(COVER_TOP_OFFSET)
        self.cover_card = CoverPickerCard(page)
        cover_col.addWidget(self.cover_card, 0, Qt.AlignmentFlag.AlignHCenter)
        caption = QLabel("Обложка", page)
        caption.setObjectName("emptyHint")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cover_col.addWidget(caption)
        cover_col.addStretch(1)
        layout.addLayout(cover_col)

        # Синхронизация черновика и валидация
        self.input_title.textChanged.connect(self._sync_draft)
        self.input_year.textChanged.connect(self._sync_draft)
        self.combo_genre.editTextChanged.connect(self._sync_draft)
        self._region_group.idClicked.connect(self._sync_draft)
        self.cover_card.cover_picked.connect(self._on_cover_picked)
        # Пользователь сам изменил автозаполненное поле — метка снятся
        self.input_title.textChanged.connect(lambda *_: (
            self._revert_auto_mark(self.badge_title, [self.input_title])))
        self.input_year.textChanged.connect(lambda *_: (
            self._revert_auto_mark(self.badge_year, [self.input_year])))
        self.combo_genre.editTextChanged.connect(lambda *_: (
            self._revert_auto_mark(self.badge_genre, [self.combo_genre])))
        self._region_group.idClicked.connect(lambda *_: (
            self._revert_auto_mark(
                self.badge_region, [self.btn_ru, self.btn_ww])))
        return page

    def _make_mark_badge(self, parent: QWidget) -> QLabel:
        """Бейдж «!» автозаполнения: жёлтый/красный, справа от поля."""
        badge = QLabel("!", parent)
        badge.setObjectName("autoMarkBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.hide()
        return badge

    def _field(
        self, label: str, editor: QWidget | QHBoxLayout,
        optional: bool = False, badge: QLabel | None = None,
    ) -> QWidget:
        """Группа «подпись над полем» (+ пометка «(необязательно)»).

        Горизонтальные поля 5px: даже у кнопок у левого края группы
        остаётся запас внутри родителя для ховер-увеличения.
        С бейджем поле оборачивается в строку «поле + «!»» справа.
        """
        box = QWidget(self)
        v = QVBoxLayout(box)
        v.setContentsMargins(5, 0, 5, 3)
        v.setSpacing(6)
        lbl_row = QHBoxLayout()
        lbl_row.setSpacing(6)
        lbl = QLabel(label, box)
        lbl.setObjectName("fieldLabel")
        lbl_row.addWidget(lbl)
        if optional:
            hint = QLabel("(необязательно)", box)
            hint.setObjectName("optionalHint")
            lbl_row.addWidget(hint)
        lbl_row.addStretch(1)
        v.addLayout(lbl_row)
        if badge is not None:
            editor_row = QHBoxLayout()
            editor_row.setSpacing(6)
            if isinstance(editor, QWidget):
                editor_row.addWidget(editor, 1)
            else:
                editor_row.addLayout(editor)
            editor_row.addWidget(badge)
            v.addLayout(editor_row)
        elif isinstance(editor, QWidget):
            v.addWidget(editor)
        else:
            v.addLayout(editor)
        return box

    # ---------- Шаг 2: Исполнители ----------
    def _make_artists_step(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(10)

        title = QLabel("Исполнитель", page)
        title.setObjectName("sectionTitle")
        v.addWidget(title)
        v.addSpacing(4)

        # --- Вариант 1: существующий исполнитель ---
        self.radio_existing = QRadioButton(
            "Исполнитель уже существует в базе?", page
        )
        v.addWidget(self.radio_existing)

        existing_panel = QWidget(page)
        ep_outer = QVBoxLayout(existing_panel)
        ep_outer.setContentsMargins(24, 2, 12, 4)
        ep_outer.setSpacing(4)
        ep = QHBoxLayout()
        ep.setSpacing(10)
        self.input_search = QLineEdit(existing_panel)
        self.input_search.setPlaceholderText("Поиск исполнителя")
        self.input_search.setMinimumWidth(240)
        self.input_search.setMaximumWidth(340)
        ep.addWidget(self.input_search)
        self.btn_add_existing = HoverButton("Добавить", existing_panel)
        self.btn_add_existing.setObjectName("primaryButton")
        ep.addWidget(self.btn_add_existing)
        ep.addStretch(1)
        ep_outer.addLayout(ep)
        # Подсказка при попытке добавить того, кого нет в базе
        self.lbl_search_hint = QLabel("", existing_panel)
        self.lbl_search_hint.setObjectName("errorHint")
        self.lbl_search_hint.hide()
        ep_outer.addWidget(self.lbl_search_hint)
        v.addWidget(existing_panel)

        v.addSpacing(4)

        # --- Вариант 2: новый исполнитель ---
        self.radio_new = QRadioButton("Ещё нету такого исполнителя?", page)
        v.addWidget(self.radio_new)

        new_panel = QWidget(page)
        np_ = QHBoxLayout(new_panel)
        np_.setContentsMargins(24, 2, 12, 4)
        np_.setSpacing(12)

        # Слева — поля нового исполнителя, каждое на своей строке (по ТЗ)
        fields = QVBoxLayout()
        fields.setSpacing(10)

        row_name = QHBoxLayout()
        row_name.setSpacing(8)
        lbl_name = QLabel("Имя исполнителя:", new_panel)
        lbl_name.setObjectName("inlineLabel")
        row_name.addWidget(lbl_name)
        self.input_name = QLineEdit(new_panel)
        self.input_name.setPlaceholderText("Имя исполнителя")
        self.input_name.setMinimumWidth(220)
        self.input_name.setMaximumWidth(320)
        row_name.addWidget(self.input_name)
        row_name.addStretch(1)
        fields.addLayout(row_name)

        row_genre = QHBoxLayout()
        row_genre.setSpacing(8)
        lbl_genre = QLabel("Основной жанр:", new_panel)
        lbl_genre.setObjectName("inlineLabel")
        row_genre.addWidget(lbl_genre)
        hint_genre = QLabel("(необязательно)", new_panel)
        hint_genre.setObjectName("optionalHint")
        row_genre.addWidget(hint_genre)
        self.combo_artist_genre = DarkComboBox(new_panel)
        self.combo_artist_genre.setEditable(True)
        self.combo_artist_genre.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_artist_genre.addItems(STARTER_GENRES)
        self.combo_artist_genre.setCurrentIndex(-1)
        self.combo_artist_genre.lineEdit().setPlaceholderText("Например, Рок")
        self.combo_artist_genre.setMaximumWidth(280)
        row_genre.addWidget(self.combo_artist_genre)
        row_genre.addStretch(1)
        fields.addLayout(row_genre)

        self.btn_add_new = HoverButton("Добавить", new_panel)
        self.btn_add_new.setObjectName("primaryButton")
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_add_new)
        btn_row.addStretch(1)
        fields.addLayout(btn_row)

        np_.addLayout(fields)
        np_.addStretch(1)

        # Справа в сегменте — фото исполнителя (необязательно)
        photo_col = QVBoxLayout()
        # Поля 10px: карточка растёт при ховере на +10% и не должна
        # обрезаться границей панели
        photo_col.setContentsMargins(10, 10, 10, 4)
        photo_col.setSpacing(8)
        self.photo_card = CoverPickerCard(
            new_panel, dialog_title="Выберите фото исполнителя"
        )
        photo_col.addWidget(self.photo_card, 0, Qt.AlignmentFlag.AlignHCenter)
        cap_row = QHBoxLayout()
        cap_row.setSpacing(6)
        cap1 = QLabel("Фото", new_panel)
        cap1.setObjectName("emptyHint")
        cap2 = QLabel("(необязательно)", new_panel)
        cap2.setObjectName("optionalHint")
        cap_row.addStretch(1)
        cap_row.addWidget(cap1)
        cap_row.addWidget(cap2)
        cap_row.addStretch(1)
        photo_col.addLayout(cap_row)
        np_.addLayout(photo_col)

        v.addWidget(new_panel)

        v.addStretch(1)

        # --- Список исполнителей (снизу) ---
        list_title = QLabel("Список исполнителей:", page)
        list_title.setObjectName("listTitle")
        v.addWidget(list_title)

        self.chips_area = QScrollArea(page)
        self.chips_area.setFixedHeight(52)
        self.chips_area.setWidgetResizable(True)
        self.chips_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.chips_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.chips_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chips_container = QWidget()
        chips_row = QHBoxLayout(self.chips_container)
        chips_row.setContentsMargins(10, 4, 10, 4)
        chips_row.setSpacing(12)
        self.chips_row = chips_row
        self.chips_hint = QLabel(
            "Пока пусто — добавьте хотя бы одного исполнителя",
            self.chips_container,
        )
        self.chips_hint.setObjectName("emptyHint")
        self.chips_hint.hide()
        self.chips_area.setWidget(self.chips_container)
        v.addWidget(self.chips_area)

        # --- Поведение ---
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.radio_existing, 0)
        self._mode_group.addButton(self.radio_new, 1)
        self.radio_existing.setChecked(True)

        self._photo_dim = QGraphicsOpacityEffect(self.photo_card)
        self._photo_dim.setOpacity(1.0)
        self.photo_card.setGraphicsEffect(self._photo_dim)

        self.radio_existing.toggled.connect(self._sync_mode)
        self.input_search.textChanged.connect(self._sync_add_states)
        self.input_search.textChanged.connect(self._hide_search_hint)
        self.input_name.textChanged.connect(self._sync_add_states)
        self.btn_add_existing.clicked.connect(self._add_existing_artist)
        self.btn_add_new.clicked.connect(self._add_new_artist)
        self.photo_card.cover_picked.connect(self._on_artist_photo)

        self._sync_mode()
        self._setup_completer()
        return page

    # ---------- Шаг 3: Треклист ----------
    def _make_tracks_step(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(12)

        # Заголовок + кнопка добавления
        head = QHBoxLayout()
        title = QLabel("Треклист", page)
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_add_track = HoverButton("Добавить трек", page)
        self.btn_add_track.setObjectName("primaryButton")
        self.btn_add_track.clicked.connect(self.open_track_dialog)
        head.addWidget(self.btn_add_track)
        v.addLayout(head)

        # Сегмент со списком треков: когда в нём ЕСТЬ треки — тянется
        # на всё свободное место окна (видно максимум строк, которые
        # помещаются, при переполнении — прокрутка). Пока список пуст —
        # компактная высота 56px, прижатая к верху под шапкой
        # (см. _rebuild_tracks).
        self.track_frame = QFrame(page)
        self.track_frame.setObjectName("trackListFrame")
        self.track_frame.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        frame_v = QVBoxLayout(self.track_frame)
        frame_v.setContentsMargins(
            10, TRACK_FRAME_PAD_V, 10, TRACK_FRAME_PAD_V
        )
        frame_v.setSpacing(0)
        self.tracks_area = QScrollArea(self.track_frame)
        self.tracks_area.setWidgetResizable(True)
        self.tracks_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tracks_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tracks_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tracks_container = QWidget()
        self.tracks_flow = QVBoxLayout(self.tracks_container)
        self.tracks_flow.setContentsMargins(0, 0, 0, 0)
        self.tracks_flow.setSpacing(0)
        self.tracks_hint = QLabel(
            "Пока нет треков — добавьте первый кнопкой «Добавить трек»",
            self.tracks_container,
        )
        self.tracks_hint.setObjectName("emptyHint")
        self.tracks_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tracks_area.setWidget(self.tracks_container)
        frame_v.addWidget(self.tracks_area)
        v.addWidget(self.track_frame, 1)
        self._tracks_page_layout = v  # для перевставки сегмента в _rebuild_tracks
        self._rebuild_tracks()
        return page

    def open_track_dialog(self) -> None:
        """Диалог «Новый трек»: блюр-фон + подъём из низа (см. dialogs).

        Исполнители, закреплённые за альбомом (шаг 2), сразу выбраны
        в треке — их можно оставить или убрать крестиком.
        """
        if self._track_overlay is None:
            self._track_overlay = TrackDialogOverlay(self)
            self._track_overlay.track_added.connect(self._on_track_added)
            self._track_overlay.artist_created.connect(
                lambda _name: self._refresh_completer()
            )
        self._track_overlay.open(preset_artists=self.draft.artists)

    def _on_track_added(self, track: TrackDraft) -> None:
        self.draft.tracks.append(track)
        self._rebuild_tracks()

    def _remove_track(self, track: TrackDraft) -> None:
        self.draft.tracks = [t for t in self.draft.tracks if t is not track]
        self._rebuild_tracks()

    def _rebuild_tracks(self) -> None:
        flow = self.tracks_flow
        while flow.count():
            item = flow.takeAt(0)
            widget = item.widget()
            # подсказку не удаляем — она переиспользуется
            if widget is not None and widget is not self.tracks_hint:
                widget.hide()
                widget.deleteLater()
        tracks = self.draft.tracks
        lay = self._tracks_page_layout
        if not tracks:
            self.tracks_hint.show()
            flow.addWidget(self.tracks_hint)
            # Пустой сегмент — компактный (56px) и ПРИЖАТЫЙ К ВЕРХУ:
            # без stretch он не получает лишнего места, и шапка
            # «Треклист» + «Добавить трек» остаются наверху, а сегмент
            # стоит прямо под ними (иначе всё «уезжает» в центр окна)
            self.track_frame.setFixedHeight(TRACK_FRAME_EMPTY_H)
            lay.removeWidget(self.track_frame)
            lay.addWidget(
                self.track_frame, 0, Qt.AlignmentFlag.AlignTop
            )
        else:
            self.tracks_hint.hide()
            total = len(tracks)
            for index, track in enumerate(tracks):
                row = TrackRow(
                    index,
                    track,
                    parent=self.tracks_container,
                    is_last=(index == total - 1),
                )
                row.removed.connect(self._remove_track)
                if self._auto_filled and id(track) in self._auto_track_ids:
                    # Автозаполнение: названия треков из Deezer жёлтые
                    # (вероятнее всего заполнены верно); добавленный
                    # вручную трек остаётся обычного цвета
                    row.lbl_title.setStyleSheet(
                        f"color: {RATING_YELLOW};"
                    )
                else:
                    row.lbl_title.setStyleSheet("")
                flow.addWidget(row)
            # Замыкающий stretch: без него QVBoxLayout раздаёт лишнее
            # место строкам, и они разъезжаются по высоте сегмента.
            # С ним строки стоят плотно друг под другом сверху,
            # а всё свободное место остаётся снизу
            flow.addStretch(1)
            # Сегмент растягивается на всё доступное место окна:
            # видно максимум строк, остальные — прокруткой (как раньше)
            self.track_frame.setMinimumHeight(0)
            self.track_frame.setMaximumHeight(QWIDGETSIZE_MAX)
            lay.removeWidget(self.track_frame)
            lay.addWidget(self.track_frame, 1)
        self._update_next_state()

    # ---------- Поведение ----------
    def _step_text(self, index: int) -> str:
        return f"Шаг {index + 1} из {len(STEP_NAMES)} · {STEP_NAMES[index]}"

    def go_to_step(self, index: int) -> None:
        index = max(0, min(index, self.steps.count() - 1))
        self.steps.setCurrentIndex(index)
        self.lbl_step.setText(self._step_text(index))
        self.btn_back.setVisible(index > 0)
        last = index == self.steps.count() - 1
        if last:
            self.btn_next.setText(
                "Сохранить" if self._edit_album is not None else "Создать"
            )
        else:
            self.btn_next.setText("Далее →")
        self._sync_dup_label()
        self._update_next_state()

    def _on_next_clicked(self) -> None:
        index = self.steps.currentIndex()
        if index == self.steps.count() - 1:
            self._create_album()
        else:
            self.go_to_step(index + 1)

    def _go_back_step(self) -> None:
        """«← Назад»: на ПРЕДЫДУЩИЙ шаг (с 3-го — на 2-й, и т.д.)."""
        self.go_to_step(self.steps.currentIndex() - 1)

    def _create_album(self) -> None:
        """Альбом собран: сохраняем в базу (и на диск), закрываем мастер.

        В режиме редактирования вместо нового альбома обновляется
        существующий (см. store.update_album): кнопка «Сохранить».
        """
        if self._edit_album is not None:
            album = STORE.update_album(self._edit_album, self.draft)
            self._edit_album = None
            self.hide()
            self.album_updated.emit(album)
            return
        album = STORE.add_album(self.draft)
        self.hide()
        self.album_created.emit(album)

    # --- Выход из мастера: предупреждение о потере данных ------------
    def _request_exit(self) -> None:
        """«Отмена»/Esc: при введённых данных — подтверждение выхода."""
        if not self.isVisible():
            return
        if self._has_unsaved_input():
            if self._exit_overlay is None:
                self._exit_overlay = ExitConfirmOverlay(self)
                self._exit_overlay.confirmed.connect(self.hide)
            # Оверлей один на оба режима мастера — тексты ставим на
            # каждый показ: иначе текст первого режима «прилипает»
            if self._edit_album is not None:
                self._exit_overlay.set_texts(
                    title="Выйти из редактирования альбома?",
                    stay_text="Продолжить редактирование",
                )
            else:
                self._exit_overlay.set_texts(
                    title="Выйти из создания альбома?",
                    stay_text="Продолжить создание",
                )
            self._exit_overlay.open()
        else:
            self.hide()

    def _has_unsaved_input(self) -> bool:
        """В мастере есть что терять? (пустой мастер закрывается сразу)"""
        return bool(
            self.steps.currentIndex() > 0
            or self.draft.title
            or self.draft.year
            or self.draft.genre
            or self.draft.artists
            or self.draft.tracks
            or self.draft.cover_path
        )

    def _handle_escape(self) -> None:
        """Esc: совет → предупреждение → диалог трека → выход → мастер."""
        if not self.isVisible():
            return  # Esc не должен управлять спрятанным мастером
        tip = self._tip_overlay
        if tip is not None and tip.isVisible():
            tip.close_overlay()
            return
        warn = self._warn_overlay
        if warn is not None and warn.isVisible():
            warn.close_overlay()
            self.open_autofill_tip()  # совет показывается и после Esc
            return
        overlay = self._track_overlay
        if overlay is not None and overlay.isVisible():
            overlay.handle_escape()
            return
        exit_ov = self._exit_overlay
        if exit_ov is not None and exit_ov.isVisible():
            exit_ov.close_overlay()
            return
        self._request_exit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Оверлеи внутри мастера тянутся на весь его размер;
        # при изменении окна их геометрию надо обновить
        for overlay in (self._warn_overlay, self._tip_overlay,
                        self._exit_overlay):
            if overlay is not None and overlay.isVisible():
                overlay.setGeometry(self.rect())

    # ---------- Автозаполнение с Deezer/Spotify ----------
    def apply_auto_fill(self, data: DeezerAlbum | SpotifyAlbum | YTMusicAlbum) -> None:
        """Заполнить мастер данными источника (после reset()).

        Обложка и фото исполнителей скачиваются в data/covers;
        новые исполнители сразу попадают в базу (их сможет
        проверить пользователь — об этом предупреждает отдельное
        окно). Жанр — если источник его вернул (Spotify жанров
        не отдаёт). На время скачивания мастер заблокирован:
        Esc и клики не могут закрыть его посреди заполнения.

        После заполнения поля помечаются: жёлтый «!» — вероятнее
        всего верно (название, год, жанр, плитки исполнителей,
        названия треков), красный — не заполняется автоматически
        (регион). Метка поля снимается, как только пользователь
        меняет его значение. Ссылка запоминается в черновике
        (source_id) — по ней нельзя создать второй альбом.
        """
        # Программное заполнение: textChanged/editTextChanged НЕ
        # должны снимать метки (они ещё даже не выставлены)
        self._auto_filling = True
        try:
            if data.title:
                self.input_title.setText(data.title)
            if data.year:
                self.input_year.setText(data.year)
            if data.genre:
                self.combo_genre.setEditText(data.genre)

            self.setEnabled(False)
            # Обложка: скачиваем и показываем в карточке
            if data.cover_url:
                cover_path = data.download_image(data.cover_url)
                if cover_path:
                    self.draft.cover_path = cover_path
                    self.cover_card.set_photo_file(
                        str(STORE.resolve(cover_path))
                    )

            # Фото исполнителей качаются один раз на уникальный URL:
            # один артист в нескольких треках не дублирует загрузки
            photo_cache: dict[str, str | None] = {}

            def photo_of(url: str | None) -> str | None:
                if not url:
                    return None
                if url not in photo_cache:
                    photo_cache[url] = data.download_image(url)
                return photo_cache[url]

            # Исполнители альбома: новые — сразу в базу (с фото)
            self.draft.artists = [
                self._ensure_artist(name, data.photos.get(name), photo_of)
                for name in data.artist_names
            ]

            # Треки: исполнители трека тоже попадают в базу
            self.draft.tracks = [
                TrackDraft(
                    title=track.title,
                    artists=[
                        self._ensure_artist(
                            name, data.photos.get(name), photo_of
                        )
                        for name in track.artists
                    ],
                )
                for track in data.tracks
            ]
        finally:
            # Мастер снова активен, правки пользователя больше не
            # являются продолжением программного заполнения
            self.setEnabled(True)
            self._auto_filling = False

        # Метки автозаполнения действуют до правки пользователя;
        # rebuild-ы должны пройти УЖЕ с флагом (жёлтые плитки/треки)
        self._auto_filled = True
        # Жёлтым помечаются только черновики, пришедшие из источника:
        # исполнитель/трек, добавленные потом руками, остаются обычными
        self._auto_artist_ids = {id(a) for a in self.draft.artists}
        self._auto_track_ids = {id(t) for t in self.draft.tracks}
        self.draft.source_id = data.album_id
        self._rebuild_artist_chips()
        self._rebuild_tracks()
        self._sync_draft()
        self._apply_auto_marks()

    def _ensure_artist(self, name: str, photo_url: str | None,
                       get_photo) -> ArtistDraft:
        """Исполнитель в базе (добавить при необходимости) → черновик."""
        photo_path = get_photo(photo_url)
        artist = STORE.find_artist(name)
        if artist is None:
            STORE.add_artist(name, photo_path=photo_path)
            return ArtistDraft(
                name=name, genre="", photo_path=photo_path, existing=True
            )
        if photo_path and not artist.photo_path:
            STORE.update_artist_photo(artist, photo_path)
        return ArtistDraft(
            name=artist.name,
            genre=artist.genre,
            photo_path=artist.photo_path,
            existing=True,
        )

    # --- Цветные метки автозаполнения --------------------------------
    def _repolish(self, widget: QWidget) -> None:
        """Перечитать QSS после смены динамического свойства."""
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _revert_auto_mark(self, badge: QLabel,
                          editors: list[QWidget]) -> None:
        """Пользователь изменил автозаполненное поле — метка снятся.

        Подсвечено только то, что пришло из Deezer и не тронуто
        руками: правка названия/года/жанра/региона возвращает полю
        исходный вид (без «!» и цветной рамки). Программное
        заполнение (apply_auto_fill) и очистка мастера метки не
        трогают.
        """
        if self._auto_filling or not self._auto_filled:
            return
        self._set_field_mark(badge, editors, None)

    def _set_field_mark(self, badge: QLabel, editors: list[QWidget],
                        kind: str | None) -> None:
        """Пометка поля автозаполнения: «!» справа + рамка поля.

        kind: "ok" (жёлтый — вероятнее всего верно), "bad" (красный —
        вероятно неверно/не заполняется автоматически), None — снять.
        """
        if kind:
            badge.setProperty("mark", kind)
            badge.show()
        else:
            badge.hide()
        self._repolish(badge)
        for editor in editors:
            editor.setProperty("autoMark", kind or "")
            self._repolish(editor)

    def _apply_auto_marks(self) -> None:
        """Метки по ТЗ: Название/Год/Жанр — жёлтые, Регион — красный."""
        self._set_field_mark(
            self.badge_title, [self.input_title], "ok"
        )
        self._set_field_mark(self.badge_year, [self.input_year], "ok")
        self._set_field_mark(self.badge_genre, [self.combo_genre], "ok")
        self._set_field_mark(
            self.badge_region, [self.btn_ru, self.btn_ww], "bad"
        )

    def _clear_auto_marks(self) -> None:
        """Снять все метки и бейджи (новая сессия мастера)."""
        self._set_field_mark(self.badge_title, [self.input_title], None)
        self._set_field_mark(self.badge_year, [self.input_year], None)
        self._set_field_mark(self.badge_genre, [self.combo_genre], None)
        self._set_field_mark(
            self.badge_region, [self.btn_ru, self.btn_ww], None
        )

    def open_autofill_warning(self) -> None:
        """Предупреждение поверх заполненного мастера (см. dialogs)."""
        if self._warn_overlay is None:
            self._warn_overlay = AutofillWarningOverlay(self)
            # После предупреждения — окно-совет о жёлтых/красных метках
            self._warn_overlay.accepted.connect(self.open_autofill_tip)
        self._warn_overlay.open()

    def open_autofill_tip(self) -> None:
        """Окно-совет о жёлтых/красных пометках (см. dialogs)."""
        if self._tip_overlay is None:
            self._tip_overlay = AutofillTipOverlay(self)
        self._tip_overlay.open()

    def _sync_draft(self, *_args) -> None:
        self.draft.title = self.input_title.text().strip()
        self.draft.year = self.input_year.text()
        self.draft.genre = self.combo_genre.currentText().strip()
        self.draft.region = "RU" if self.btn_ru.isChecked() else "WW"
        self._update_next_state()
        self._update_dup_warning()

    def _on_cover_picked(self, path: str) -> None:
        self.draft.cover_path = path

    # --- Предупреждение о возможном дубле (ручное создание) ----------
    def _dup_warning_active(self) -> bool:
        """Существует ли альбом с тем же названием и исполнителем?

        На первом шаге исполнители ещё не выбраны — предупреждаем
        по совпадению названия («ВОЗМОЖНО такой альбом уже
        существует»). Когда исполнители выбраны — совпадением
        считается название И хотя бы один общий исполнитель.
        В режиме редактирования сам редактируемый альбом не считается
        дублем — иначе предупреждение висело бы всегда.
        """
        title = self.draft.title.strip().casefold()
        if not title:
            return False
        artist_names = {
            a.name.strip().casefold() for a in self.draft.artists
        }
        for album in STORE.albums:
            if album is self._edit_album:
                continue  # редактируем его — совпадение с самим собой не дубль
            if album.title.strip().casefold() != title:
                continue
            if not artist_names:
                return True  # исполнители ещё не выбраны
            if artist_names & {
                n.casefold() for n in album.artist_names
            }:
                return True
        return False

    def _apply_dup_title_mark(self) -> None:
        """Жёлтая рамка поля «Название» (без восклицательного знака)."""
        self.input_title.setProperty(
            "autoMark", "ok" if self._dup_active else ""
        )
        self._repolish(self.input_title)

    def _sync_dup_label(self) -> None:
        """Жёлтый текст — на первом шаге, на уровне кнопок подвала."""
        self.lbl_dup_warn.setVisible(
            self._dup_active and self.steps.currentIndex() == 0
        )

    def _update_dup_warning(self, *_args) -> None:
        """Пересчитать состояние предупреждения о дубликате."""
        if self._auto_filling:
            return  # идёт автозаполнение: предупреждение не вычисляется
        if self._auto_filled:
            # В режиме автозаполнения действуют метки автозаполнения
            if self._dup_active:
                self._dup_active = False
                self._apply_dup_title_mark()
                self._restyle_artist_chips()
            self.lbl_dup_warn.hide()
            return
        active = self._dup_warning_active()
        if active != self._dup_active:
            self._dup_active = active
            self._apply_dup_title_mark()
            self._restyle_artist_chips()
        self._sync_dup_label()

    def _restyle_artist_chips(self) -> None:
        """Жёлтые рамки плиток (или обычные): по черновику каждого.

        Порядок плиток в chips_row соответствует draft.artists
        (они перестраиваются вместе) — метка ставится только
        автозаполненным или когда актив предупреждение о дубле.
        """
        chips = [
            self.chips_row.itemAt(i).widget()
            for i in range(self.chips_row.count())
        ]
        chips = [w for w in chips if isinstance(w, ArtistChip)]
        for artist, chip in zip(self.draft.artists, chips):
            marked = self._dup_active or (
                self._auto_filled and id(artist) in self._auto_artist_ids
            )
            chip.setProperty("autoMark", "ok" if marked else "")
            self._repolish(chip)

    # --- Режим добавления: существующий / новый ---
    def _sync_mode(self, *_args) -> None:
        existing = self.radio_existing.isChecked()
        self.input_search.setEnabled(existing)
        for w in (self.input_name, self.combo_artist_genre):
            w.setEnabled(not existing)
        self.photo_card.setEnabled(not existing)
        self._photo_dim.setOpacity(1.0 if not existing else 0.35)
        self._sync_add_states()

    def _sync_add_states(self, *_args) -> None:
        self.btn_add_existing.setEnabled(
            self.radio_existing.isChecked()
            and bool(self.input_search.text().strip())
        )
        self.btn_add_new.setEnabled(
            self.radio_new.isChecked()
            and bool(self.input_name.text().strip())
        )

    # --- Добавление / удаление исполнителей ---
    def _setup_completer(self) -> None:
        """Автодополнение поиска именами из базы исполнителей."""
        self._completer = QCompleter(STORE.artist_names(), self.input_search)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.popup().setStyleSheet(
            f"QListView {{ background-color: {BG_BAR}; border: 1px solid {BORDER};"
            f" color: {TEXT}; outline: none; }}"
            f"QListView::item {{ padding: 6px 12px; }}"
            f"QListView::item:selected {{ background-color: {SELECTION_BG}; }}"
        )
        self.input_search.setCompleter(self._completer)

    def _refresh_completer(self) -> None:
        self._completer.setModel(
            QStringListModel(STORE.artist_names(), self._completer)
        )

    def _hide_search_hint(self, *_args) -> None:
        self.lbl_search_hint.hide()

    def _artist_exists(self, name: str) -> bool:
        low = name.casefold()
        return any(a.name.casefold() == low for a in self.draft.artists)

    def _add_existing_artist(self) -> None:
        """Добавить исполнителя ТОЛЬКО если он есть в базе."""
        name = self.input_search.text().strip()
        if not name:
            return
        artist = STORE.find_artist(name)
        if artist is None:
            self.lbl_search_hint.setText(
                "Такого исполнителя нет в базе — добавьте его как нового."
            )
            self.lbl_search_hint.show()
            return
        self.draft.artists.append(ArtistDraft(
            name=artist.name,
            genre=artist.genre,
            photo_path=artist.photo_path,
            existing=True,
        ))
        self.input_search.clear()
        self._rebuild_artist_chips()

    def _add_new_artist(self) -> None:
        name = self.input_name.text().strip()
        if not name or self._artist_exists(name):
            return
        genre = self.combo_artist_genre.currentText().strip()
        self.draft.artists.append(ArtistDraft(
            name=name,
            genre=genre,
            photo_path=self._artist_photo_path,
            existing=False,
        ))
        # Новый исполнитель сразу попадает в базу — теперь он виден
        # в поиске сегмента «уже существует»
        STORE.add_artist(name, genre=genre,
                         photo_path=self._artist_photo_path)
        self._refresh_completer()
        self.input_name.clear()
        self.combo_artist_genre.setCurrentIndex(-1)
        self.combo_artist_genre.lineEdit().clear()
        self.photo_card.clear_photo()
        self._artist_photo_path = None
        self._rebuild_artist_chips()

    def _on_artist_photo(self, path: str) -> None:
        self._artist_photo_path = path

    def _remove_artist(self, artist: ArtistDraft) -> None:
        self.draft.artists = [a for a in self.draft.artists if a is not artist]
        self._rebuild_artist_chips()

    def _rebuild_artist_chips(self) -> None:
        row = self.chips_row
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None and w is not self.chips_hint:
                # hide() — чтобы плитка пропала мгновенно, не дожидаясь
                # отработки deleteLater в цикле событий
                w.hide()
                w.deleteLater()
        if not self.draft.artists:
            self.chips_hint.show()
            row.addWidget(self.chips_hint)
        else:
            self.chips_hint.hide()
            # Жёлтая рамка: у черновика из Deezer или при дубликате;
            # исполнитель, добавленный руками, остаётся обычным
            for artist in self.draft.artists:
                chip = ArtistChip(artist, self.chips_container)
                if self._dup_active or (
                    self._auto_filled and id(artist) in self._auto_artist_ids
                ):
                    chip.setProperty("autoMark", "ok")
                chip.removed.connect(self._remove_artist)
                row.addWidget(chip)
        row.addStretch(1)
        self._update_next_state()
        self._update_dup_warning()

    def _update_next_state(self) -> None:
        if getattr(self, "btn_next", None) is None:
            return  # ещё идёт сборка интерфейса
        index = self.steps.currentIndex()
        if index == 0:
            # Жанр необязателен — остальные поля обязательны
            ready = bool(
                self.draft.title
                and len(self.draft.year) == 4
                and self.draft.region
            )
        elif index == 1:
            ready = len(self.draft.artists) > 0
        else:
            ready = len(self.draft.tracks) > 0  # минимум один трек
        self.btn_next.setEnabled(ready)

    def open_for_edit(self, album: Album) -> None:
        """Открыть мастер в режиме РЕДАКТИРОВАНИЯ существующего альбома.

        Все три этапа prefilled данными альбома: шапка «Редактирование
        альбома», финальная кнопка — «Сохранить» (update вместо
        создания). Предупреждение о дубле не срабатывает на сам
        редактируемый альбом (см. _dup_warning_active).
        """
        self.reset()
        self._edit_album = album
        # Заполняем поля, ГАСЯ их сигналы: каждый textChanged во время
        # заполнения запускает _sync_draft, которая переписала бы
        # черновик значениями ЕЩЁ ПУСТЫХ соседних полей (год и жанр
        # затирались бы названием). Черновик строим ПОСЛЕ заполнения.
        self.input_title.blockSignals(True)
        self.input_year.blockSignals(True)
        self.combo_genre.blockSignals(True)
        try:
            self.input_title.setText(album.title)
            self.input_year.setText(album.year)
            self.combo_genre.setCurrentText(album.genre)
        finally:
            self.input_title.blockSignals(False)
            self.input_year.blockSignals(False)
            self.combo_genre.blockSignals(False)
        # Регион: программный setChecked не кликает кнопку — сигнал
        # idClicked не сработает, черновик не перезапишется
        (self.btn_ru if album.region == "RU" else self.btn_ww).setChecked(
            True
        )
        if album.cover_path is not None:
            path = STORE.resolve(album.cover_path)
            if path is not None:
                self.cover_card.set_photo_file(str(path))
        self.draft = AlbumDraft(
            title=album.title,
            year=album.year,
            genre=album.genre,
            region=album.region,
            cover_path=album.cover_path,  # прежний путь — обложка не
                                          # переимпортируется без изменений
            artists=[
                ArtistDraft(name=name, existing=True)
                for name in album.artist_names
            ],
            tracks=[
                TrackDraft(
                    title=track.title,
                    artists=[
                        ArtistDraft(name=a.name, existing=True)
                        for a in track.artists
                    ],
                )
                for track in album.tracks
            ],
            source_id=album.source_id,
        )
        self.lbl_title.setText("Редактирование альбома")
        self._rebuild_artist_chips()
        self._rebuild_tracks()
        self.go_to_step(0)
        self.input_title.setFocus()

    def reset(self) -> None:
        """Чистое состояние при каждом открытии мастера."""
        self.draft = AlbumDraft()
        self._edit_album = None
        self._artist_photo_path = None
        # Новая сессия: метки автозаполнения и предупреждение дубля
        # сняты; списки автопомеченных черновиков пусты
        self._auto_filled = False
        self._auto_filling = False
        self._dup_active = False
        self._auto_artist_ids = set()
        self._auto_track_ids = set()
        # Внутренние окна не должны переживать открытие
        for overlay in (self._warn_overlay, self._tip_overlay,
                        self._exit_overlay):
            if overlay is not None and overlay.isVisible():
                overlay.close_overlay()
        self._clear_auto_marks()
        self.lbl_dup_warn.hide()
        self.lbl_title.setText("Создание альбома")
        self.input_title.clear()
        self.input_year.clear()
        self.combo_genre.setCurrentIndex(-1)
        self.combo_genre.lineEdit().clear()
        self.btn_ru.setChecked(True)
        self.cover_card.clear_photo()

        self.radio_existing.setChecked(True)
        self.input_search.clear()
        self.lbl_search_hint.hide()
        self.input_name.clear()
        self.combo_artist_genre.setCurrentIndex(-1)
        self.combo_artist_genre.lineEdit().clear()
        self.photo_card.clear_photo()
        self._sync_mode()
        self._rebuild_artist_chips()

        # Внутренний диалог трека закрываем, список треков чистим
        if self._track_overlay is not None and self._track_overlay.isVisible():
            self._track_overlay.hide()
        self._rebuild_tracks()

        self.go_to_step(0)
        self.input_title.setFocus()
