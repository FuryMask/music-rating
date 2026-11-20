"""Анимация «падения сверху» — появление содержимого окна и страниц.

По ТЗ: когда главное окно открывается, все обложки, текст и кнопки
ПАДАЮТ СВЕРХУ, начавшись с нулевой прозрачности; длительность —
0.250 секунды. Такие же анимации — на страницах «Смотреть все»
(collection_page) и «Дискография» (artist_detail).

Как это работает (для каждого виджета отдельно):
  • QGraphicsOpacityEffect: прозрачность 0 → 1;
  • позиция: выше конечной на DROP_OFFSET пикселей → конечная
    (виджеты лежат в layout'ах, поэтому во время анимации ничто
    не должно пересчитывать компоновку — длительность короткая,
    конечная позиция восстанавливается явно);
  • easing OutCubic — «падение» замедляется к месту посадки.

Пока идёт анимация, контейнер блокируется для мыши
(WA_TransparentForMouseEvents на общем родителе): иначе ховер,
начавшийся в падении, запомнил бы неверную «базовую геометрию»
(Hoverable) и вернул бы карточку не на место.

Для ОКНА ПРИ СТАРТЕ есть особенность: эффект должен быть применён
ДО показа окна (pre_hide в конструкторе). Если применять эффект
только по showEvent → singleShot(0), первый кадр окна на Windows
успевает нарисоваться ДО применения эффекта — содержимое появляется
сразу целиком и анимация выглядит «неприменённой» (это и видел
пользователь в изначальном окне). Прозрачность, заданная до показа,
гарантированно попадает в самый первый кадр.

Виджеты-цели могут быть пересозданы во время анимации (обновление
главной) — все колбэки проверяют валидность C++-обёртки через
shiboken6.isValid, чтобы анимация не уронила приложение.
"""

import shiboken6
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

DROP_MS = 250      # длительность по ТЗ — 0.250 секунды
DROP_OFFSET = 24   # стартовая высота падения, px
BLOCK_PAD_MS = 60  # запас блокировки мыши после конца анимации


def pre_hide(widgets: list[QWidget]) -> None:
    """Спрятать виджеты ДО показа окна (прозрачность 0).

    Вызывается в конструкторе окна: тогда ПЕРВЫЙ кадр окна (сколько
    бы ни длилась асинхронная возня оконного менеджера) рисуется уже
    прозрачным, и анимация падения видна целиком. run_drop_in потом
    подхватывает эти же эффекты (см. _animate_one).
    """
    for widget in widgets:
        if widget is None or not shiboken6.isValid(widget):
            continue
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        widget._drop_pre_effect = effect  # подхватится в _animate_one


def run_drop_in(widgets: list[QWidget], ms: int = DROP_MS,
                offset: int = DROP_OFFSET,
                block_container: QWidget | None = None,
                stagger: int = 0) -> None:
    """Проиграть «падение сверху» для перечисленных виджетов.

    Виджеты, которых сейчас нет на экране (скрыты/удалены),
    пропускаются. block_container (если задан) на ms + запас
    закрывается от мыши, чтобы ховер не сломал геометрию.

    stagger — каскад (Task 39): следующий виджет стартует на stagger мс
    позже предыдущего. 0 — все одновременно (поведение Task 31, его
    проверяют тесты; каскад используется там, где порядок красив).
    """
    targets = [
        w for w in widgets
        if w is not None and shiboken6.isValid(w) and w.isVisible()
    ]
    if not targets:
        return

    total_ms = ms + max(0, len(targets) - 1) * max(0, stagger)
    if block_container is not None:
        block_container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        QTimer.singleShot(
            total_ms + BLOCK_PAD_MS,
            lambda: _unblock(block_container),
        )

    if stagger <= 0 or len(targets) == 1:
        for widget in targets:
            _animate_one(widget, ms, offset)
        return

    batch = object()
    for widget in targets:
        reset = getattr(widget, "_reset_hover", None)
        if reset is not None:
            reset()
        widget._drop_pending = batch

    for index, widget in enumerate(targets):
        if index == 0:
            _animate_if_visible(widget, ms, offset, batch)
        else:
            QTimer.singleShot(
                index * stagger, widget,
                lambda target=widget: _animate_if_visible(target, ms, offset, batch),
            )


def _animate_if_visible(widget: QWidget, ms: int, offset: int, batch: object) -> None:
    """Отложенный старт каскада: виджет мог исчезнуть/пересоздаться."""
    if widget._drop_pending is batch:
        widget._drop_pending = None
        if widget.isVisible():
            _animate_one(widget, ms, offset)


def _unblock(container: QWidget) -> None:
    if shiboken6.isValid(container):
        container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )


def _animate_one(widget: QWidget, ms: int, offset: int) -> None:
    """Падение одного виджета: прозрачность 0→1 и позиция выше→место."""
    previous = getattr(widget, "_drop_anim", None)
    if previous is not None and previous.state() == QAbstractAnimation.State.Running:
        return
    reset = getattr(widget, "_reset_hover", None)
    if reset is not None:
        reset()
    final = QPoint(widget.pos())

    # Если виджет спрятали ДО показа окна (pre_hide) — эффект уже
    # стоит, прозрачность 0; иначе создаём эффект на месте
    effect = getattr(widget, "_drop_pre_effect", None)
    if effect is None or not shiboken6.isValid(effect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
    widget._drop_pre_effect = None

    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    position = QPoint(final.x(), final.y() - offset)
    widget.move(position)

    def on_step(t: float) -> None:
        nonlocal final, position
        # Виджет/эффект могли быть удалены посреди анимации (быстрый
        # refresh главной, пересоздание карточек) — молча выходим
        if not shiboken6.isValid(widget) or not shiboken6.isValid(effect):
            return
        effect.setOpacity(t)
        if widget.pos() != position:
            final = widget.pos()
        position = QPoint(final.x(), final.y() - int(offset * (1.0 - t)))
        widget.move(position)

    def on_done() -> None:
        if not shiboken6.isValid(widget):
            return
        if shiboken6.isValid(effect):
            widget.setGraphicsEffect(None)  # эффект больше не нужен
        # Возврат на место — через компоновку родителя, а НЕ
        # widget.move(final): если окно ресайзнули ПОКА шла анимация
        # (например, додетал асинхронный maximize Windows), захваченный
        # «финал» устарел — компоновка знает настоящие места
        parent = widget.parentWidget()
        lay = parent.layout() if parent is not None else None
        if lay is not None:
            lay.activate()
        else:
            widget.move(final)

    anim.valueChanged.connect(on_step)
    anim.finished.connect(on_done)
    widget._drop_anim = anim  # удерживаем ссылку (иначе GC убьёт анимацию)
    if previous is not None:
        previous.deleteLater()
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
