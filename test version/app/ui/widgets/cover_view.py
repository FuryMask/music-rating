"""CoverView — квадратная обложка с самостоятельной отрисовкой.

Три состояния:
  1. Заглушка: цветная плашка + первая буква (карточки на главной).
  2. Иконка фотоаппарата (выбор обложки в мастере создания).
  3. Фотография — выбранный файл, обрезанный до квадрата по центру.

Размер задаёт родитель (setGeometry), содержимое масштабируется само.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

PLACEHOLDER_TEXT = QColor(232, 232, 232, 217)  # буква/иконка на заглушке
CAMERA_COLOR = QColor("#9a9a9a")


class CoverView(QWidget):
    def __init__(self, parent: QWidget | None = None, letter: str = "",
                 color: str = "#2f2f2f", camera: bool = False,
                 radius: float = 12.0) -> None:
        super().__init__(parent)
        self._letter = letter
        self._color = QColor(color)
        self._camera = camera
        self._radius = radius
        self._photo: QPixmap | None = None       # оригинал
        self._photo_square: QPixmap | None = None  # кроп под квадрат
        self._outline = 0.0                      # сила белой обводки 0..1

    # --- Публичное API ---
    def set_outline(self, value: float) -> None:
        """Сила ховер-обводки (0..1); вызывается карточкой-родителем."""
        self._outline = max(0.0, min(1.0, value))
        self.update()
    def set_placeholder(self, letter: str, color: str) -> None:
        self._letter = letter
        self._color = QColor(color)
        self._photo = self._photo_square = None
        self.update()

    def set_camera(self, on: bool) -> None:
        self._camera = on
        self.update()

    def set_photo(self, pixmap: QPixmap | None) -> None:
        """Показать изображение (кроп до квадрата по центру)."""
        if pixmap is None or pixmap.isNull():
            self._photo = self._photo_square = None
        else:
            self._photo = pixmap
            side = min(pixmap.width(), pixmap.height())
            x = (pixmap.width() - side) // 2
            y = (pixmap.height() - side) // 2
            self._photo_square = pixmap.copy(x, y, side, side)
        self.update()

    def has_photo(self) -> bool:
        return self._photo_square is not None

    # --- Геометрия ---
    def sizeHint(self) -> QSize:
        return QSize(160, 160)

    def minimumSizeHint(self) -> QSize:
        return QSize(160, 160)

    # --- Отрисовка ---
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        if self._photo_square is not None:
            painter.drawPixmap(self.rect(), self._photo_square)
        else:
            painter.fillPath(path, self._color)
            if self._camera:
                self._draw_camera(painter)
            elif self._letter:
                self._draw_letter(painter, rect)

        # Ховер-обводка: рисуется ПОСЛЕДНЕЙ поверх содержимого,
        # чуть внутри края (полностью видна, ничем не перекрывается)
        if self._outline > 0.01:
            pen = QPen(QColor(255, 255, 255, int(210 * self._outline)))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = 1.6
            ring = rect.adjusted(inset, inset, -inset, -inset)
            ring_radius = max(0.0, self._radius - inset)
            painter.drawRoundedRect(ring, ring_radius, ring_radius)

    def _draw_letter(self, painter: QPainter, rect: QRectF) -> None:
        font = QFont(self.font())
        font.setPixelSize(max(12, int(self.height() * 0.28)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(PLACEHOLDER_TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._letter)

    def _draw_camera(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        painter.setPen(QPen(CAMERA_COLOR, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        body_w, body_h = w * 0.58, w * 0.44
        cx, cy = w / 2, h / 2 + h * 0.02
        body = QRectF(cx - body_w / 2, cy - body_h / 2, body_w, body_h)
        painter.drawRoundedRect(body, 5, 5)

        lens_r = body_h * 0.30
        painter.drawEllipse(QPointF(cx, cy), lens_r, lens_r)

        bump_w = body_w * 0.28
        painter.drawRoundedRect(
            QRectF(cx - bump_w / 2, body.top() - body_h * 0.14,
                   bump_w, body_h * 0.18),
            2, 2,
        )
