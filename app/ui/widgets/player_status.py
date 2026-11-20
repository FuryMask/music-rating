"""A timed status message with a stationary hover target."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from app.ui.widgets.glass import line_icon

STATUS_MS = 5000
INDICATOR_SIZE = 22


class _StatusIndicator(QWidget):
    hovered = Signal(bool)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setFixedSize(INDICATOR_SIZE, INDICATOR_SIZE)
        self.arrow_visible = False
        self._icon = line_icon("chevron-down", 14)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)

    def paintEvent(self, event) -> None:
        if self.arrow_visible:
            painter = QPainter(self)
            painter.setOpacity(0.48)
            self._icon.paint(painter, self.rect().adjusted(4, 4, -4, -4))


class PlayerStatus(QWidget):
    text_changed = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self._hovered = False
        self._timer = QTimer(self, singleShot=True, interval=STATUS_MS)
        self._timer.timeout.connect(self._refresh)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setObjectName("stepHint")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        policy = self._label.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._label.setSizePolicy(policy)
        layout.addWidget(self._label, 0, 0)
        self._indicator = _StatusIndicator(self)
        self._indicator.setAccessibleName("Показать статус воспроизведения")
        self._indicator.hovered.connect(self._set_hovered)
        layout.addWidget(self._indicator, 0, 0, Qt.AlignmentFlag.AlignCenter)
        self._refresh()

    def setText(self, text: str) -> None:
        if text == self._label.text():
            return
        self._label.setText(text)
        if text:
            self._timer.start()
        else:
            self._timer.stop()
        self._refresh()
        if text:
            self.text_changed.emit()

    def _set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        self._refresh()

    def _refresh(self) -> None:
        has_text = bool(self._label.text())
        show_text = has_text and (self._timer.isActive() or self._hovered)
        self._label.setVisible(show_text)
        self._indicator.setVisible(has_text)
        self._indicator.arrow_visible = has_text and not show_text
        self._indicator.update()

    def hideEvent(self, event) -> None:
        self._set_hovered(False)
        super().hideEvent(event)
