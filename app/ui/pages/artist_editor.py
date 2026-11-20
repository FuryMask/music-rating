"""Страница «Редактирование исполнителя» — имя, фото, жанр.

Открывается кнопкой «Редактировать» на странице исполнителя.
В отличие от мастера альбома (полнооконный оверлей) редактор —
ОБЫЧНАЯ страница рабочей зоны: занимает только основное поле,
верхняя полоса с поиском и сайдбар остаются на месте.

Поля:
  • фото — круглое превью + «Выбрать фото…» (файл копируется в
    data/covers при сохранении) и «Убрать фото» (повторное нажатие
    возвращает). Превью показывает то, что реально увидит страница:
    новое фото → текущее → аватар-обложка → заглушка с буквой;
  • имя — обязательное, уникальное (без учёта регистра; имя — ключ
    ссылок, STORE.update_artist синхронизирует альбомы и фиты);
  • жанр — выпадающий список с возможностью ввести свой вариант;
    пустое значение возвращает автоподсчёт по альбомам
    (см. store.artist_main_genre).

«Назад»/Esc/«Отмена» закрывают страницу без сохранения (сигнал
back_clicked ловит главное окно). Сохранение эмитит artist_saved.
Ошибки валидации — всплывающие тосты над главным окном (Task 31,
см. widgets/toast.py).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import STARTER_GENRES, Artist
from app.store import STORE
from app.ui.pages.album_detail import BackButton
from app.ui.widgets.combo_box import DarkComboBox
from app.ui.widgets.cover_picker import IMAGE_FILTER
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.toast import KIND_ERROR, notify

PHOTO_SIZE = 140        # сторона круглого превью фото


class ArtistEditorPage(QWidget):
    """Редактор исполнителя: занимает только основное поле окна."""

    back_clicked = Signal()        # «назад»/«Отмена» — закрыть без сохранения
    artist_saved = Signal(object)  # Artist — сохранение выполнено

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("artistEditorPage")
        self._artist: Artist | None = None
        self._photo_src: str | None = None   # выбранный файл (не в базе)
        self._photo_cleared = False          # нажато «Убрать фото»

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(20)

        # --- Шапка: назад + заголовок ---
        self.btn_back = BackButton(self)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        head = QHBoxLayout()
        head.addWidget(self.btn_back)
        head.addSpacing(12)
        lbl_title = QLabel("Редактирование исполнителя", self)
        lbl_title.setObjectName("detailTitle")
        head.addWidget(lbl_title)
        head.addStretch(1)
        root.addLayout(head)

        # --- Фото: круглое превью + кнопки ---
        photo_row = QHBoxLayout()
        photo_row.setSpacing(24)

        self.photo = CoverView(self, radius=PHOTO_SIZE / 2)  # круг
        self.photo.setFixedSize(PHOTO_SIZE, PHOTO_SIZE)
        photo_row.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)

        photo_col = QVBoxLayout()
        photo_col.setSpacing(10)

        lbl_photo = QLabel("Фото", self)
        lbl_photo.setObjectName("fieldLabel")
        photo_col.addWidget(lbl_photo)

        self.btn_choose = HoverButton("Выбрать фото…", self)
        self.btn_choose.setObjectName("ghostButton")
        self.btn_choose.setToolTip("Выбрать картинку на диске")
        self.btn_choose.setFixedWidth(170)
        self.btn_choose.clicked.connect(self._choose_photo)
        photo_col.addWidget(self.btn_choose)

        self.btn_remove = HoverButton("Убрать фото", self)
        self.btn_remove.setObjectName("ghostButton")
        self.btn_remove.setFixedWidth(170)
        self.btn_remove.clicked.connect(self._toggle_photo)
        photo_col.addWidget(self.btn_remove)

        self.lbl_photo_hint = QLabel(
            "Если своего фото нет, исполнитель показывается с обложкой "
            "одного из его альбомов.",
            self,
        )
        self.lbl_photo_hint.setObjectName("emptyHint")
        self.lbl_photo_hint.setWordWrap(True)
        photo_col.addWidget(self.lbl_photo_hint)
        photo_col.addStretch(1)

        photo_row.addLayout(photo_col, 1)
        root.addLayout(photo_row)

        # --- Имя ---
        lbl_name = QLabel("Имя", self)
        lbl_name.setObjectName("fieldLabel")
        root.addWidget(lbl_name)

        self.input_name = QLineEdit(self)
        self.input_name.setPlaceholderText("Имя исполнителя")
        self.input_name.textChanged.connect(self._hide_error)
        root.addWidget(self.input_name)

        # --- Жанр ---
        lbl_genre = QLabel("Жанр", self)
        lbl_genre.setObjectName("fieldLabel")
        root.addWidget(lbl_genre)

        self.combo_genre = DarkComboBox(self)
        self.combo_genre.setEditable(True)
        self.combo_genre.addItems(STARTER_GENRES)
        self.combo_genre.setFixedWidth(280)
        self.combo_genre.editTextChanged.connect(self._hide_error)
        root.addWidget(self.combo_genre, 0, Qt.AlignmentFlag.AlignLeft)

        root.addStretch(1)

        # --- Кнопки: Отмена / Сохранить ---
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = HoverButton("Отмена", self)
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.back_clicked.emit)
        buttons.addWidget(self.btn_cancel)
        self.btn_save = HoverButton("Сохранить", self)
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.clicked.connect(self._save)
        buttons.addWidget(self.btn_save)
        root.addLayout(buttons)

    # --- Данные -----------------------------------------------------------
    def set_artist(self, artist: Artist) -> None:
        """Открыть редактор для исполнителя (сброс несохранённых правок)."""
        self._artist = artist
        self._photo_src = None
        self._photo_cleared = False

        self.input_name.setText(artist.name)
        self.combo_genre.setCurrentText(artist.genre)
        self._refresh_photo()

    # --- Фото ---------------------------------------------------------------
    def _refresh_photo(self) -> None:
        """Превью: выбранный файл → текущее фото/аватар → заглушка."""
        src = self._photo_src
        if (
            src is None
            and not self._photo_cleared
            and self._artist is not None
        ):
            src = STORE.artist_avatar_path(self._artist)
        pixmap = QPixmap()
        resolved = STORE.resolve(src)
        if resolved is not None:
            pixmap = QPixmap(str(resolved))
        if not pixmap.isNull():
            self.photo.set_photo(pixmap)
        else:
            letter = self._artist.display_letter if self._artist else "?"
            color = (
                self._artist.display_color if self._artist else "#333333"
            )
            self.photo.set_placeholder(letter, color)

        has_current = (
            self._artist is not None and self._artist.photo_path is not None
        )
        self.btn_remove.setVisible(
            has_current or self._photo_src is not None or self._photo_cleared
        )
        self.btn_remove.setText(
            "Вернуть фото" if self._photo_cleared else "Убрать фото"
        )

    def _choose_photo(self) -> None:
        """Файловый диалог: выбранный файл показывается сразу,
        в базу попадёт при сохранении (STORE.update_artist)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите фото исполнителя", "", IMAGE_FILTER
        )
        if not path:
            return
        self._photo_src = path
        self._photo_cleared = False
        self._refresh_photo()

    def _toggle_photo(self) -> None:
        """«Убрать фото» / повторное нажатие — вернуть."""
        if self._photo_cleared:
            self._photo_cleared = False
            self._photo_src = None
        else:
            self._photo_cleared = True
            self._photo_src = None
        self._refresh_photo()

    # --- Сохранение -----------------------------------------------------------
    def _save(self) -> None:
        """Сохранить имя/фото/жанр и закрыть страницу."""
        if self._artist is None:
            return
        name = self.input_name.text().strip()
        if not name:
            self._show_error("Введите имя исполнителя.")
            return
        existing = STORE.find_artist(name)
        if existing is not None and existing is not self._artist:
            self._show_error("Исполнитель с таким именем уже есть.")
            return
        artist = STORE.update_artist(
            self._artist,
            name,
            self.combo_genre.currentText(),
            photo_src=self._photo_src,
            clear_photo=self._photo_cleared,
        )
        self.artist_saved.emit(artist)

    # --- Ошибка валидации ---------------------------------------------------
    def _show_error(self, text: str) -> None:
        """Ошибка валидации — красный всплывающий тост (Task 31)."""
        notify(self, text, KIND_ERROR)

    def _hide_error(self, *_args) -> None:
        pass  # тосты закрываются сами — прятать нечего
