"""Окно «Вы успешно создали альбом, хотите оценить его сейчас?».

Появляется после сохранения нового альбома, когда пользователь
вернулся на главную (сигнал album_created ловит главное окно, см.
main_window._on_album_created). Стиль — как у остальных
внутриприложных окон: блюр-фон главной + подъём карточки из низа
с проявлением. «Да» (primary) открывает мастер оценивания для
свежесозданного альбома (сигнал accepted), «Нет» (ghost) просто
закрывает окно.
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

CARD_SIZE = (460, 210)
RISE_MS = 320
BLUR_RADIUS = 26



class RateAfterCreateOverlay(QWidget):
    """Оверлей «хотите оценить альбом сейчас?» после создания."""

    accepted = Signal()  # «Да» — открыть мастер оценивания

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("afterCreateOverlay")
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

        title = QLabel("Альбом создан!", self.card)
        title.setObjectName("successTitle")
        v.addWidget(title)

        body = QLabel(
            "Вы успешно создали альбом, хотите оценить его сейчас?",
            self.card,
        )
        body.setObjectName("warningBody")
        body.setWordWrap(True)
        v.addWidget(body)

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
        self.btn_yes.clicked.connect(self._accept)
        buttons.addWidget(self.btn_yes)
        v.addLayout(buttons)

    # --- Открытие / закрытие ---------------------------------------------
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
        self.btn_yes.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def _accept(self) -> None:
        self.close_overlay()
        self.accepted.emit()

    # --- Отрисовка и геометрия -------------------------------------------
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
