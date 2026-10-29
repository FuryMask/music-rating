"""Страница «Облачно» — заглушка облачного режима («В разработке»).

Переключатель режима просмотра (кнопка-БД в сайдбаре, см.
ui/sidebar.py) переводит рабочую зону на эту страницу. В режиме
«Облачно» должны показываться альбомы, загруженные всеми
пользователями, но сетевые функции пока отложены — по центру
полупрозрачная надпись «В разработке» (тот же стиль, что на
странице «Комнаты», QSS #devPlaceholder).

ВАЖНО: страница — единственный ребёнок с stretch=1 в layout, поэтому
она забирает всю высоту рабочей зоны и надпись стоит ровно по центру
(тот же приём против «уезжающей» шапки, что и на rooms_page).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class CloudStubPage(QWidget):
    """Рабочая зона в режиме «Облачно»: надпись «В разработке»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cloudPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)

        self.lbl_dev = QLabel("В разработке", self)
        self.lbl_dev.setObjectName("devPlaceholder")
        self.lbl_dev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # stretch=1: страница одна в layout — надпись центрируется
        # по всей высоте рабочей зоны
        root.addWidget(self.lbl_dev, 1)
