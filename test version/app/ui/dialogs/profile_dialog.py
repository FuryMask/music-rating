"""Окно профиля — вход, регистрация и карточка аккаунта (вкладки).

Открывается кнопкой профиля в сайдбаре (левее «+»). Стиль — как у
остальных внутриприложных окон: блюр-фон главного окна + подъём
карточки из низа с проявлением (см. dialogs/exit_confirm_dialog.py).

Состояния карточки (внутренний QStackedWidget):
  1. ВХОД (не залогинен): поля «Логин»/«Пароль», кнопка «Войти»,
     под ней гиперссылка «Ещё нет аккаунта?» — переключает карточку
     на РЕГИСТРАЦИЮ: «Логин»/«Пароль»/«Подтвердите пароль».
  2. ПРОФИЛЬ (залогинен — после входа/регистрации/перезапуска):
     сверху выбор вкладки — «Главная» / «Данные» / «Настройки» /
     «Статистика» и маленькая кнопка «✕» в самом конце ряда —
     возврат в меню:
       • Главная — аватар, имя, дата последней оценки (пока оценок
         нет, строка даты скрыта);
       • Данные (бывшая «Настройки») — поля смены пароля (новый +
         подтверждение) и имени — каждое со своей маленькой
         кнопкой-галочкой, компактная красная «Удалить аккаунт» и
         «Выйти из аккаунта». Оповещения об успехе/ошибке смены
         (Task 31) — ВСПЛЫВАЮЩИЕ ТОСТЫ сверху по центру главного
         окна (см. widgets/toast.py): зелёная галочка или красный
         крестик + уходящая полоска прогресса; строки-статусы
         внутри карточки больше не используются.
         «Сменить» имя/пароль на АКТУАЛЬНЫЕ нельзя — отдельная
         ошибка (Task 22). У кнопок
         в краях вкладки есть запас под ховер-рост: «Удалить аккаунт»
         не срезается слева, «Выйти из аккаунта» — снизу, галочки —
         справа (Task 22);
       • Настройки (Task 30) — экспорт и импорт БД:
         «Экспортировать БД» (проводник: выбрать место сохранения —
         ZIP-архив с базой и обложками, см. STORE.export_library) и
         «Импортировать БД» (проводник: выбрать файл; локальное
         наполнение ЗАМЕНЯЕТСЯ содержимым выбранной базы, см.
         STORE.import_library), после импорта сигнал db_imported —
         главное окно обновляет экраны; итог — тост («База
         сохранена»/«База импортирована» либо красная ошибка);
       • Статистика — оценено альбомов, любимый альбом, любимый
         исполнитель, любимая оценка, самый нелюбимый альбом,
         самый нелюбимый исполнитель.
     Удаление аккаунта — подтверждение (блюр поверх профиля).
  3. Аккаунты = участники оценивания: создали профиль — имя появилось
     на шаге 1 мастера оценивания (STORE.raters).

Esc: закрыть подтверждение → закрыть окно.
После удаления аккаунта сигнал account_deleted — главное окно
обновляет главную и страницу альбома (оценки пересчитаны).
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    QPointF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPixmap,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import _stable_color
from app.store import STORE
from app.theme import TEXT_MUTED
from app.ui.dialogs.exit_confirm_dialog import (
    _make_blurred,
    ExitConfirmOverlay,
    RISE_MS,
)
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.toast import KIND_ERROR, KIND_SUCCESS, notify

PROFILE_CARD_SIZE = (480, 420)

PAGE_LOGIN = 0
PAGE_REGISTER = 1
PAGE_PROFILE = 2

TAB_HOME = 0
TAB_ACCOUNT = 1      # «Данные» — пароль/имя/удаление (бывшая «Настройки»)
TAB_SETTINGS = 2     # «Настройки» — экспорт/импорт БД (Task 30)
TAB_STATS = 3

EXPORT_FILTER = "База Music Rating (*.zip)"
IMPORT_FILTER = (
    "База Music Rating (*.zip);;"
    "База SQLite (*.db *.sqlite);;"
    "Все файлы (*)"
)

ICON_BUTTON_SIZE = 28   # сторона маленьких кнопок-иконок (✕ и галочки)
HOVER_PAD = 10          # запас в краях вкладки под ховер-рост (+10 %)

_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_date(iso: str | None) -> str:
    """ISO-момент → «23 октября 2026»; пусто/криво — пустая строка."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return (
        f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]} {moment.year}"
    )


