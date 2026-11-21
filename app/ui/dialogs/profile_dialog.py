"""Карточка облачного аккаунта и настройки Music Rating."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPixmap,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import _stable_color
from app.services.cloud_library import CloudSession
from app.store import STORE
from app.theme import (
    THEMES, TEXT_MUTED, VISUALIZERS, apply_theme, save_visualizer, saved_theme, saved_visualizer,
)
from app.ui.dialogs.exit_confirm_dialog import (
    _make_blurred,
    RISE_MS,
)
from app.ui.widgets.combo_box import DarkComboBox
from app.ui.widgets.glass import line_icon
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.toast import KIND_ERROR, KIND_SUCCESS, notify

PROFILE_CARD_SIZE = (480, 420)

TAB_HOME = 0
TAB_ACCOUNT = 1
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
    """Кнопка закрытия или подтверждения в профиле."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=8)
        self.setFixedSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
        self.setIcon(line_icon(kind))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class ProfileOverlay(QWidget):
    """Полнооконный оверлей профиля Supabase."""

    logout_requested = Signal()
    db_imported = Signal()      # база импортирована — обновить все экраны

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("profileOverlay")
        self._bg: QPixmap | None = None
        self._account: CloudSession | None = None
        self._display_name = ""
        self._animation: QParallelAnimationGroup | None = None

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

        card_v.addWidget(self._make_profile_page())

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.handle_escape
        )

    def _make_profile_page(self) -> QWidget:
        page = QWidget(self.card)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # --- Выбор вкладки ---
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons: list[HoverButton] = []
        for index, name in enumerate(
            ("Главная", "Данные", "Настройки", "Статистика")
        ):
            tab = HoverButton(name, page, outline_radius=12)
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
        tab = QWidget(self.tab_content)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, HOVER_PAD)
        self.lbl_email = QLabel(tab)
        self.lbl_email.setObjectName("profileMeta")
        self.lbl_email.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_email.setWordWrap(True)
        layout.addWidget(self.lbl_email)
        layout.addStretch(1)
        self.btn_logout = HoverButton("Выйти из аккаунта", tab)
        self.btn_logout.setObjectName("ghostButton")
        self.btn_logout.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self.btn_logout, 0, Qt.AlignmentFlag.AlignHCenter)
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

        theme_row = QHBoxLayout()
        theme_label = QLabel("Тема:", tab)
        self.theme_select = DarkComboBox(tab)
        self.theme_select.setAccessibleName("Тема приложения")
        self.theme_select.addItems(THEMES)
        self.theme_select.setCurrentText(
            QApplication.instance().property("musicRatingTheme") or saved_theme()
        )
        self.theme_select.setMinimumWidth(150)
        theme_label.setBuddy(self.theme_select)
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme_select)
        theme_row.addStretch(1)
        v.addLayout(theme_row)
        self.theme_select.currentTextChanged.connect(self._change_theme)

        visualizer_row = QHBoxLayout()
        visualizer_label = QLabel("Визуализатор:", tab)
        theme_label.setMinimumWidth(visualizer_label.sizeHint().width())
        self.visualizer_select = DarkComboBox(tab)
        self.visualizer_select.setAccessibleName("Визуализатор плеера")
        for mode, label in VISUALIZERS.items():
            self.visualizer_select.addItem(label, mode)
        self.visualizer_select.setCurrentIndex(self.visualizer_select.findData(saved_visualizer()))
        self.visualizer_select.setMinimumWidth(150)
        visualizer_label.setBuddy(self.visualizer_select)
        visualizer_row.addWidget(visualizer_label)
        visualizer_row.addWidget(self.visualizer_select)
        visualizer_row.addStretch(1)
        v.addLayout(visualizer_row)
        self.visualizer_select.currentIndexChanged.connect(
            lambda index: save_visualizer(self.visualizer_select.itemData(index))
        )

        self.btn_export_db = HoverButton("Экспортировать БД", tab)
        self.btn_export_db.setObjectName("ghostButton")
        self.btn_export_db.setToolTip(
            "Сохранить копию базы с обложками в ZIP-файл"
        )
        self.btn_export_db.clicked.connect(self._do_export_db)
        v.addWidget(self.btn_export_db, 0, Qt.AlignmentFlag.AlignLeft)

        self.btn_import_db = HoverButton("Импортировать БД", tab)
        self.btn_import_db.setObjectName("ghostButton")
        self.btn_import_db.setToolTip(
            "Заменить текущую библиотеку базой из файла"
        )
        self.btn_import_db.clicked.connect(self._do_import_db)
        v.addWidget(self.btn_import_db, 0, Qt.AlignmentFlag.AlignLeft)

        hint = QLabel(
            "Экспорт — копия базы с обложками (ZIP). "
            "Импорт заменяет текущее наполнение.",
            tab,
        )
        hint.setObjectName("fieldLabel")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addStretch(1)
        return tab

    def _change_theme(self, name: str) -> None:
        app = QApplication.instance()
        apply_theme(app, name, persist=True)
        if not self.isVisible():
            return
        window = self.parentWidget()
        self.hide()
        self._bg = _make_blurred(window.grab())
        self.show()
        self.raise_()
        self.theme_select.setFocus()

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
        перечитывает статистику. Облачный вход сохраняется.
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
    def _select_tab(self, index: int) -> None:
        self.tab_buttons[index].setChecked(True)
        self.tab_content.setCurrentIndex(index)
    def _refresh_profile(self) -> None:
        """Наполнить карточку данными текущего пользователя."""
        account = self._account
        if account is None:
            return
        display_name = self._display_name
        self.avatar.set_user(display_name)
        self.lbl_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_name.setText(display_name)
        self.lbl_email.setText(f"Электронная почта: {account.email}" if account.email else "Аккаунт Supabase")
        stats = STORE.user_stats(account.user_id, display_name)
        last = _fmt_date(stats.last_rated_at)
        self.lbl_last_rated.setText(f"Последняя оценка: {last}" if last else "")
        self.lbl_last_rated.setVisible(bool(last))
        created = _fmt_date(account.created_at)
        self.lbl_member.setText(f"В приложении с {created}" if created else "")
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

    # ================= Открытие / закрытие =================
    def set_account(self, account: CloudSession, display_name: str) -> None:
        self._account = account
        self._display_name = display_name
        self._refresh_profile()

    def open(self, account: CloudSession, display_name: str) -> None:
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        self.set_account(account, display_name)
        self._select_tab(TAB_HOME)
        self.show()
        self.raise_()

        target = QPoint(
            (self.width() - PROFILE_CARD_SIZE[0]) // 2,
            (self.height() - PROFILE_CARD_SIZE[1]) // 2,
        )
        self._stop_animation()
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
        self._animation = group
        group.finished.connect(self._stop_animation)
        group.start()

    def _stop_animation(self) -> None:
        if self._animation is not None:
            group, self._animation = self._animation, None
            group.stop()
            group.deleteLater()

    def close_overlay(self) -> None:
        self._stop_animation()
        self._bg = None
        self.card.hide()
        self.hide()

    def handle_escape(self) -> None:
        if self.isVisible():
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
            self._stop_animation()
            self.card.move(
                (self.width() - PROFILE_CARD_SIZE[0]) // 2,
                (self.height() - PROFILE_CARD_SIZE[1]) // 2,
            )
            self._fx.setOpacity(1.0)
    def mousePressEvent(self, event) -> None:
        event.accept()
