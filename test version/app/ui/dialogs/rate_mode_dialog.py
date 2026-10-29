"""Выбор режима оценивания: «Локально или по сети?» (Task 24).

Открывается вместо мастера при нажатии «Оценить?» (и после создания
альбома). Три кнопки:
  «Нет»      — окно закрывается, ничего не происходит;
  «Локально» — обычный мастер оценивания (rate_album.py);
  «По сети»  — мастер оценивания по сети (rate_network.py, лобби).

ТЕСТОВАЯ СБОРКА: кнопка «По сети» НЕАКТИВНА (сетевые функции в
тестовом билде отключены, подсказка «В разработке») — оценивание
возможно только локально.

Стиль — как у остальных внутриприложных окон: блюр-фон главного окна
+ подъём карточки из низа.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.dialogs.exit_confirm_dialog import _make_blurred
from app.ui.widgets.hoverable import HoverButton

CARD_SIZE = (560, 210)
RISE_MS = 320


class RateModeOverlay(QWidget):
    """Оверлей «Локально или по сети?» поверх главного окна."""

    local_requested = Signal()    # «Локально» — обычный мастер
    network_requested = Signal()  # «По сети» — мастер с лобби

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("rateModeOverlay")
        self._bg: QPixmap | None = None

        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(*CARD_SIZE)

        self._fx = QGraphicsOpacityEffect(self.card)
        self._fx.setOpacity(1.0)
        self.card.setGraphicsEffect(self._fx)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(12)

        title = QLabel("Вы хотите оценить локально или по сети?", self.card)
        title.setObjectName("warningTitle")
        title.setWordWrap(True)
        v.addWidget(title)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_no = HoverButton("Нет", self.card)
        self.btn_no.setObjectName("ghostButton")
        self.btn_no.clicked.connect(self.close_overlay)
        buttons.addWidget(self.btn_no)
        buttons.addStretch(1)
        self.btn_network = HoverButton("По сети", self.card)
        self.btn_network.setObjectName("ghostButton")
        # ТЕСТОВАЯ СБОРКА: «По сети» не работает — сетевые функции
        # отключены (клики невозможны, подсказка объясняет почему;
        # стиль #ghostButton:disabled — серая, как «Выгрузить»)
        self.btn_network.setEnabled(False)
        self.btn_network.setToolTip("В разработке")
        self.btn_network.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_network.clicked.connect(self._go_network)
        buttons.addWidget(self.btn_network)
        self.btn_local = HoverButton("Локально", self.card)
        self.btn_local.setObjectName("primaryButton")
        self.btn_local.clicked.connect(self._go_local)
        buttons.addWidget(self.btn_local)
        v.addLayout(buttons)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.close_overlay
        )

    # --- Открытие / закрытие -----------------------------------------------
    def open(self) -> None:
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        self.show()
        self.raise_()

        target = QPoint(
            (self.width() - CARD_SIZE[0]) // 2,
            (self.height() - CARD_SIZE[1]) // 2,
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
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeleteWhenStopped)
        self.btn_no.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def _go_local(self) -> None:
        self.close_overlay()
        self.local_requested.emit()

    def _go_network(self) -> None:
        self.close_overlay()
        self.network_requested.emit()

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
                (self.width() - CARD_SIZE[0]) // 2,
                (self.height() - CARD_SIZE[1]) // 2,
            )
            self._fx.setOpacity(1.0)

    def mousePressEvent(self, event) -> None:
        event.accept()
