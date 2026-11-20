"""Всплывающие уведомления (тосты) — замена строк-статусов в окнах.

Вид уведомления (пользовательское ТЗ):
  ┌────────────────────────────────┐
  │ (✓)  База успешно импортирована│   иконка: зелёная галочка /
  │                                │   красный крестик перед текстом
  │ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░ │   прогресс: полоска снизу
  └────────────────────────────────┘   медленно «уходит», цвет — по
                                     характеру уведомления (успех /
                                     ошибка).

  • небольшое окошко со скруглёнными краями;
  • сверху по центру главного окна;
  • клик по тосту закрывает его сразу;
  • несколько уведомлений ложатся «стопкой карт в колоде»:
    новое — поверх, старые выглядывают снизу; максимум 3 —
    самое старое закрывается сразу при появлении четвёртого.

Каждый тост — отдельное безрамочное окно (Qt.ToolTip) поверх главного:
клики в самом окне не блокируются. Вся отрисовка — в paintEvent
(никаких QGraphics-эффектов: прозрачность меняется прямо в отрисовке),
анимации — QVariantAnimation.

API: notify(widget, text, kind) — виджет любой иерархии окна;
менеджер находится по главному окну (widget.window()).
Для тестов: MainWindow хранит менеджер в self.toasts, у тоста
читаются .text/.kind, менеджер держит .active (новые — в начало).
"""

from weakref import WeakKeyDictionary

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.theme import BG_CARD, BORDER, RATING_GREEN, RATING_RED, TEXT, themed_color

KIND_SUCCESS = "success"
KIND_ERROR = "error"

TOAST_W = 360          # ширина тоста
RADIUS = 14            # скругление углов карточки
PAD = 14               # поля слева/справа
TOP_PAD = 18           # поле сверху в ВЫСОТЕ карточки
TEXT_TOP_PAD = 13      # откуда рисуется текст с иконкой (чуть выше
                       # середины — пользовательская правка)
BOTTOM_PAD = 18        # поле снизу (над прогресс-полосой)
BAR_H = 3              # высота прогресс-полоски
BAR_PAD = 10           # отступ полоски от краёв карточки
MIN_H = 58             # минимальная высота тоста
ICON_SIZE = 22         # диаметр кружка иконки
ICON_GAP = 10          # просвет между иконкой и текстом

TOAST_MS = 3500        # полное время жизни (полоска за это время уходит)
FADE_IN_MS = 220       # появление: сдвиг сверху + проявление
FADE_OUT_MS = 280      # исчезновение
SLIDE_IN = 14          # стартовый сдвиг появления сверху, px
MAX_STACK = 3          # максимум тостов в «колоде»
OVERLAP = 10           # сколько верха старого тоста накрыто новым
                       # (меньше TEXT_TOP_PAD — иначе «стопка» прячет
                       # текст тоста из-под верхнего)
TOP_GAP = 64           # отступ стопки от верхней границы окна


def _kind_color(kind: str) -> QColor:
    """Цвет характера уведомления: успех — зелёный, ошибка — красный."""
    return QColor(RATING_GREEN if kind == KIND_SUCCESS else RATING_RED)


