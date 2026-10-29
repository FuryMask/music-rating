"""Стартовая дверь тестовой сборки («Внимание! Выберите, кем вы являетесь»).

Показывается при запуске, если пользователь ещё не вошёл в аккаунт
(сессии нет). Требование ТЗ тестового билда:

  «Внимание!
  Это тестовый билд, сохранность всех действий внутри приложения
  не гарантируется. Доступен только локальный функционал.»

  «Для продолжения требуется выбрать, кем вы являетесь, к сожалению,
  это необходимо в данной версии приложения.»

  <выбор из всех заглушек + «Меня здесь нет»>

  • выбрал заглушку → аккаунт заглушки создаётся автоматически
    (пароль — STUB_PASSWORD из app/build_config.py, по умолчанию «1»)
    и пользователь сразу логинится; имя/пароль дальше можно менять
    в профиле, как у обычного аккаунта;
  • выбрал «Меня здесь нет» → открывается окно входа/регистрации
    (профиль); если закрыть его без входа — дверь вернётся;
  • ВЫЙТИ БЕЗ ВЫБОРА НЕЛЬЗЯ: у двери нет крестика, Esc не закрывает
    её (напоминает красным тостом), клики в главное окно за ней не
    проходят.

Оверлей — ребёнок главного окна (как окно профиля): блокирует всё
содержимое. Фон — сплошной тёмный: содержимое окна в этот момент
всё равно прозрачно (приготовлено к анимации падения), блюр нечего
размывать. Сигналы:

  identity_confirmed() — выбрали заглушку, аккаунт готов и залогинен;
  login_requested()    — выбрали «Меня здесь нет» (окно откроет профиль).

Класс GateProfileOverlay — профиль, который СОобщает о закрытии:
главное окно по закрытию решает — вернуть дверь (не залогинен) или
отыграть анимацию открытия (залогинен).
"""

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.build_config import (
    GATE_CONFIRM,
    GATE_NOBODY,
    GATE_TEXT_1,
    GATE_TEXT_2,
    GATE_TITLE,
    STUB_PASSWORD,
    STUB_USERS,
)
from app.store import STORE
from app.ui.dialogs.profile_dialog import ProfileOverlay
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.toast import KIND_ERROR, notify

GATE_CARD_SIZE = (540, 596)   # карточка двери (шире профиля: 8 заглушек)


