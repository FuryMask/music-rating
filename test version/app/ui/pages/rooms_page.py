"""Страница «Комнаты» — заглушка («В разработке»).

По ТЗ сетевые функции отложены: по кнопке-планете в сайдбаре рабочая
зона показывает ТОЛЬКО надпись «В разработке» — как и страница
облачного режима (см. pages/cloud_page.py, тот же QSS
#devPlaceholder). Никаких списков комнат и лобби-переходов здесь
больше нет: реестр ROOMS (см. pages/rate_network.py) продолжает
существовать для сетевых сессий, но интерфейса под него пока нет.

ВАЖНО: надпись — единственный ребёнок с stretch=1 в layout, поэтому
она стоит ровно по центру рабочей зоны. Возврат — «назад» (Esc),
страница участвует в стеке навигации главного окна.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class RoomsPage(QWidget):
    """Страница «Комнаты»: только надпись «В разработке»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("roomsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)

        self.lbl_dev = QLabel("В разработке", self)
        self.lbl_dev.setObjectName("devPlaceholder")
        self.lbl_dev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # stretch=1: страница одна в layout — надпись центрируется
        # по всей высоте рабочей зоны
        root.addWidget(self.lbl_dev, 1)
