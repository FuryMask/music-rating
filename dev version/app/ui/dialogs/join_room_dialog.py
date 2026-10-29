"""Подтверждение присоединения к комнате («Присоединиться к оцениванию?»).

Клик по строке комнаты на странице «Комнаты» (см. pages/rooms_page.py)
открывает это окно: «Нет» закрывает его без действий, «Да» (primary)
присоединяет к оцениванию — сигнал confirmed. Тело карточки: название
альбома и имя хоста комнаты.

Стиль — как у остальных внутриприложных окон: блюр-фон главного окна
+ подъём карточки из низа. Esc закрывает окно без присоединения.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QKeySequence,
    QPainter,
    QColor,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.dialogs.exit_confirm_dialog import _make_blurred
from app.ui.widgets.hoverable import HoverButton

CARD_SIZE = (480, 200)
RISE_MS = 320


class JoinRoomOverlay(QWidget):
    """Оверлей «Присоединиться к оцениванию?» поверх главного окна."""

    confirmed = Signal()  # «Да» — открыть сетевой мастер как гость

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("joinRoomOverlay")
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

        title = QLabel("Присоединиться к оцениванию?", self.card)
        title.setObjectName("warningTitle")
        title.setWordWrap(True)
        v.addWidget(title)

        self.lbl_body = QLabel("", self.card)
        self.lbl_body.setObjectName("warningBody")
        self.lbl_body.setWordWrap(True)
        v.addWidget(self.lbl_body)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_no = HoverButton("Нет", self.card)
        self.btn_no.setObjectName("ghostButton")
        self.btn_no.clicked.connect(self.close_overlay)
        buttons.addWidget(self.btn_no)
        buttons.addStretch(1)
        self.btn_yes = HoverButton("Да", self.card)
        self.btn_yes.setObjectName("primaryButton")
        self.btn_yes.clicked.connect(self._confirm_join)
        buttons.addWidget(self.btn_yes)
        v.addLayout(buttons)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.close_overlay
        )

    # --- Открытие / закрытие -----------------------------------------------
    def open(self, album_title: str, host_name: str) -> None:
        """Показать окно с данными комнаты (альбом + хост)."""
        self.lbl_body.setText(f"Альбом: {album_title}\nХост: {host_name}")
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
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        self.btn_yes.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def _confirm_join(self) -> None:
        self.close_overlay()
        self.confirmed.emit()

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
