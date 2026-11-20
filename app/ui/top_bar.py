"""Логотип и центрированный поиск в верхней полосе."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QWidget,
)

from app.ui.widgets.glass import line_icon, paint_glass
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import reduced_motion

TOP_BAR_HEIGHT = 64   # высота полосы
SEARCH_WIDTH = 440    # ширина поля поиска
LOGO_TEXT = "Music Rating"


class TopBar(QWidget):
    """Полоса сверху: логотип слева и поле поиска по центру."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFixedHeight(TOP_BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)

        # --- Левая колонка: логотип ---
        self.logo = QLabel(LOGO_TEXT, self)
        self.logo.setObjectName("logo")
        mark = QLabel(self)
        mark.setObjectName("brandMark")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(line_icon("note", 21).pixmap(21))

        self.left_side = QWidget(self)
        self.left_side.setObjectName("topBarSide")
        left_layout = QHBoxLayout(self.left_side)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(mark)
        left_layout.addWidget(self.logo)
        left_layout.addStretch(1)
        self.cloud_button = HoverButton("Из облака", self, outline_radius=12)
        self.cloud_button.setObjectName("cloudDownloadButton")
        self.cloud_button.setIcon(line_icon("cloud-download"))
        self.cloud_button.setAccessibleName("Скачать изменения из облака")
        side_width = max(self.logo.sizeHint().width() + 52, self.cloud_button.sizeHint().width() + 10)
        self.left_side.setFixedWidth(side_width)

        # --- Поле ввода (будущая строка поиска) ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Найти альбом или исполнителя")
        self.search_input.setAccessibleName("Поиск по медиатеке")
        self.search_input.setFixedWidth(SEARCH_WIDTH)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(line_icon("search"), QLineEdit.ActionPosition.LeadingPosition)

        layout.addWidget(self.left_side)
        layout.addWidget(self.search_input, 1, Qt.AlignmentFlag.AlignCenter)
        right_side = QWidget(self)
        right_side.setFixedWidth(side_width)
        right_layout = QHBoxLayout(right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch(1)
        right_layout.addWidget(self.cloud_button)
        layout.addWidget(right_side)

        self._cloud_opacity = QGraphicsOpacityEffect(self.cloud_button)
        self.cloud_button.setGraphicsEffect(self._cloud_opacity)
        self._cloud_pulse = QPropertyAnimation(self._cloud_opacity, b"opacity", self)
        self._cloud_pulse.setDuration(2100)
        self._cloud_pulse.setStartValue(1.0)
        self._cloud_pulse.setKeyValueAt(0.5, 0.65)
        self._cloud_pulse.setEndValue(1.0)
        self._cloud_pulse.setLoopCount(-1)
        self._cloud_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.set_cloud_availability(False, "Войдите через кнопку облака слева внизу.")

    def set_cloud_availability(self, available: bool, message: str) -> None:
        self.cloud_button.setToolTip(message)
        if available == self.cloud_button.isEnabled() and self._cloud_pulse.state() == QPropertyAnimation.State.Running:
            return
        self.cloud_button.setEnabled(available)
        self._cloud_pulse.stop()
        self._cloud_opacity.setOpacity(1.0 if available else 0.55)
        if available and not reduced_motion():
            self._cloud_pulse.start()

    def paintEvent(self, event) -> None:
        paint_glass(self, 22)