class TestGateOverlay(QWidget):
    """Стартовая дверь тестовой сборки поверх главного окна."""

    identity_confirmed = Signal()  # заглушка выбрана и залогинена
    login_requested = Signal()     # «Меня здесь нет» — открыть профиль

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("testGateOverlay")

        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(*GATE_CARD_SIZE)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)

        title = QLabel(GATE_TITLE, self.card)
        title.setObjectName("warningTitle")
        title.setWordWrap(True)
        v.addWidget(title)

        body1 = QLabel(GATE_TEXT_1, self.card)
        body1.setObjectName("warningBody")
        body1.setWordWrap(True)
        v.addWidget(body1)

        body2 = QLabel(GATE_TEXT_2, self.card)
        body2.setObjectName("warningBody")
        body2.setWordWrap(True)
        v.addWidget(body2)

        v.addSpacing(4)

        # --- Сетка заглушек 2 колонки × 4 ряда --------------------------
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._stub_buttons: list[QPushButton] = []

        grid = QGridLayout()
        grid.setSpacing(8)
        for index, name in enumerate(STUB_USERS):
            btn = QPushButton(name, self.card)
            btn.setObjectName("stubButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedHeight(38)
            self._group.addButton(btn, index)
            grid.addWidget(btn, index // 2, index % 2)
            self._stub_buttons.append(btn)
        grid_row = len(STUB_USERS) // 2   # следующий ряд сетки
        self.btn_nobody = QPushButton(GATE_NOBODY, self.card)
        self.btn_nobody.setObjectName("stubButton")
        self.btn_nobody.setCheckable(True)
        self.btn_nobody.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_nobody.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_nobody.setFixedHeight(38)
        self._group.addButton(self.btn_nobody, len(STUB_USERS))
        grid.addWidget(self.btn_nobody, grid_row, 0, 1, 2)  # во всю ширину
        v.addLayout(grid)

        # Свободное место — между сеткой и «Подтвердить» (карточка
        # фиксированной высоты: при другом системном шрифте тексты
        # занимают чуть больше/меньше, кнопка остаётся внизу)
        v.addStretch(1)

        v.addSpacing(4)

        self.btn_confirm = HoverButton(GATE_CONFIRM, self.card)
        self.btn_confirm.setObjectName("primaryButton")
        self.btn_confirm.setEnabled(False)   # пока ничего не выбрано
        self.btn_confirm.clicked.connect(self._confirm)
        v.addWidget(self.btn_confirm, 0, Qt.AlignmentFlag.AlignHCenter)

        # «Подтвердить» активна, пока выбрана хоть одна кнопка группы
        self._group.buttonToggled.connect(
            lambda _btn, _checked: self.btn_confirm.setEnabled(
                self._group.checkedButton() is not None
            )
        )

        # Esc НЕ закрывает дверь — только напоминает красным тостом
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self._remind_must_choose
        )

    # --- Выбор ------------------------------------------------------------
    def _confirm(self) -> None:
        """«Подтвердить»: заглушка → аккаунт и вход; «нет меня» → профиль."""
        selected = self._group.checkedButton()
        if selected is None:
            self._remind_must_choose()
            return
        if selected is self.btn_nobody:
            # Логин/регистрация своими руками: дверь спрячется, профиль
            # откроет главное окно; без входа дверь вернётся
            self.hide()
            self.login_requested.emit()
            return
        name = selected.text()
        user = STORE.find_user(name)
        if user is None:
            # Аккаунта ещё нет — создать с паролем-заглушкой (сразу
            # логинит). Пароль потом можно сменить в профиле.
            user, error = STORE.register_user(
                name, STUB_PASSWORD, STUB_PASSWORD
            )
            if user is None:
                notify(
                    self,
                    error or "Не удалось создать аккаунт",
                    KIND_ERROR,
                )
                return
        else:
            # Аккаунт заглушки уже есть (например, сменили имя/пароль
            # и вернулись) — выбор «кем я есть» и есть вход
            STORE.set_current_user(user)
        self.hide()
        self.identity_confirmed.emit()

    def _remind_must_choose(self) -> None:
        notify(self, "Сначала выберите, кем вы являетесь", KIND_ERROR)

    # --- Открытие -----------------------------------------------------------
    def open_gate(self) -> None:
        """Показать дверь (выбор сброшен, «Подтвердить» неактивна)."""
        parent = self.parentWidget()
        self.setGeometry(parent.rect())
        # Сброс выбора: exclusive-группу надо временно разомкнуть,
        # иначе setChecked(False) на отмеченной кнопке не сработает
        self._group.setExclusive(False)
        for btn in (*self._stub_buttons, self.btn_nobody):
            btn.setChecked(False)
        self._group.setExclusive(True)
        self.btn_confirm.setEnabled(False)

        self.show()
        self.raise_()
        self.card.move(
            (self.width() - GATE_CARD_SIZE[0]) // 2,
            (self.height() - GATE_CARD_SIZE[1]) // 2,
        )
        self.card.show()

    # --- Отрисовка и геометрия ---------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        # Сплошной тёмный фон: содержимое окна в этот момент прозрачно
        # (приготовлено к анимации падения) — блюрить нечего
        painter.fillRect(self.rect(), QColor("#141414"))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self.card.move(
                (self.width() - GATE_CARD_SIZE[0]) // 2,
                (self.height() - GATE_CARD_SIZE[1]) // 2,
            )

    def mousePressEvent(self, event) -> None:
        # Клик мимо карточки ничего не делает — уйти без выбора нельзя
        event.accept()


class GateProfileOverlay(ProfileOverlay):
    """Профиль, сообщающий о закрытии (двери тестовой сборки).

    Из окна входа/регистрации можно выйти (Esc) — тогда главное окно
    обязано решить: пользователь не залогинен → вернуть стартовую
    дверь; залогинен → показать приложение. Обычный ProfileOverlay
    о закрытии не сообщает, поэтому для тестовой сборки используется
    этот подкласс (в том числе по кнопке профиля в сайдбаре).
    """

    closed = Signal()   # окно профиля закрыто (любым способом)

    def close_overlay(self) -> None:
        super().close_overlay()
        self.closed.emit()
