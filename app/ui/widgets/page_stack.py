"""QStackedWidget с перекрёстным затуханием при смене страницы.

Как это устроено (важно для стабильности):
  • перед переключением со СТАРОЙ страницы снимается снимок (grab) —
    он рисуется поверх стека и плавно гаснет, пока под ним уже
    показана НОВАЯ страница;
  • снимок — обычный QWidget, который сам рисует pixmap с меняющейся
    прозрачностью. QGraphicsOpacityEffect НЕ используется: страницы
    содержат карточки со своими эффектами (анимация «падения»),
    вложенные эффекты Qt конфликтуют (см. HANDOFF §9);
  • снимок закрыт от мыши (WA_TransparentForMouseEvents) — клик
    сразу попадает на новую страницу;
  • направление: вперёд — снимок уезжает влево, назад — вправо
    (глубина «вперёд/назад», как в нативных приложениях).

При reduced-motion, скрытом окне и переключении в ту же страницу
анимации нет — сразу обычный setCurrentWidget.
"""

from __future__ import annotations

import os

import shiboken6

from PySide6.QtCore import QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QStackedWidget, QWidget

from app.theme import BG_MAIN, themed_color
from app.ui.widgets import motion

SHIFT_PX = 18   # насколько снимок «уезжает» за время затухания


def page_fade_enabled() -> bool:
    """Включено ли затухание при смене страниц (по умолчанию ВЫКЛ).

    Почему по умолчанию выключено: для затухания нужен снимок прежней
    страницы (grab), а он для главной стоит ~26 мс — заметный рывок
    ровно в момент клика. Плюс сама анимация прячет новую страницу на
    время затухания. Переключение без анимации занимает ~10–15 мс и
    ощущается мгновенным. Включить: MUSICRATING_PAGE_FADE=1.
    """
    return os.environ.get("MUSICRATING_PAGE_FADE") == "1"


class _PageSnapshot(QWidget):
    """Снимок прежней страницы, плавно гаснущий поверх стека."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("pageSnapshot")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # НЕПРОЗРАЧНЫЙ снимок: рисуем фон + гаснущую страницу сами.
        # Полупрозрачный дочерний виджет заставлял Qt перерисовывать
        # страницу под ним на каждом кадре (замер: 15–20 мс/кадр,
        # «лаг» при переключении). Непрозрачный — только себя.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._pix: QPixmap | None = None
        self._alpha = 0.0
        self._shift = 0.0
        self.hide()

    def start(self, pixmap: QPixmap, shift: int) -> None:
        self._pix = pixmap
        self._alpha = 1.0
        self._shift = float(shift)
        self.setGeometry(self.parentWidget().contentsRect())
        self.show()
        self.raise_()
        self.update()

    def set_frame(self, alpha: float, shift: float) -> None:
        self._alpha = max(0.0, min(1.0, alpha))
        self._shift = shift
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), themed_color(BG_MAIN))
        if self._pix is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self._alpha)
        painter.drawPixmap(QPoint(int(self._shift), 0), self._pix)


class AnimatedStackedWidget(QStackedWidget):
    """Стек страниц рабочей зоны с перекрёстным затуханием."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = _PageSnapshot(self)
        self._anim: QVariantAnimation | None = None
        # Направление «вперёд» (+1) / «назад» (-1) для следующего перехода
        self._direction = 1

    # --- Публичное API ---
    def set_direction(self, direction: int) -> None:
        """Задать направление следующего перехода (+1 вперёд, -1 назад)."""
        self._direction = 1 if direction >= 0 else -1

    def setCurrentWidget(self, widget: QWidget, direction: int | None = None):
        """Переключить страницу; старая растворяется снимком.

        direction — разовое указание для ЭТОГО перехода; по умолчанию
        берётся текущее направление стека, после перехода сбрасывается
        на «вперёд» (чтобы «назад» не прилипало к следующим открытиям).
        """
        previous = self.currentWidget()
        chosen = self._direction if direction is None else (
            1 if direction >= 0 else -1
        )
        self._direction = 1
        # По умолчанию — мгновенное переключение: без grab прежней
        # страницы и без 0.36 с затухания (Task 45, «прогруз страниц»)
        if not page_fade_enabled() or not self._can_animate(previous, widget):
            return super().setCurrentWidget(widget)

        snapshot = previous.grab()
        result = super().setCurrentWidget(widget)
        self._play(snapshot, chosen)
        return result

    # --- Внутреннее ---
    def _can_animate(self, previous: QWidget | None,
                     widget: QWidget | None) -> bool:
        return bool(
            previous is not None
            and widget is not None
            and previous is not widget
            and self.isVisible()
            and previous.isVisible()
            and self.width() > 4
            and self.height() > 4
            and not motion.reduced_motion()
        )

    def _play(self, snapshot: QPixmap, direction: int) -> None:
        shift = SHIFT_PX * (-1 if direction >= 0 else 1)
        self._snapshot.start(snapshot, 0)

        def frame(value: float) -> None:
            if not shiboken6.isValid(self._snapshot):
                return
            # Гаснет по OutCubic (кривая задана у анимации), сдвиг — линейно
            self._snapshot.set_frame(1.0 - value, shift * value)

        def done() -> None:
            self._anim = None
            if shiboken6.isValid(self._snapshot):
                self._snapshot.hide()
                self._snapshot._pix = None

        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self._anim = motion.animate(
            self, 0.0, 1.0, motion.PAGE_MS, frame, on_done=done
        )

    # --- События ---
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._anim is not None:
            # Окно изменило размер посреди перехода: снимок устарел
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        if shiboken6.isValid(self._snapshot):
            self._snapshot.hide()
            self._snapshot.setGeometry(self.contentsRect())
