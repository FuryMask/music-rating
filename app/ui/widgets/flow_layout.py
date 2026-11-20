"""FlowLayout — компоновка «плитки с переносом на новую строку».

Порт классического примера Qt (itemviews/flowlayout): дети идут
слева направо, не влезло — перенос вниз. Нужен для плиток
исполнителей в диалоге трека: ширина карточки ограничена, чипы
должны переноситься, а не растягивать карточку по горизонтали.
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Вертикально-горизонтальная «текучая» раскладка виджетов."""

    def __init__(self, parent: QWidget | None = None,
                 spacing: int = 10) -> None:
        super().__init__(parent)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    # --- QLayout API ---
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # --- Раскладка ---
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        right = rect.right() - margins.right()

        x, y = left, top
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            item_w, item_h = hint.width(), hint.height()

            # Перенос: строка не первая И элемент не влезает до края
            if x != left and x + item_w > right:
                x = left
                y += line_height + self.spacing()
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(item_w, item_h)))

            x += item_w + self.spacing()
            line_height = max(line_height, item_h)

        # Как в каноническом примере Qt: без ограничения высотой rect —
        # иначе heightForWidth для «пробного» rect высотой 0 даёт -1
        return y + line_height - rect.y() + margins.bottom()
