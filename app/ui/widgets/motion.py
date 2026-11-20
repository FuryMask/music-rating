"""Примитивы движения — общий «язык анимаций» приложения (Task 39).

Зачем отдельный модуль: анимации в приложении должны ощущаться
ОДНОЙ системой, а не набором случайных эффектов. Здесь собраны:
  • единые длительности и кривые (EASE_OUT / EASE_IN_OUT);
  • animate() — короткая обёртка над QVariantAnimation;
  • fade_in() — проявление виджета через QGraphicsOpacityEffect
    (аккуратно: вложенные эффекты Qt не любит — см. HANDOFF §9);
  • SmoothScrollArea — «инерционное» колесо мыши: прокрутка
    доезжает до цели за 0.18 с, а не прыгает;
  • MUSICRATING_REDUCED_MOTION=1 — режим «меньше движения»: все
    анимации выключаются, интерфейс сразу в конечном состоянии
    (полезно для слабых машин, удалённого доступа и автотестов).
  • Каскад появления живёт в widgets/drop_animation.py (параметр
    stagger) — там же, где «падение» разделов из Task 31.

Все анимации — QVariantAnimation/QPropertyAnimation с родителем-
виджетом: они живут ровно столько, сколько нужно, и не копятся.
"""

from __future__ import annotations

import os
import shiboken6

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QScrollArea, QWidget

from app.ui.widgets.scroll_bar import install_slim_scrollbars

# --- Общие длительности (секунды восприятия, а не «чем быстрее, тем лучше») ---
FAST_MS = 150       # микро-отклик: появление панели поиска
BASE_MS = 320       # базовое движение интерфейса
PAGE_MS = 360       # смена страницы (перекрёстное затухание)
SCROLL_MS = 120
SCROLL_MAX_MS = 180
SCROLL_STEP_PX = 120  # пикселей за щелчок колеса в нативном режиме

EASE_OUT = QEasingCurve.Type.OutCubic


def reduced_motion() -> bool:
    """Выключены ли анимации (доступность/тесты)."""
    return os.environ.get("MUSICRATING_REDUCED_MOTION") == "1"


def smooth_scroll_enabled() -> bool:
    """Плавность колеса включена по умолчанию; значение 0 отключает её."""
    return os.environ.get("MUSICRATING_SMOOTH_SCROLL", "1") != "0"


def animate(parent: QWidget, start, end, ms: int, on_value,
            easing: QEasingCurve.Type = EASE_OUT,
            on_done=None) -> QVariantAnimation:
    """Запустить анимацию числа start→end; on_value(t) зовётся каждый кадр."""
    anim = QVariantAnimation(parent)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setDuration(max(1, ms))
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(on_value)

    def finish() -> None:
        if on_done is not None:
            on_done()
        # Анимации — короткоживущие объекты: не копим их в детях виджета
        anim.deleteLater()

    anim.finished.connect(finish)
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    return anim


def fade_in(widget: QWidget, ms: int = BASE_MS, start: float = 0.0) -> None:
    """Проявить виджет: прозрачность start→1 с эффектом непрозрачности.

    Эффект снимается по завершении — дальше виджет рисуется как обычно.
    Вкладывать такие эффекты (эффект на предке и потомке) нельзя.
    """
    if reduced_motion() or widget is None or not shiboken6.isValid(widget):
        return
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(start)
        widget.setGraphicsEffect(effect)
    else:
        effect.setOpacity(start)

    def apply(value: float) -> None:
        if shiboken6.isValid(effect):
            effect.setOpacity(value)

    def done() -> None:
        if shiboken6.isValid(widget):
            widget.setGraphicsEffect(None)

    animate(widget, start, 1.0, ms, apply, on_done=done)


class SmoothScrollArea(QScrollArea):
    """Короткое сглаживание колеса; пиксельные жесты тачпада идут 1:1."""

    WHEEL_STEP = SCROLL_STEP_PX

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        install_slim_scrollbars(self)
        self._scroll_bar = self.verticalScrollBar()
        self._target = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(EASE_OUT)
        self._anim.valueChanged.connect(self._apply_scroll)
        for bar in (self.verticalScrollBar(), self.horizontalScrollBar()):
            bar.setSingleStep(SCROLL_STEP_PX // 3)
            bar.actionTriggered.connect(self._anim.stop)
            bar.rangeChanged.connect(self._anim.stop)

    def _apply_scroll(self, value: float) -> None:
        self._scroll_bar.setValue(round(value))

    def _scroll_wheel(self, event, bar, pixels: int, angle: int, step: int) -> bool:
        if bar.maximum() <= bar.minimum() or not (pixels or angle):
            return False
        if pixels or reduced_motion() or not smooth_scroll_enabled():
            self._anim.stop()
            change = pixels if pixels else angle / 120.0 * step
            bar.setValue(round(bar.value() - change))
            event.accept()
            return True

        current = bar.value()
        running = self._scroll_bar is bar and (
            self._anim.state() == QAbstractAnimation.State.Running
        )
        distance = -angle / 120.0 * step
        base = self._target if running and (self._target - current) * distance > 0 else current
        target = max(bar.minimum(), min(bar.maximum(), base + distance))
        self._anim.stop()
        if abs(target - current) >= 1:
            self._scroll_bar = bar
            self._target = target
            self._anim.blockSignals(True)
            self._anim.setStartValue(float(current))
            self._anim.setEndValue(float(target))
            self._anim.setDuration(min(SCROLL_MAX_MS, SCROLL_MS + round(abs(target - current) * 0.15)))
            self._anim.blockSignals(False)
            self._anim.start()
        event.accept()
        return True

    def wheelEvent(self, event) -> None:
        pixels = event.pixelDelta()
        angle = event.angleDelta()
        delta = pixels if not pixels.isNull() else angle
        if abs(delta.x()) > abs(delta.y()):
            handled = self._scroll_wheel(event, self.horizontalScrollBar(),
                                         pixels.x(), angle.x(), self.WHEEL_STEP)
        else:
            handled = self._scroll_wheel(event, self.verticalScrollBar(),
                                         pixels.y(), angle.y(), self.WHEEL_STEP)
        if not handled:
            super().wheelEvent(event)

    def hideEvent(self, event) -> None:
        self._anim.stop()
        super().hideEvent(event)
