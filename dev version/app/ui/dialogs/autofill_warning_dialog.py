"""Предупреждение после автоматической загрузки альбома с Deezer.

По ТЗ: после открытия мастера с заполненными данными вылезает ещё
одно окно (по стилю — как при создании треков: блюр-фон мастера +
подъём карточки из низа с проявлением), где написано:

    Внимание!                                   (жёлтым цветом)
    Автоматическая загрузка может допускать ошибки, настоятельно
    рекомендуется проверить все данные.         (белым)

Кнопка «Понятно» закрывает окно и ОТКРЫВАЕТ СЛЕДУЮЩЕЕ — окно-совет
о жёлтых/красных пометках (см. dialogs/autofill_tip_dialog.py,
сигнал accepted). Esc закрывает предупреждение с тем же результатом
(порядок обрабатывает create_album._handle_escape).
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.hoverable import HoverButton
from app.ui.dialogs.exit_confirm_dialog import _make_blurred

CARD_SIZE = (440, 230)
RISE_MS = 320
BLUR_RADIUS = 26



class AutofillWarningOverlay(QWidget):
    """Оверлей-предупреждение поверх мастера создания альбома."""

    accepted = Signal()  # окно закрыто кнопкой — пора показать совет

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("warningOverlay")
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

        title = QLabel("Внимание!", self.card)
        title.setObjectName("warningTitle")
        v.addWidget(title)

        body = QLabel(
            "Автоматическая загрузка может допускать ошибки, "
            "настоятельно рекомендуется проверить все данные.",
            self.card,
        )
        body.setObjectName("warningBody")
        body.setWordWrap(True)
        v.addWidget(body)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_ok = HoverButton("Понятно", self.card)
        self.btn_ok.setObjectName("primaryButton")
        self.btn_ok.clicked.connect(self._accept)
        buttons.addWidget(self.btn_ok)
        v.addLayout(buttons)

    def _accept(self) -> None:
        self.close_overlay()
        self.accepted.emit()

    # --- Открытие / закрытие ------------------------------------------------
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
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        self.btn_ok.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    # --- Отрисовка и геометрия ----------------------------------------------
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
