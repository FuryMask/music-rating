"""Примесь Hoverable — стандарт ховера для всех «кнопок» приложения.

Правила (единые для карточек, кнопок и всего кликабельного):
  • тонкая белая обводка плавно появляется/исчезает за 250 мс;
  • размер элемента плавно увеличивается на 10 % за 250 мс.

Использование:
    class MyCard(Hoverable, QWidget):
        def __init__(...):
            super().__init__(...)
            self.init_hover(outline_radius=12)

Примесь также рисует обводку в paintEvent и анимирует геометрию
вокруг центра, приподнимая элемент над соседями (raise_).
"""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    Property,
    QPropertyAnimation,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

HOVER_MS = 250       # длительность анимаций
HOVER_SCALE = 1.10   # увеличение при наведении (+10 %)


class Hoverable:
    """Примесь поверх любого QWidget-наследника."""

    def init_hover(self, outline_radius: float = 8.0,
                   outline_on_self: bool = True) -> None:
        self._hover_progress = 0.0
        self._outline_radius = outline_radius
        self._outline_on_self = outline_on_self
        self._base_geometry = QRect(self.geometry())

        self._outline_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._outline_anim.setDuration(HOVER_MS)
        self._outline_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._scale_anim = QPropertyAnimation(self, b"geometry", self)
        self._scale_anim.setDuration(HOVER_MS)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # --- Анимируемое свойство: сила обводки 0..1 ---
    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = value
        self._on_hover_progress(value)

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    def _on_hover_progress(self, value: float) -> None:
        """Хук при каждом кадре анимации обводки.

        По умолчанию перерисовывает сам виджет. Если обводку рисует
        не сам виджет, а его ребёнок (например, CoverView у карточек),
        переопределите хук и передайте значение ему.
        """
        if self._outline_on_self:
            self.update()

    # --- Кнопку погасили, пока курсор на ней ---
    def event(self, event) -> bool:
        # Если виджет отключили во время ховера, enter/leave больше не
        # срабатывают и обводка с ростом «залипли» бы навсегда — гасим.
        if (
            event.type() == QEvent.Type.EnabledChange
            and not self.isEnabled()
            and (
                self._hover_progress > 0.0
                or self._scale_anim.state() == QAbstractAnimation.State.Running
            )
        ):
            self._force_hover_off()
        return super().event(event)

    def _force_hover_off(self) -> None:
        """Плавно вернуть элемент в покой (обводка 0, базовый размер)."""
        self._outline_anim.stop()
        self._outline_anim.setStartValue(self._hover_progress)
        self._outline_anim.setEndValue(0.0)
        self._outline_anim.start()

        self._scale_anim.stop()
        self._scale_anim.setStartValue(self.geometry())
        self._scale_anim.setEndValue(QRect(self._base_geometry))
        self._scale_anim.start()

    # --- События мыши ---
    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self.isEnabled():
            self._apply_hover(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self.isEnabled():
            self._apply_hover(False)

    def _apply_hover(self, on: bool) -> None:
        # Обводка
        self._outline_anim.stop()
        self._outline_anim.setStartValue(self._hover_progress)
        self._outline_anim.setEndValue(1.0 if on else 0.0)
        self._outline_anim.start()

        # Размер (вокруг центра). Базовая геометрия — та, что была в покое;
        # она не пересчитывается, если ховер повторился посреди анимации,
        # иначе размер «уплывал» бы с каждым наведением.
        was_running = (
            self._scale_anim.state() == QAbstractAnimation.State.Running
        )
        self._scale_anim.stop()
        if on:
            if not was_running:
                self._base_geometry = QRect(self.geometry())
            base = QRect(self._base_geometry)
            size = base.size() * HOVER_SCALE
            top_left = QPoint(
                base.center().x() - size.width() // 2,
                base.center().y() - size.height() // 2,
            )
            target = QRect(top_left, size)
            self.raise_()  # растущий элемент рисуется поверх соседей
        else:
            target = QRect(self._base_geometry)
        self._scale_anim.setStartValue(self.geometry())
        self._scale_anim.setEndValue(target)
        self._scale_anim.start()

    # --- Отрисовка обводки ---
    def outline_rect(self) -> QRectF:
        """Прямоугольник обводки; по умолчанию — весь виджет."""
        return QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._outline_on_self and self._hover_progress > 0.01:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 255, 255, int(210 * self._hover_progress)))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rect = self.outline_rect()
            painter.drawRoundedRect(
                rect, self._outline_radius, self._outline_radius
            )


class HoverButton(Hoverable, QPushButton):
    """Обычная кнопка со стандартным ховером приложения."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 outline_radius: float = 10.0) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.init_hover(outline_radius)

    # --- Смена текста не должна ломать размер (Task 19, п. 9) ----------
    def setText(self, text: str) -> None:
        """Текст изменился → sizeHint изменился: обновить базу ховера.

        Иначе «уход» курсора возвращает кнопку к СТАРОЙ (узкой)
        геометрии, захваченной при входе: например «Далее →» →
        «Сохранить» — компоновка расширяла кнопку, а затем анимация
        ховера сжимала её обратно, и текст обрезался с обеих сторон.
        """
        super().setText(text)
        QTimer.singleShot(0, self._refresh_base_geometry)

    def _refresh_base_geometry(self) -> None:
        """База ховера = фактическая геометрия после пересчёта layout."""
        was_running = (
            self._scale_anim.state() == QAbstractAnimation.State.Running
        )
        self._scale_anim.stop()
        self._base_geometry = QRect(self.geometry())
        if was_running or (self.underMouse() and self.isEnabled()):
            # Курсор на кнопке — вырасти заново уже от новой базы
            self._apply_hover(True)
