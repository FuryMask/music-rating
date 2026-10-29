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
                block_container: QWidget | None = None) -> None:
    """Проиграть «падение сверху» для перечисленных виджетов.

    Виджеты, которых сейчас нет на экране (скрыты/удалены),
    пропускаются. block_container (если задан) на ms + запас
    закрывается от мыши, чтобы ховер не сломал геометрию.
    """
    targets = [
        w for w in widgets
        if w is not None and shiboken6.isValid(w) and w.isVisible()
    ]
    if not targets:
        return

    if block_container is not None:
        block_container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        QTimer.singleShot(
            ms + BLOCK_PAD_MS,
            lambda: _unblock(block_container),
        )

    for widget in targets:
        _animate_one(widget, ms, offset)


def _unblock(container: QWidget) -> None:
    if shiboken6.isValid(container):
        container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )


def _animate_one(widget: QWidget, ms: int, offset: int) -> None:
    """Падение одного виджета: прозрачность 0→1 и позиция выше→место."""
    final = QPoint(widget.pos())

    # Если виджет спрятали ДО показа окна (pre_hide) — эффект уже
    # стоит, прозрачность 0; иначе создаём эффект на месте
    effect = getattr(widget, "_drop_pre_effect", None)
    if effect is None or not shiboken6.isValid(effect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
    widget._drop_pre_effect = None

    widget.move(final.x(), final.y() - offset)

    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def on_step(t: float) -> None:
        if not shiboken6.isValid(widget):
            return
        effect.setOpacity(t)
        widget.move(final.x(), final.y() - int(offset * (1.0 - t)))

    def on_done() -> None:
        if not shiboken6.isValid(widget):
            return
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
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