class UserAvatar(QLabel):
    """Круглый аватар с первой буквой имени (как обложки-заглушки)."""

    SIZE = 56

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._letter = "?"
        self._color = "#3a4347"

    def set_user(self, username: str) -> None:
        self._letter = (username[:1] or "?").upper()
        self._color = _stable_color(username)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(QColor("#e8e8e8"))
        font = self.font()
        font.setPixelSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._letter)


class IconToolButton(HoverButton):
    """Маленькая квадратная кнопка с иконкой, нарисованной линиями.

    kind="close" — крестик (возврат в меню из карточки профиля),
    kind="check" — галочка (подтвердить смену пароля/имени). Иконки
    рисуются в paintEvent по образцу кнопок сайдбара: глиф шрифтом
    выглядит грубо и по-разному на разных системах.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=8)
        self._kind = kind
        self.setFixedSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон и рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e8e8e8"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        if self._kind == "close":
            arm = 5.0
            painter.drawLine(QPointF(cx - arm, cy - arm),
                             QPointF(cx + arm, cy + arm))
            painter.drawLine(QPointF(cx - arm, cy + arm),
                             QPointF(cx + arm, cy - arm))
        else:  # check
            painter.drawLine(QPointF(cx - 5.0, cy + 0.5),
                             QPointF(cx - 1.5, cy + 4.0))
            painter.drawLine(QPointF(cx - 1.5, cy + 4.0),
                             QPointF(cx + 5.5, cy - 3.5))


class ProfileOverlay(QWidget):
    """Полноэкранное окно профиля (вход / регистрация / аккаунт)."""

    account_deleted = Signal()  # аккаунт удалён — обновить главную/альбом
    db_imported = Signal()      # база импортирована — обновить все экраны

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("profileOverlay")
        self._bg: QPixmap | None = None
        self._confirm: ExitConfirmOverlay | None = None

        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(*PROFILE_CARD_SIZE)

        self._fx = QGraphicsOpacityEffect(self.card)
        self._fx.setOpacity(1.0)
        self.card.setGraphicsEffect(self._fx)

        card_v = QVBoxLayout(self.card)
        card_v.setContentsMargins(28, 24, 28, 24)
        card_v.setSpacing(14)

        self.pages = QStackedWidget(self.card)
        self.pages.addWidget(self._make_login_page())       # PAGE_LOGIN
        self.pages.addWidget(self._make_register_page())    # PAGE_REGISTER
        self.pages.addWidget(self._make_profile_page())     # PAGE_PROFILE
        card_v.addWidget(self.pages)

        # Esc — свой обработчик (подтверждение → закрытие);
        # глухой guard на видимость — шорткат сработает и при скрытом
        # окне, т.к. контекст — всё главное окно
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.handle_escape
        )

    # ================= Страница входа =================
    def _make_login_page(self) -> QWidget:
        page = QWidget(self.pages)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        title = QLabel("Вход", page)
        title.setObjectName("profileTitle")
        v.addWidget(title)

        v.addWidget(self._field_label("Логин", page))
        self.in_login = QLineEdit(page)
        self.in_login.setPlaceholderText("Логин")
        v.addWidget(self.in_login)

        v.addWidget(self._field_label("Пароль", page))
        self.in_password = QLineEdit(page)
        self.in_password.setPlaceholderText("Пароль")
        self.in_password.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.in_password)

        v.addStretch(1)

        self.btn_login = HoverButton("Войти", page)
        self.btn_login.setObjectName("primaryButton")
        self.btn_login.clicked.connect(self._do_login)
        v.addWidget(self.btn_login, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_login_link = QLabel(
            f'<a href="register" style="color: {TEXT_MUTED};">'
            "Ещё нет аккаунта?</a>",
            page,
        )
        self.lbl_login_link.setObjectName("authLink")
        self.lbl_login_link.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.lbl_login_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.lbl_login_link.linkActivated.connect(
            lambda _href: self._show_register()
        )
        v.addWidget(self.lbl_login_link)
        return page

    # ================= Страница регистрации =================
    def _make_register_page(self) -> QWidget:
        page = QWidget(self.pages)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        title = QLabel("Регистрация", page)
        title.setObjectName("profileTitle")
        v.addWidget(title)

        v.addWidget(self._field_label("Логин", page))
        self.in_reg_login = QLineEdit(page)
        self.in_reg_login.setPlaceholderText("Логин")
        v.addWidget(self.in_reg_login)

        v.addWidget(self._field_label("Пароль", page))
        self.in_reg_password = QLineEdit(page)
        self.in_reg_password.setPlaceholderText("Пароль")
        self.in_reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.in_reg_password)

        v.addWidget(self._field_label("Подтвердите пароль", page))
        self.in_reg_password2 = QLineEdit(page)
        self.in_reg_password2.setPlaceholderText("Подтвердите пароль")
        self.in_reg_password2.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.in_reg_password2)

        v.addStretch(1)

        self.btn_register = HoverButton("Зарегистрироваться", page)
        self.btn_register.setObjectName("primaryButton")
        self.btn_register.clicked.connect(self._do_register)
        v.addWidget(self.btn_register, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_register_link = QLabel(
            f'<a href="login" style="color: {TEXT_MUTED};">'
            "Уже есть аккаунт?</a>",
            page,
        )
        self.lbl_register_link.setObjectName("authLink")
        self.lbl_register_link.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.lbl_register_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.lbl_register_link.linkActivated.connect(
            lambda _href: self._show_login()
        )
        v.addWidget(self.lbl_register_link)
        return page

    # ================= Страница профиля (вкладки) =================
    def _make_profile_page(self) -> QWidget:
        page = QWidget(self.pages)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # --- Выбор вкладки ---
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []
        for index, name in enumerate(
            ("Главная", "Данные", "Настройки", "Статистика")
        ):
            tab = QPushButton(name, page)
            tab.setObjectName("profileTab")
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tab_group.addButton(tab, index)
            tab.clicked.connect(
                lambda _checked=False, i=index: self._select_tab(i)
            )
            tabs_row.addWidget(tab)
            self.tab_buttons.append(tab)
        tabs_row.addStretch(1)

        # Маленькая кнопка в самом конце ряда вкладок — возврат в меню
        self.btn_close_menu = IconToolButton("close", page)
        self.btn_close_menu.setObjectName("profileCloseButton")
        self.btn_close_menu.setToolTip("Вернуться в меню")
        self.btn_close_menu.clicked.connect(self.close_overlay)
        tabs_row.addWidget(self.btn_close_menu)
        v.addLayout(tabs_row)

        # --- Содержимое вкладок ---
        self.tab_content = QStackedWidget(page)
        self.tab_content.addWidget(self._make_tab_home())      # TAB_HOME
        self.tab_content.addWidget(self._make_tab_account())   # TAB_ACCOUNT
        self.tab_content.addWidget(self._make_tab_settings())  # TAB_SETTINGS
        self.tab_content.addWidget(self._make_tab_stats())     # TAB_STATS
        v.addWidget(self.tab_content, 1)
        return page

    def _make_tab_home(self) -> QWidget:
        tab = QWidget(self.tab_content)
        h = QHBoxLayout(tab)
        h.setContentsMargins(0, 8, 0, 0)
        h.setSpacing(18)

        self.avatar = UserAvatar(tab)
        h.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(7)
        self.lbl_name = QLabel("", tab)
        self.lbl_name.setObjectName("profileName")
        self.lbl_name.setWordWrap(True)
        col.addWidget(self.lbl_name)
        self.lbl_last_rated = QLabel("", tab)
        self.lbl_last_rated.setObjectName("profileMeta")
        col.addWidget(self.lbl_last_rated)
        self.lbl_member = QLabel("", tab)
        self.lbl_member.setObjectName("profileMeta")
        col.addWidget(self.lbl_member)
        col.addStretch(1)
        h.addLayout(col)
        h.addStretch(1)
        return tab

    def _make_tab_account(self) -> QWidget:
        """Вкладка «Данные»: смена пароля и имени, выход, удаление."""
        tab = QWidget(self.tab_content)
        v = QVBoxLayout(tab)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        # Оповещения об успехе/ошибке смены — всплывающие тосты над
        # главным окном (Task 31): строк-статусов внутри карточки
        # больше нет, поля не сдвигаются и ничего не резервируется.

        # --- Смена пароля: 2 поля + кнопка-галочка справа.
        # Правое поле строки — запас под ховер-рост галочки, иначе её
        # край срезается границей вкладки (Task 22, п. 1)
        password_row = QHBoxLayout()
        password_row.setSpacing(8)
        password_row.setContentsMargins(0, 0, HOVER_PAD, 0)
        self.in_new_password = QLineEdit(tab)
        self.in_new_password.setPlaceholderText("Новый пароль")
        self.in_new_password.setEchoMode(QLineEdit.EchoMode.Password)
        password_row.addWidget(self.in_new_password, 1)
        self.in_new_password2 = QLineEdit(tab)
        self.in_new_password2.setPlaceholderText("Подтвердите пароль")
        self.in_new_password2.setEchoMode(QLineEdit.EchoMode.Password)
        password_row.addWidget(self.in_new_password2, 1)
        self.btn_apply_password = IconToolButton("check", tab)
        self.btn_apply_password.setObjectName("checkButton")
        self.btn_apply_password.setToolTip("Сменить пароль")
        self.btn_apply_password.clicked.connect(self._do_change_password)
        password_row.addWidget(self.btn_apply_password)
        v.addLayout(password_row)

        # --- Смена имени: поле с текущим именем + кнопка-галочка
        # (правый запас — как у строки пароля)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.setContentsMargins(0, 0, HOVER_PAD, 0)
        self.in_name = QLineEdit(tab)
        self.in_name.setPlaceholderText("Имя")
        name_row.addWidget(self.in_name, 1)
        self.btn_apply_name = IconToolButton("check", tab)
        self.btn_apply_name.setObjectName("checkButton")
        self.btn_apply_name.setToolTip("Сменить имя")
        self.btn_apply_name.clicked.connect(self._do_rename)
        name_row.addWidget(self.btn_apply_name)
        v.addLayout(name_row)

        # Удалить аккаунт — компактная красная кнопка слева. Отступ
        # строки — запас под ховер-рост кнопки влево: без него кнопка
        # срезается левым краем вкладки (Task 22, п. 1). AlignLeft
        # обязателен: без него кнопка растягивается на всю строку.
        # Точный запас ставит _update_delete_pad по фактической ширине
        # кнопки (шрифт системы может сделать её шире 200 px)
        self._delete_row = QHBoxLayout()
        delete_row = self._delete_row
        delete_row.setContentsMargins(HOVER_PAD, 0, 0, 0)
        self.btn_delete_account = HoverButton("Удалить аккаунт", tab)
        self.btn_delete_account.setObjectName("dangerSmallButton")
        self.btn_delete_account.setToolTip(
            "Удалить аккаунт и все его оценки"
        )
        self.btn_delete_account.clicked.connect(self._request_delete)
        delete_row.addWidget(
            self.btn_delete_account, 0, Qt.AlignmentFlag.AlignLeft
        )
        v.addLayout(delete_row)

        v.addStretch(1)

        # Выйти из аккаунта — внизу вкладки (аккаунт остаётся в
        # участниках). Пространство ПОД кнопкой — запас под
        # ховер-рост вниз: без него низ кнопки срезается краем
        # вкладки (Task 22, п. 1)
        self.btn_logout = HoverButton("Выйти из аккаунта", tab)
        self.btn_logout.setObjectName("ghostButton")
        self.btn_logout.clicked.connect(self._do_logout)
        v.addWidget(self.btn_logout, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(HOVER_PAD)
        return tab

    def _make_tab_settings(self) -> QWidget:
        """Вкладка «Настройки» (Task 30): экспорт и импорт БД.

        Итог операции — всплывающий тост (Task 31): зелёный
        «База сохранена»/«База импортирована» либо красная ошибка.
        """
        tab = QWidget(self.tab_content)
        v = QVBoxLayout(tab)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        self.btn_export_db = HoverButton("Экспортировать БД", tab)
        self.btn_export_db.setObjectName("ghostButton")
        self.btn_export_db.setToolTip(
            "Сохранить копию базы с обложками в ZIP-файл"
        )
        self.btn_export_db.clicked.connect(self._do_export_db)
        v.addWidget(self.btn_export_db, 0, Qt.AlignmentFlag.AlignHCenter)

        self.btn_import_db = HoverButton("Импортировать БД", tab)
        self.btn_import_db.setObjectName("ghostButton")
        self.btn_import_db.setToolTip(
            "Заменить текущую библиотеку базой из файла"
        )
        self.btn_import_db.clicked.connect(self._do_import_db)
        v.addWidget(self.btn_import_db, 0, Qt.AlignmentFlag.AlignHCenter)

        # Пояснение (текст, не кнопка): формат экспорта и смысл импорта.
        # Ширина ФИКСИРОВАННАЯ: у wordWrap-метки с выравниванием
        # компоновка берёт «квадратный» sizeHint — текст обрезался
        hint = QLabel(
            "Экспорт — копия базы с обложками (ZIP). "
            "Импорт заменяет текущее наполнение.",
            tab,
        )
        hint.setObjectName("fieldLabel")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hint.setFixedWidth(PROFILE_CARD_SIZE[0] - 140)
        v.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch(1)
        return tab

    def _make_tab_stats(self) -> QWidget:
        tab = QWidget(self.tab_content)
        v = QVBoxLayout(tab)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        self.lbl_stat_count = QLabel("", tab)
        self.lbl_stat_count.setObjectName("statRow")
        self.lbl_stat_count.setWordWrap(True)
        v.addWidget(self.lbl_stat_count)

        self.lbl_stat_album = QLabel("", tab)
        self.lbl_stat_album.setObjectName("statRow")
        self.lbl_stat_album.setWordWrap(True)
        v.addWidget(self.lbl_stat_album)

        self.lbl_stat_artist = QLabel("", tab)
        self.lbl_stat_artist.setObjectName("statRow")
        self.lbl_stat_artist.setWordWrap(True)
        v.addWidget(self.lbl_stat_artist)

        self.lbl_stat_rating = QLabel("", tab)
        self.lbl_stat_rating.setObjectName("statRow")
        self.lbl_stat_rating.setWordWrap(True)
        v.addWidget(self.lbl_stat_rating)

        self.lbl_stat_worst_album = QLabel("", tab)
        self.lbl_stat_worst_album.setObjectName("statRow")
        self.lbl_stat_worst_album.setWordWrap(True)
        v.addWidget(self.lbl_stat_worst_album)

        self.lbl_stat_worst_artist = QLabel("", tab)
        self.lbl_stat_worst_artist.setObjectName("statRow")
        self.lbl_stat_worst_artist.setWordWrap(True)
        v.addWidget(self.lbl_stat_worst_artist)

        v.addStretch(1)
        return tab

    # --- Вспомогательное -------------------------------------------------
    @staticmethod
    def _field_label(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("fieldLabel")
        return label

    # ================= Поведение =================
    def _show_login(self) -> None:
        self._clear(self.in_login, self.in_password)
        self.pages.setCurrentIndex(PAGE_LOGIN)
        self.in_login.setFocus()

    def _show_register(self) -> None:
        self._clear(self.in_reg_login, self.in_reg_password,
                    self.in_reg_password2)
        self.pages.setCurrentIndex(PAGE_REGISTER)
        self.in_reg_login.setFocus()

    @staticmethod
    def _clear(*inputs: QLineEdit) -> None:
        for field in inputs:
            field.clear()

    def _do_login(self) -> None:
        user, error = STORE.authenticate(
            self.in_login.text(), self.in_password.text()
        )
        if user is None:
            notify(self, error or "Ошибка входа", KIND_ERROR)
            return
        self._clear(self.in_login, self.in_password)
        self._show_profile_page()

    def _do_register(self) -> None:
        user, error = STORE.register_user(
            self.in_reg_login.text(),
            self.in_reg_password.text(),
            self.in_reg_password2.text(),
        )
        if user is None:
            notify(self, error or "Ошибка", KIND_ERROR)
            return
        self._clear(self.in_reg_login, self.in_reg_password,
                    self.in_reg_password2)
        self._show_profile_page()

    def _do_logout(self) -> None:
        STORE.logout()
        self._show_login()

    def _show_profile_page(self) -> None:
        self._refresh_profile()
        self.pages.setCurrentIndex(PAGE_PROFILE)
        self._select_tab(TAB_HOME)

    def _do_change_password(self) -> None:
        """Галочка у полей пароля: новый пароль + подтверждение.

        «Сменить» пароль на текущий нельзя — хранилище вернёт
        ошибку (Task 22, п. 3); итог — всплывающий тост (Task 31):
        красная ошибка или зелёное «Пароль изменён».
        """
        user = STORE.current_user
        if user is None:
            self._show_login()
            return
        new = self.in_new_password.text()
        if not new:
            notify(self, "Введите новый пароль", KIND_ERROR)
            return
        if new != self.in_new_password2.text():
            notify(self, "Пароли не совпадают", KIND_ERROR)
            return
        error = STORE.change_password(user, new)
        if error is not None:
            notify(self, error, KIND_ERROR)
            return
        self._clear(self.in_new_password, self.in_new_password2)
        notify(self, "Пароль изменён", KIND_SUCCESS)

    def _do_rename(self) -> None:
        """Галочка у поля имени: переименовать аккаунт.

        То же самое имя сменой не считается — ошибка (Task 22, п. 3);
        итог — всплывающий тост (Task 31).
        """
        user = STORE.current_user
        if user is None:
            self._show_login()
            return
        error = STORE.rename_user(user, self.in_name.text())
        if error is not None:
            notify(self, error, KIND_ERROR)
            return
        # Аватар, имя на «Главной», поле и список участников обновятся
        self._refresh_profile()
        notify(self, "Имя изменено", KIND_SUCCESS)

    # ================= Экспорт / импорт БД (вкладка «Настройки») =========
    def _do_export_db(self) -> None:
        """«Экспортировать БД»: проводник → ZIP с базой и обложками.

        Проводник открывается с предложением имени файла (без DBMS —
        это просто копия библиотеки); расширение .zip добавляется
        при необходимости (STORE.export_library тоже подстрахуется).
        Итог — всплывающий тост (Task 31): зелёный «База сохранена»
        или красная ошибка записи.
        """
        default = str(Path.home() / "music-rating-library.zip")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Сохранить копию базы", default, EXPORT_FILTER
        )
        if not path_str:
            return  # пользователь отменил выбор — ничего не делаем
        try:
            STORE.export_library(Path(path_str))
        except OSError as exc:
            reason = exc.strerror or str(exc)
            notify(self, f"Не удалось сохранить: {reason}", KIND_ERROR)
            return
        notify(self, "База сохранена", KIND_SUCCESS)

    def _do_import_db(self) -> None:
        """«Импортировать БД»: проводник → замена локального наполнения.

        STORE.import_library проверяет файл ДО подмены живой базы:
        ошибка (не база/повреждён) ничего не меняет и показывается
        красным тостом. После успешного импорта карточка
        перечитывается (пользователь мог смениться), зелёный тост
        «База импортирована», сигнал db_imported заставит главное
        окно обновить экраны; если в импортированной базе нет
        пользователей — возврат к входу.
        """
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл базы", str(Path.home()), IMPORT_FILTER
        )
        if not path_str:
            return
        error = STORE.import_library(Path(path_str))
        if error is not None:
            notify(self, error, KIND_ERROR)
            return
        self._refresh_profile()
        notify(self, "База импортирована", KIND_SUCCESS)
        self.db_imported.emit()
        if STORE.current_user is None:
            # В импортированной базе нет аккаунтов — карточку не показать
            self._show_login()

    def _select_tab(self, index: int) -> None:
        self.tab_buttons[index].setChecked(True)
        self.tab_content.setCurrentIndex(index)
        # Ширина кнопок вкладки известна только после её показа —
        # пересчитать запас «Удалить аккаунт» (см. _update_delete_pad)
        QTimer.singleShot(0, self._update_delete_pad)

    def _refresh_profile(self) -> None:
        """Наполнить карточку данными текущего пользователя."""
        user = STORE.current_user
        if user is None:
            return
        self.avatar.set_user(user.username)
        self.lbl_name.setText(user.username)
        # Дата последней оценки: пока оценок нет — строки нет вовсе
        last = _fmt_date(user.last_rated_at)
        if last:
            self.lbl_last_rated.setText(f"Последняя оценка: {last}")
            self.lbl_last_rated.show()
        else:
            self.lbl_last_rated.hide()
        created = _fmt_date(user.created_at)
        self.lbl_member.setText(
            f"В приложении с {created}" if created else ""
        )

        # Поля «Настроек» — в исходное состояние
        self._clear(self.in_new_password, self.in_new_password2)
        self.in_name.setText(user.username)

        stats = STORE.user_stats(user)
        self.lbl_stat_count.setText(
            f"Оценено альбомов: {stats.rated_count}"
        )
        if stats.favorite_album is not None:
            title, average = stats.favorite_album
            self.lbl_stat_album.setText(
                f"Любимый альбом: «{title}» — {average:.1f}"
            )
        else:
            self.lbl_stat_album.setText("Любимый альбом: —")
        if stats.favorite_artist is not None:
            name, average = stats.favorite_artist
            self.lbl_stat_artist.setText(
                f"Любимый исполнитель: {name} — {average:.1f}"
            )
        else:
            self.lbl_stat_artist.setText("Любимый исполнитель: —")
        if stats.favorite_rating is not None:
            self.lbl_stat_rating.setText(
                f"Любимая оценка: {stats.favorite_rating:.1f}"
            )
        else:
            self.lbl_stat_rating.setText("Любимая оценка: —")
        if stats.least_favorite_album is not None:
            title, average = stats.least_favorite_album
            self.lbl_stat_worst_album.setText(
                f"Самый нелюбимый альбом: «{title}» — {average:.1f}"
            )
        else:
            self.lbl_stat_worst_album.setText("Самый нелюбимый альбом: —")
        if stats.least_favorite_artist is not None:
            name, average = stats.least_favorite_artist
            self.lbl_stat_worst_artist.setText(
                f"Самый нелюбимый исполнитель: {name} — {average:.1f}"
            )
        else:
            self.lbl_stat_worst_artist.setText(
                "Самый нелюбимый исполнитель: —"
            )

    # ================= Удаление аккаунта =================
    def _request_delete(self) -> None:
        """«Удалить аккаунт» → подтверждение с блюром поверх профиля."""
        if self._confirm is None:
            self._confirm = ExitConfirmOverlay(
                self,
                title="Удалить аккаунт?",
                body=(
                    "Аккаунт и все его оценки будут удалены. "
                    "Это действие необратимо."
                ),
                exit_text="Удалить",
                stay_text="Отмена",
                title_name="dangerTitle",
            )
            self._confirm.confirmed.connect(self._delete_account)
        self._confirm.open()

    def _delete_account(self) -> None:
        user = STORE.current_user
        if user is None:
            return
        STORE.delete_user(user)
        self.close_overlay()
        self.account_deleted.emit()

    # ================= Открытие / закрытие =================
    def open(self) -> None:
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        # Состояние карточки: залогинен — профиль, нет — вход
        if STORE.current_user is not None:
            self._show_profile_page()
        else:
            self._show_login()

        self.show()
        self.raise_()

        target = QPoint(
            (self.width() - PROFILE_CARD_SIZE[0]) // 2,
            (self.height() - PROFILE_CARD_SIZE[1]) // 2,
        )
        self._fx.setOpacity(0.0)
        self.card.move(target.x(), self.height() + 8)

        pos_anim = QPropertyAnimation(self.card, b"pos", self.card)
        pos_anim.setDuration(RISE_MS)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        pos_anim.setStartValue(self.card.pos())
        pos_anim.setEndValue(target)
        fade_anim = QPropertyAnimation(self._fx, b"opacity", self.card)
        fade_anim.setDuration(RISE_MS)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        # Запас под ховер-рост «Удалить аккаунт» — по фактической ширине
        # кнопки (она известна только после раскладки карточки)
        QTimer.singleShot(0, self._update_delete_pad)

    def _update_delete_pad(self) -> None:
        """Отступ «Удалить аккаунт» слева = выступ ховера (ширина/20)."""
        pad = max(HOVER_PAD, int(self.btn_delete_account.width() / 20) + 1)
        self._delete_row.setContentsMargins(pad, 0, 0, 0)

    def close_overlay(self) -> None:
        if self._confirm is not None and self._confirm.isVisible():
            self._confirm.close_overlay()
        self.card.hide()
        self.hide()

    def handle_escape(self) -> None:
        """Esc: подтверждение → закрытие окна."""
        if not self.isVisible():
            return
        if self._confirm is not None and self._confirm.isVisible():
            self._confirm.close_overlay()
            return
        self.close_overlay()

    # --- Отрисовка и геометрия ---------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._bg is not None:
            painter.drawPixmap(self.rect(), self._bg)
        else:
            painter.fillRect(self.rect(), QColor("#141414"))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self.card.move(
                (self.width() - PROFILE_CARD_SIZE[0]) // 2,
                (self.height() - PROFILE_CARD_SIZE[1]) // 2,
            )
            self._fx.setOpacity(1.0)
            if self._confirm is not None and self._confirm.isVisible():
                self._confirm.setGeometry(self.rect())

    def mousePressEvent(self, event) -> None:
        event.accept()