class Toast(QWidget):
    """Одно всплывающее уведомление (самостоятельное окошко)."""

    def __init__(self, text: str, kind: str, manager: "ToastManager",
                 parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.text = text
        self.kind = kind
        self._manager = manager
        self._color = _kind_color(kind)

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(TOAST_W)

        self._alpha = 0.0          # 0..1 — общая прозрачность карточки
        self._progress = 1.0       # 1..0 — остаток полоски (уходит слева)
        self._closing = False
        self._target = QPoint(0, 0)

        # Расчёт высоты: текст переносится на ширину после иконки
        text_w = TOAST_W - PAD * 2 - ICON_SIZE - ICON_GAP
        rect = QFontMetrics(self.font()).boundingRect(
            0, 0, text_w, 10000,
            Qt.TextFlag.TextWordWrap, text,
        )
        self._text_rect_h = rect.height()
        self.setFixedHeight(
            max(MIN_H, TEXT_TOP_PAD + self._text_rect_h + BOTTOM_PAD + BAR_H)
        )

        # Жизнь: полоска равномерно уходит за TOAST_MS
        self._life = QVariantAnimation(self)
        self._life.setStartValue(0.0)
        self._life.setEndValue(1.0)
        self._life.setDuration(TOAST_MS)
        self._life.valueChanged.connect(self._on_life)
        self._life.finished.connect(self.dismiss)

        # Появление: сверху вниз + проявление
        self._appear = QVariantAnimation(self)
        self._appear.setStartValue(0.0)
        self._appear.setEndValue(1.0)
        self._appear.setDuration(FADE_IN_MS)
        self._appear.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._appear.valueChanged.connect(self._on_appear)

        # Исчезновение
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setDuration(FADE_OUT_MS)
        self._fade.valueChanged.connect(self._on_fade)
        self._fade.finished.connect(self._finish_close)

        # Плавный переезд при пересборке стопки (точки храним сами:
        # QVariantAnimation ненадёжно интерполирует QPoint)
        self._slide = QVariantAnimation(self)
        self._slide.setStartValue(0.0)
        self._slide.setEndValue(1.0)
        self._slide.setDuration(FADE_IN_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.valueChanged.connect(self._on_slide)
        self._slide_from = QPoint(0, 0)

    # --- Публичное -----------------------------------------------------------
    @property
    def is_closing(self) -> bool:
        return self._closing

    def open_at(self, pos: QPoint) -> None:
        """Показать: цель = pos, старт — чуть выше и прозрачным."""
        self._target = pos
        self._slide.stop()
        self.move(pos.x(), pos.y() - SLIDE_IN)
        self.show()
        self.raise_()
        self._life.start()
        self._appear.start()

    def move_to(self, pos: QPoint) -> None:
        """Плавно переехать на новую позицию в стопке."""
        if self.pos() == pos:
            return
        self._target = QPoint(pos)
        self._slide.stop()
        self._slide_from = QPoint(self.pos())
        self._slide.start()

    def jump_to(self, pos: QPoint) -> None:
        """Мгновенно переместиться (окно двигают/меняют размер):
        новая цель запоминается, чтобы идущие анимации сходились
        уже к ней."""
        self._target = QPoint(pos)
        self._slide.stop()
        self.move(pos)

    def dismiss(self) -> None:
        """Закрыть тост (клик, конец времени или вытеснение)."""
        if self._closing:
            return
        self._closing = True
        self._life.stop()
        self._appear.stop()
        self._slide.stop()
        self._fade.start()

    # --- Анимации ------------------------------------------------------------
    def _on_life(self, t: float) -> None:
        self._progress = 1.0 - t
        self.update()

    def _on_appear(self, t: float) -> None:
        self._alpha = t
        self.move(
            self._target.x(),
            self._target.y() - int(SLIDE_IN * (1.0 - t)),
        )
        self.update()

    def _on_fade(self, t: float) -> None:
        self._alpha = 1.0 - t
        self.update()

    def _on_slide(self, t: float) -> None:
        start = self._slide_from
        end = self._target
        self.move(
            start.x() + int((end.x() - start.x()) * t),
            start.y() + int((end.y() - start.y()) * t),
        )

    def _finish_close(self) -> None:
        self.hide()
        self._manager.remove(self)
        self.deleteLater()

    # --- События -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        self.dismiss()
        event.accept()

    # --- Отрисовка -----------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._alpha)

        # Карточка со скруглёнными краями
        card = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        painter.setPen(QPen(themed_color(BORDER), 1))
        painter.setBrush(themed_color(BG_CARD))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

        # Иконка: цветной кружок с галочкой/крестиком перед текстом
        icon_cx = PAD + ICON_SIZE / 2.0
        content_h = max(self._text_rect_h, ICON_SIZE)
        icon_cy = (TEXT_TOP_PAD + (content_h - ICON_SIZE) / 2.0
                   + ICON_SIZE / 2.0)
        center = QPointF(icon_cx, icon_cy)
        halo = QColor(self._color)
        halo.setAlpha(int(38 * self._alpha))
        painter.setBrush(halo)
        painter.drawEllipse(center, ICON_SIZE / 2.0, ICON_SIZE / 2.0)

        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if self.kind == KIND_SUCCESS:
            # Галочка
            p1 = QPointF(icon_cx - 5.0, icon_cy + 0.5)
            p2 = QPointF(icon_cx - 1.5, icon_cy + 4.0)
            p3 = QPointF(icon_cx + 5.0, icon_cy - 3.5)
            painter.drawLine(p1, p2)
            painter.drawLine(p2, p3)
        else:
            # Крестик
            a = 4.5
            painter.drawLine(
                QPointF(icon_cx - a, icon_cy - a),
                QPointF(icon_cx + a, icon_cy + a),
            )
            painter.drawLine(
                QPointF(icon_cx - a, icon_cy + a),
                QPointF(icon_cx + a, icon_cy - a),
            )

        # Текст (перенос слов)
        text_rect = QRectF(
            PAD + ICON_SIZE + ICON_GAP, TEXT_TOP_PAD,
            TOAST_W - PAD * 2 - ICON_SIZE - ICON_GAP,
            self._text_rect_h + 4,
        )
        painter.setPen(themed_color(TEXT))
        painter.drawText(
            text_rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter,
            self.text,
        )

        # Прогресс-полоска: остаток цвета характера, «сход» — серым
        bar_y = self.height() - BAR_PAD - BAR_H
        bar_w = self.width() - BAR_PAD * 2
        track = QRectF(BAR_PAD, bar_y, bar_w, BAR_H)
        track_path = QPainterPath()
        track_path.addRoundedRect(track, BAR_H / 2, BAR_H / 2)
        painter.setBrush(QColor("#2e2e2e"))
        painter.drawPath(track_path)
        if self._progress > 0.0:
            fill_w = max(BAR_H, bar_w * self._progress)
            fill = QRectF(BAR_PAD, bar_y, fill_w, BAR_H)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill, BAR_H / 2, BAR_H / 2)
            painter.setBrush(self._color)
            painter.drawPath(fill_path)


class ToastManager(QObject):
    """Стопка тостов одного главного окна («колода», максимум 3)."""

    def __init__(self, window: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent or window)
        self._window = window
        self._toasts: list[Toast] = []   # [0] — самый новый
        window.installEventFilter(self)
        # Регистрация: notify() находит ЭТОТ же менеджер по окну —
        # MainWindow.toasts и менеджер notify() не должны расходиться
        existing = _MANAGERS.get(window)
        if existing is not self:
            if existing is not None:
                existing._window.removeEventFilter(existing)
            _MANAGERS[window] = self

    # --- Публичное -----------------------------------------------------------
    @property
    def active(self) -> list[Toast]:
        """Активные тосты; [0] — самый новый (верх «колоды»)."""
        return list(self._toasts)

    def show(self, text: str, kind: str = KIND_SUCCESS) -> Toast:
        """Показать уведомление; лишние старые вытесняются."""
        toast = Toast(text, kind, self, self._window)
        self._toasts.insert(0, toast)
        # Максимум 3: всё, что глубже, закрывается сразу
        for old in self._toasts[MAX_STACK:]:
            old.dismiss()
        self._relayout()
        return toast

    def remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._relayout()

    def clear(self) -> None:
        """Закрыть все тосты (используется тестами)."""
        for toast in list(self._toasts):
            toast.dismiss()

    # --- Геометрия стопки ------------------------------------------------------
    def _slot_positions(self) -> list[QPoint]:
        """Глобальные позиции слотов: новое — поверх, старые снизу."""
        origin = self._window.mapToGlobal(
            QPoint(
                (self._window.width() - TOAST_W) // 2,
                TOP_GAP,
            )
        )
        positions: list[QPoint] = []
        y = origin.y()
        for toast in self._toasts:
            positions.append(QPoint(origin.x(), y))
            y += toast.height() - OVERLAP
        return positions

    def _relayout(self) -> None:
        for toast, pos in zip(self._toasts, self._slot_positions()):
            if not toast.isVisible():
                toast.open_at(pos)
            else:
                toast.move_to(pos)
            toast.raise_()

    # --- Движение окна: стопка следует за ним ---------------------------------
    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() in (
            QEvent.Type.Move, QEvent.Type.Resize,
        ):
            for toast, pos in zip(self._toasts, self._slot_positions()):
                toast.jump_to(pos)
        return False


_MANAGERS: WeakKeyDictionary = WeakKeyDictionary()


def manager_for(window: QWidget) -> ToastManager:
    """Менеджер тостов для главного окна (создаётся один раз)."""
    mgr = _MANAGERS.get(window)
    if mgr is None:
        mgr = ToastManager(window)
        _MANAGERS[window] = mgr
    return mgr


def notify(widget: QWidget, text: str,
           kind: str = KIND_SUCCESS) -> Toast | None:
    """Показать тост над главным окном, которому принадлежит widget."""
    window = widget.window()
    if window is None:
        return None
    return manager_for(window).show(text, kind)
