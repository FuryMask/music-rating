"""Верхняя полоса главного окна.

Схема центрирования поиска: две боковые колонки РАВНОЙ фиксированной
ширины (слева — логотип, справа — метка режима просмотра), поле
ввода центрируется в пространстве между ними. Так поиск всегда
ровно по центру полосы, а текущий режим («Локально»/«Облачно»)
виден справа сверху.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from app.ui.widgets.glass import line_icon, paint_glass

TOP_BAR_HEIGHT = 64   # высота полосы
SEARCH_WIDTH = 440    # ширина поля поиска
LOGO_TEXT = "Music Rating"
MODE_LOCAL = "Локально"
MODE_CLOUD = "Облачно"


class TopBar(QWidget):
    """Полоса сверху: логотип слева, поле ввода по центру, режим справа."""

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
        side_width = self.logo.sizeHint().width() + 52
        self.left_side.setFixedWidth(side_width)

        # --- Поле ввода (будущая строка поиска) ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Найти альбом или исполнителя")
        self.search_input.setAccessibleName("Поиск по медиатеке")
        self.search_input.setFixedWidth(SEARCH_WIDTH)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(line_icon("search"), QLineEdit.ActionPosition.LeadingPosition)

        # --- Правая колонка: метка режима просмотра (балансир той же
        # ширины, что логотип — центровка поиска не смещается) ---
        self.right_side = QWidget(self)
        self.right_side.setObjectName("topBarSide")
        self.right_side.setFixedWidth(side_width)
        self.mode_label = QLabel(MODE_LOCAL, self.right_side)
        self.mode_label.setObjectName("modeLabel")
        right_layout = QHBoxLayout(self.right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch(1)
        right_layout.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.left_side)
        layout.addWidget(self.search_input, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.right_side)

    def paintEvent(self, event) -> None:
        paint_glass(self, 22)

    def set_mode_text(self, text: str) -> None:
        """Обновить надпись режима («Локально»/«Облачно») справа."""
        self.mode_label.setText(text)
