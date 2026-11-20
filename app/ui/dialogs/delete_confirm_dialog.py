"""Подтверждение удаления альбома (кнопка «Удалить» на его странице).

Тот же стиль, что у остальных внутриприложных окон (см.
dialogs/autofill_warning_dialog.py):
  • фон оверлея — РАЗМЫТЫЙ снимок главного окна (grab + blur);
  • карточка (#dialogCard) поднимается из низа с проявлением;
  • «Удалить альбом?» красным (#dangerTitle), тело белым;
  • «Отмена» (ghost) и красная «Удалить» (#dangerButton).

Esc = отмена. Подтверждение → сигнал confirmed: главное окно
удаляет альбом из базы и возвращается на главную страницу.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
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

from app.ui.widgets.hoverable import HoverButton
from app.ui.dialogs.exit_confirm_dialog import _make_blurred

CARD_SIZE = (480, 240)
RISE_MS = 320
BLUR_RADIUS = 26



class DeleteConfirmOverlay(QWidget):
    """Оверлей «точно удалить этот альбом?» поверх главного окна."""

    confirmed = Signal()  # «Удалить» — удаляем

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("confirmOverlay")
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

        title = QLabel("Удалить альбом?", self.card)
        title.setObjectName("dangerTitle")
        v.addWidget(title)

        body = QLabel("", self.card)
        body.setObjectName("warningBody")
        body.setWordWrap(True)
        v.addWidget(body)
        self.lbl_body = body

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_cancel = HoverButton("Отмена", self.card)
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.close_overlay)
        buttons.addWidget(self.btn_cancel)
        buttons.addStretch(1)
        self.btn_delete = HoverButton("Удалить", self.card)
        self.btn_delete.setObjectName("dangerButton")
        self.btn_delete.clicked.connect(self._confirm)
        buttons.addWidget(self.btn_delete)
        v.addLayout(buttons)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.close_overlay
        )

    # --- Открытие / закрытие -----------------------------------------------
    def open(self, album_title: str) -> None:
        """Показать поверх окна с именем альбома в тексте."""
        self.lbl_body.setText(
            f"«{album_title}» и его треки будут удалены из библиотеки. "
            "Исполнители останутся в базе. Действие нельзя отменить."
        )
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
        self.btn_cancel.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def _confirm(self) -> None:
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
