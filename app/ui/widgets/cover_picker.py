"""Карточка выбора изображения: фотоаппарат → проводник → фото.

Один класс для обложки альбома («Обложка») и фото исполнителя
(«Фото») — различаются только заголовком файлового диалога.
Вынесена из мастера в виджеты, чтобы её могли использовать
и диалоги (например, окно создания исполнителя в диалоге трека).

Ховер — по единому стандарту: белая обводка (её рисует CoverView —
ребёнок, поверх содержимого) + рост на 10 % за 250 мс.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QWidget

from app.ui.widgets.album_card import CARD_SIZE, COVER_RADIUS
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import Hoverable

IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)"


class CoverPickerCard(Hoverable, QWidget):
    """Кликабельная квадратная карточка с выбором картинки."""

    cover_picked = Signal(str)  # путь к выбранному файлу

    def __init__(self, parent: QWidget | None = None,
                 dialog_title: str = "Выберите обложку") -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dialog_title = dialog_title

        self.cover = CoverView(self, camera=True, radius=COVER_RADIUS)
        # Обводку рисует CoverView (ребёнок), поэтому на себе не рисуем
        self.init_hover(outline_radius=COVER_RADIUS, outline_on_self=False)

    def sizeHint(self):
        return QSize(CARD_SIZE, CARD_SIZE)

    def minimumSizeHint(self):
        return QSize(CARD_SIZE, CARD_SIZE)

    def clear_photo(self) -> None:
        self.cover.set_photo(None)

    def set_photo_file(self, path: str) -> None:
        """Показать картинку из файла (например, скачанную с Deezer)."""
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.cover.set_photo(pixmap)

    def _on_hover_progress(self, value: float) -> None:
        self.cover.set_outline(value)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.cover.setGeometry(0, 0, self.width(), self.width())

    def mousePressEvent(self, event) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._dialog_title, "", IMAGE_FILTER
        )
        if path:
            self.cover.set_photo(QPixmap(path))
            self.cover_picked.emit(path)
