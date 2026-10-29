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

TOP_BAR_HEIGHT = 56   # высота полосы
SEARCH_WIDTH = 440    # ширина поля поиска
LOGO_TEXT = "Music Rating"
MODE_LOCAL = "Локально"
MODE_CLOUD = "Облачно"


class TopBar(QWidget):
    """Полоса сверху: логотип слева, поле ввода по центру, режим справа."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        # Без этого флага QSS-фон не рисуется у наследников QWidget
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TOP_BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)

        # --- Левая колонка: логотип ---
        self.logo = QLabel(LOGO_TEXT, self)
        self.logo.setObjectName("logo")

        self.left_side = QWidget(self)
        self.left_side.setObjectName("topBarSide")
        self.left_side.setFixedWidth(self.logo.sizeHint().width())
        left_layout = QHBoxLayout(self.left_side)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.logo)

        # --- Поле ввода (будущая строка поиска) ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Поиск…")
        self.search_input.setFixedWidth(SEARCH_WIDTH)
        self.search_input.setClearButtonEnabled(True)

        # --- Правая колонка: метка режима просмотра (балансир той же
        # ширины, что логотип — центровка поиска не смещается) ---
        self.right_side = QWidget(self)
        self.right_side.setObjectName("topBarSide")
        self.right_side.setFixedWidth(self.logo.sizeHint().width())
        self.mode_label = QLabel(MODE_LOCAL, self.right_side)
        self.mode_label.setObjectName("modeLabel")
        right_layout = QHBoxLayout(self.right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch(1)
        right_layout.addWidget(self.mode_label)

        layout.addWidget(self.left_side)
        layout.addWidget(self.search_input, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.right_side)

    def set_mode_text(self, text: str) -> None:
        """Обновить надпись режима («Локально»/«Облачно») справа."""
        self.mode_label.setText(text)
