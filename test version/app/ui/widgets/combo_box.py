"""DarkComboBox — выпадающий список со стрелкой, нарисованной вручную.

Почему стрелка не через QSS: известный трюк «width:0 + прозрачные
боковые границы + цветная верхняя» в Qt рисуется ПРОСТО ПРЯМОУГОЛЬНИКОМ
(QStyleSheetStyle заливает весь прямоугольник субконтрола цветом
верхней границы) — воспроизводится на разных стилях и версиях Qt.
Поэтому стрелка рисуется QPainter-ом в paintEvent, а субконтрол
::down-arrow в QSS обнулён, чтобы стиль не рисовал свой вариант.
"""

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QComboBox

DROPDOWN_WIDTH = 28     # ширина зоны стрелки (синхронно с QSS ::drop-down)
ARROW_COLOR = "#9a9a9a"
ARROW_COLOR_HOVER = "#c9c9c9"


class DarkComboBox(QComboBox):
    """QComboBox в тёмной теме со своей треугольной стрелкой."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # поле, рамка, текст из QSS

        cx = self.width() - DROPDOWN_WIDTH / 2
        cy = self.height() / 2
        half_w, half_h = 4.5, 2.25   # половины ширины/высоты треугольника

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 0))
        color = ARROW_COLOR_HOVER if self.underMouse() else ARROW_COLOR
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - half_w, cy - half_h),   # левый верх
            QPointF(cx + half_w, cy - half_h),   # правый верх
            QPointF(cx, cy + half_h),            # низ (острие вниз)
        ]))
