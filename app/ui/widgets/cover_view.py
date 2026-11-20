"""CoverView — квадратная обложка с самостоятельной отрисовкой.

Три состояния:
  1. Заглушка: цветная плашка + первая буква (карточки на главной).
  2. Иконка фотоаппарата (выбор обложки в мастере создания).
  3. Фотография — выбранный файл, обрезанный до квадрата по центру.

Task 39 — «живая» обложка:
  • наведение плавно ПРИБЛИЖАЕТ картинку на 5 % (она «дышит» внутри
    своей рамки, как в современных музыкальных приложениях);
  • фото масштабируется ОДИН раз в кэш-копию нужного размера, а не
    каждый кадр из оригинала (иначе прокрутка ленты с десятками
    обложек заметно тормозит: smooth-масштабирование 500→160 px
    на каждой перерисовке). Кэш пересобирается только при заметном
    изменении размера/DPI или смене фото; запас 1.18 покрывает зум
    ховера, поэтому рост карточки на 10 % не вызывает пересборку;
  • у заглушки вместо плоской заливки — мягкий диагональный градиент,
    поэтому даже пустые обложки выглядят объёмными;
  • по внутреннему краю всегда идёт тонкая светлая линия (1 px) —
    обложка «отделяется» от фона, не выглядя наклейкой.

Размер задаёт родитель (setGeometry), содержимое масштабируется само.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

PLACEHOLDER_TEXT = QColor(245, 245, 248, 228)  # буква/иконка на заглушке
CAMERA_COLOR = QColor("#a4a4ae")
HOVER_ZOOM = 0.05   # приближение картинки при наведении (5 %)
CACHE_MARGIN = 1.18  # запас кэша под зум и DPR (пересборка — редко)


class CoverView(QWidget):
    def __init__(self, parent: QWidget | None = None, letter: str = "",
                 color: str = "#242428", camera: bool = False,
                 radius: float = 16.0) -> None:
        super().__init__(parent)
        self._letter = letter
        self._color = QColor(color)
        self._camera = camera
        self._radius = radius
        self._photo: QPixmap | None = None       # оригинал
        self._photo_square: QPixmap | None = None  # кроп под квадрат
        self._outline = 0.0                      # сила белой обводки 0..1
        self._scaled: QPixmap | None = None      # кэш масштабированного фото
        self._scaled_key: tuple | None = None    # (w, h, dpr, id кропа)

    # --- Публичное API ---
    def set_outline(self, value: float) -> None:
        """Сила ховер-обводки (0..1); заодно задаёт приближение картинки."""
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
        self._scaled = None
        self._scaled_key = None
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
            self._draw_photo(painter, rect)
        else:
            self._draw_gradient(painter, path, rect)
            if self._camera:
                self._draw_camera(painter)
            elif self._letter:
                self._draw_letter(painter, rect)

        # Тонкая светлая линия по внутреннему краю: обложка «стоит» на
        # фоне, а не сливается с ним (на фото и заглушке одинаково)
        inner = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            inner, max(0.0, self._radius - 0.5), max(0.0, self._radius - 0.5)
        )

        # Ховер-обводка: рисуется ПОСЛЕДНЕЙ поверх содержимого,
        # чуть внутри края (полностью видна, ничем не перекрывается)
        if self._outline > 0.01:
            pen = QPen(QColor(255, 255, 255, int(215 * self._outline)))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = 1.6
            ring = rect.adjusted(inset, inset, -inset, -inset)
            ring_radius = max(0.0, self._radius - inset)
            painter.drawRoundedRect(ring, ring_radius, ring_radius)

    def _scaled_photo(self) -> QPixmap | None:
        """Кэш фото, отмасштабированного под размер виджета.

        Пересобираем только если фото сменилось, DPI другой или размер
        виджета заметно вышел за пределы уже отрисованного запаса.
        Во время ховер-анимации (рост 10 %) кэш переиспользуется —
        иначе каждый кадр выполнял бы дорогое smooth-масштабирование.
        """
        if self._photo_square is None or not self._photo_square.width():
            return None
        width, height = self.width(), self.height()
        if width <= 1 or height <= 1:
            return None
        dpr = self.devicePixelRatioF() or 1.0
        key = id(self._photo_square)
        if self._scaled is not None and self._scaled_key is not None:
            cw, ch, cdpr, ckey = self._scaled_key
            fits = (
                ckey == key
                and cdpr == dpr
                and width <= cw <= width * 1.35
                and height <= ch <= height * 1.35
            )
            if fits:
                return self._scaled
        cache_w = max(1, round(width * CACHE_MARGIN * dpr))
        cache_h = max(1, round(height * CACHE_MARGIN * dpr))
        scaled = self._photo_square.scaled(
            cache_w, cache_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(1.0)
        self._scaled = scaled
        self._scaled_key = (cache_w, cache_h, dpr, key)
        return scaled

    def _draw_photo(self, painter: QPainter, rect: QRectF) -> None:
        """Фото с плавным приближением вокруг центра (ховер)."""
        cached = self._scaled_photo()
        if cached is None:
            return
        zoom = 1.0 + HOVER_ZOOM * self._outline
        width = rect.width() * zoom
        height = rect.height() * zoom
        target = QRectF(
            rect.center().x() - width / 2.0,
            rect.center().y() - height / 2.0,
            width, height,
        )
        source = QRectF(0, 0, cached.width(), cached.height())
        painter.drawPixmap(target, cached, source)

    def _draw_gradient(self, painter: QPainter, path: QPainterPath,
                       rect: QRectF) -> None:
        """Заглушка: мягкий диагональный градиент вместо плоской заливки."""
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        hue, saturation, brightness, _ = self._color.getHsvF()
        hue = 0.61 if hue < 0 else hue
        saturation = max(0.25, saturation)
        brightness = max(0.25, brightness)
        gradient.setColorAt(0, QColor.fromHsvF(hue, saturation * 0.68, min(0.65, brightness + 0.20)))
        gradient.setColorAt(0.5, QColor.fromHsvF(hue, saturation, min(0.51, brightness + 0.05)))
        gradient.setColorAt(1, self._color.darker(153))
        painter.fillPath(path, gradient)

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
