"""Hover, press and ripple feedback for Qt cards and buttons."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    Property,
    QPropertyAnimation,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QStyleOptionButton, QWidget

from app.ui.widgets import motion

HOVER_MS = 450       # длительность анимаций ховера (медленно и мягко)
HOVER_SCALE = 1.10   # увеличение при наведении (+10 %)
PRESS_SCALE = 0.965  # сжатие при нажатии (от текущего размера)
PRESS_MS = 120       # сжатие
RELEASE_MS = 220     # возврат
RIPPLE_MS = 700      # волна от клика
HOVER_WATCH_MS = 110 # как часто проверять, что курсор всё ещё на элементе
HOVER_RETRY_MS = 16  # шаг ожидания раскладки перед ховером
HOVER_RETRIES = 12   # сколько раз ждать раскладку (макс. ~200 мс)
# Размер свежего QWidget ДО раскладки (в т.ч. без родителя)
UNLAID_WIDGET_SIZE = QSize(640, 480)


class Hoverable:
    """Обратная связь при наведении и нажатии."""

    _paint_scale_only = False

    def init_hover(self, outline_radius: float = 8.0,
                   outline_on_self: bool = True) -> None:
        self._hover_progress = 0.0
        self._outline_radius = outline_radius
        self._outline_on_self = outline_on_self
        self._base_geometry = QRect()
        self._scaled_geometry = QRect()
        self._visual_scale = 1.0 / HOVER_SCALE
        self._hovered = False
        self._pressed = False
        self._hover_pending = False
        self._ripple_enabled = False
        self._ripple_t = 0.0
        self._ripple_pos = QPointF(0.0, 0.0)

        self._outline_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._outline_anim.setDuration(HOVER_MS)
        self._outline_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._scale_anim = QVariantAnimation(self)
        self._scale_anim.valueChanged.connect(self._apply_scale_frame)
        self._scale_anim.setDuration(HOVER_MS)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Сторож: Qt не всегда присылает Leave, если элемент «уехал»
        # из-под курсора (прокрутка) или курсор ушёл очень быстро
        self._hover_watch = QTimer(self)
        self._hover_watch.setInterval(HOVER_WATCH_MS)
        self._hover_watch.timeout.connect(self._check_hover_alive)

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

    def event(self, event) -> bool:
        if hasattr(self, "_scale_anim") and (
            event.type() == QEvent.Type.UngrabMouse
            or (event.type() == QEvent.Type.EnabledChange and not self.isEnabled())
        ):
            if self._hovered or self._pressed or self._hover_pending:
                self._force_hover_off()
        return super().event(event)

    def _force_hover_off(self) -> None:
        self._hover_pending = False
        self._pressed = False
        self._apply_hover(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if not self.isEnabled() or self._entrance_running():
            return
        # Повторный Enter по уже наведённому элементу — не пересчитываем
        # базу, просто доводим анимацию до цели
        if self._hovered or self._pressed:
            self._apply_hover(True)
            return
        if not self._rest_size_ready():
            self._hover_pending = True
            QTimer.singleShot(0, self, lambda: self._request_hover(0))
            return
        self._apply_hover(True)

    def _request_hover(self, attempt: int) -> None:
        """Отложенный вход: ждём, пока layout задаст реальный размер."""
        if not self._hover_pending:
            return
        if self._entrance_running() or not self.isVisible() or attempt >= HOVER_RETRIES:
            self._hover_pending = False
            return
        if self._rest_size_ready():
            self._hover_pending = False
            self._apply_hover(True)
            return
        QTimer.singleShot(
            HOVER_RETRY_MS, self, lambda: self._request_hover(attempt + 1)
        )

    def _rest_size_ready(self) -> bool:
        """Похоже ли, что layout уже разложил элемент?

        Свежий QWidget имеет размер 640×480; если высота заметно больше
        sizeHint, это ещё не раскладка (карточка, плитка, кнопка).
        """
        hint = self.sizeHint()
        if hint.isEmpty() or hint.height() <= 0:
            return True
        # Кнопки-иконки сайдбара/«назад» имеют ФИКСИРОВАННЫЙ размер
        # (40×40), а sizeHint у них меньше (текст пуст) — это норма.
        if self._paint_scale_only:
            return True
        # До раскладки QWidget имеет размер по умолчанию 640×480 —
        # принимать его за базу нельзя (карточка раздувается)
        if self.size() == UNLAID_WIDGET_SIZE \
                and hint != UNLAID_WIDGET_SIZE:
            return False
        return True

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover_pending = False
        if self.isEnabled():
            self._apply_hover(False)

    def _entrance_running(self) -> bool:
        """Идёт ли по этому элементу анимация появления (drop)?"""
        anim = getattr(self, "_drop_anim", None)
        return getattr(self, "_drop_pending", None) is not None or (
            anim is not None
            and anim.state() == QAbstractAnimation.State.Running
        )

    def mousePressEvent(self, event) -> None:
        # «Пружина» нажатия: чуть сжимаемся и отпускаем на release
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.isEnabled()
            and self.isVisible()
            and not self._entrance_running()
            and not motion.reduced_motion()
        ):
            self._capture_base()
            self._pressed = True
            self._animate_scale(PRESS_MS)
            if self._ripple_enabled:
                self._start_ripple(event.position())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self._animate_scale(RELEASE_MS)
        super().mouseReleaseEvent(event)

    def _apply_hover(self, on: bool) -> None:
        if on:
            self._capture_base()
            if not self._paint_scale_only:
                self.raise_()

        self._hovered = on
        # Обводка
        self._outline_anim.stop()
        if motion.reduced_motion():
            self._set_hover_progress(1.0 if on else 0.0)
        else:
            self._outline_anim.setStartValue(self._hover_progress)
            self._outline_anim.setEndValue(1.0 if on else 0.0)
            self._outline_anim.start()

        self._animate_scale(HOVER_MS)
        if on:
            # Сторож имеет смысл только для НАСТОЯЩЕГО наведения:
            # в момент входа курсор действительно внутри элемента.
            # Синтетические Enter-события (автотесты) курсор не
            # двигают — их не сторожим, чтобы не гасить ховер.
            inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
            if inside:
                self._hover_watch.start()
        else:
            self._hover_watch.stop()

    def _capture_base(self) -> None:
        if not self._paint_scale_only and self.geometry() != self._scaled_geometry:
            self._base_geometry = self.geometry()
            self._scaled_geometry = self.geometry()

    def _scale_active(self) -> bool:
        return self._hovered

    def _target_scale(self) -> float:
        factor = HOVER_SCALE if self._scale_active() and not motion.reduced_motion() else 1.0
        return factor * PRESS_SCALE if self._pressed else factor

    def _target_rect(self) -> QRect:
        base = self._base_geometry
        size = (base.size() * self._target_scale()).expandedTo(
            self.minimumSize()
        ).boundedTo(self.maximumSize())
        return QRect(base.x() + round((base.width() - size.width()) / 2),
                     base.y() + round((base.height() - size.height()) / 2),
                     size.width(), size.height())

    def _check_hover_alive(self) -> None:
        target = QApplication.widgetAt(QCursor.pos())
        if not self.isVisible() or not self.isEnabled() or (
            target is not self and (target is None or not self.isAncestorOf(target))
        ):
            self._force_hover_off()

    def _apply_scale_frame(self, value) -> None:
        if self._paint_scale_only:
            self._visual_scale = float(value)
            self.update()
        elif self.geometry() != self._scaled_geometry:
            self._capture_base()
            self._animate_scale(HOVER_MS)
        else:
            self._scaled_geometry = QRect(value)
            self.setGeometry(value)

    def _animate_scale(self, ms: int) -> None:
        self._scale_anim.stop()
        if self._paint_scale_only:
            current = self._visual_scale
            target = self._target_scale() / HOVER_SCALE
        else:
            if self._base_geometry.isEmpty():
                return
            self._capture_base()
            current = self.geometry()
            target = self._target_rect()
        if current == target:
            return
        if motion.reduced_motion():
            self._apply_scale_frame(target)
            return
        self._scale_anim.blockSignals(True)
        self._scale_anim.setDuration(ms)
        self._scale_anim.setStartValue(current)
        self._scale_anim.setEndValue(target)
        self._scale_anim.blockSignals(False)
        self._scale_anim.start()

    # --- Волна от клика (ripple) ---
    def _start_ripple(self, pos: QPointF) -> None:
        self._ripple_pos = QPointF(pos)
        self._ripple_t = 0.0001
        old = getattr(self, "_ripple_anim", None)
        if old is not None:
            old.stop()
            old.deleteLater()

        def frame(value: float) -> None:
            self._ripple_t = float(value)
            self.update()

        def done() -> None:
            self._ripple_t = 0.0
            self._ripple_anim = None
            self.update()

        self._ripple_anim = motion.animate(
            self, 0.0, 1.0, RIPPLE_MS, frame, motion.EASE_OUT, done
        )

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._reset_hover()
        self._drop_pending = None

    def _reset_hover(self) -> None:
        self._hover_watch.stop()
        self._hover_pending = False
        self._hovered = False
        self._pressed = False
        self._scale_anim.stop()
        self._outline_anim.stop()
        self._set_hover_progress(0.0)
        ripple = getattr(self, "_ripple_anim", None)
        if ripple is not None:
            ripple.stop()
            ripple.deleteLater()
            self._ripple_anim = None
            self._ripple_t = 0.0
        if self._paint_scale_only:
            self._visual_scale = self._target_scale() / HOVER_SCALE
            self.update()
        elif not self._base_geometry.isEmpty() and self.geometry() == self._scaled_geometry:
            self.setGeometry(self._base_geometry)
        self._base_geometry = QRect()
        self._scaled_geometry = QRect()

    def _paint_ripple(self, painter: QPainter) -> None:
        if self._ripple_t <= 0.0 or self._ripple_t >= 1.0:
            return
        t = self._ripple_t
        # Радиус растёт быстро в начале и замедляется к концу
        eased = 1.0 - (1.0 - t) ** 3
        radius = max(self.width(), self.height()) * 0.95 * eased
        alpha = int(62 * (1.0 - t) * (1.0 - t))
        if radius <= 0.5 or alpha <= 0:
            return
        centre = QPointF(self._ripple_pos)
        gradient = QRadialGradient(centre, radius)
        gradient.setColorAt(0.0, QColor(255, 255, 255, alpha))
        gradient.setColorAt(0.55, QColor(255, 255, 255, int(alpha * 0.55)))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            self._outline_radius, self._outline_radius,
        )
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(centre, radius, radius)
        painter.restore()

    # --- Отрисовка обводки ---
    def outline_rect(self) -> QRectF:
        """Прямоугольник обводки; по умолчанию — весь виджет."""
        return QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_feedback(QPainter(self))

    def _paint_feedback(self, painter: QPainter) -> None:
        if self._outline_on_self and self._hover_progress > 0.01:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 255, 255, int(210 * self._hover_progress)))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rect = self.outline_rect()
            painter.drawRoundedRect(
                rect, self._outline_radius, self._outline_radius
            )
        if self._ripple_enabled:
            self._paint_ripple(painter)


class HoverButton(Hoverable, QPushButton):
    """Кнопка масштабирует отрисовку внутри неизменной области клика."""

    _paint_scale_only = True

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 outline_radius: float = 10.0) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.init_hover(outline_radius)
        self._ripple_enabled = True

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        center = QRectF(self.rect()).center()
        painter.translate(center)
        painter.scale(self._visual_scale, self._visual_scale)
        painter.translate(-center)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        self._paint_feedback(painter)
