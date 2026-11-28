"""Секция главной страницы: заголовок + горизонтальный ряд карточек.

Ряд перестраивается методом set_cards() — главная страница вызывает
его после каждого изменения базы (создание альбома, оценка и т.д.).
Главная страница определяет число карточек и добавляет плитку
«Смотреть все» секциям с полным списком.
Если карточек нет — приглушённая надпись «Пока пусто».

Ряд прокручивается по горизонтали, когда карточки не помещаются.
Внутренние поля ленты оставляют запас, чтобы карточка при
ховер-увеличении (+10 %) не обрезалась краем viewport.
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.album_card import CARD_HEIGHT
from app.ui.widgets.motion import SmoothScrollArea

CARD_SPACING = 16             # расстояние между карточками в ряду
ROW_HEIGHT = CARD_HEIGHT + 28  # запас под ховер-масштаб и скроллбар
EDGE_PAD = 8                  # запас по краям ленты для ховер-масштаба
HSCROLL_STEP = 240            # пикселей за «щелчок» колеса по горизонтали


class CardRow(SmoothScrollArea):
    """Горизонтальная лента карточек с «умным» колесом мыши (Task 39).

    • вертикальное колесо НЕ застревает над карточками — прокручивает
      страницу (главную/список), как в современных приложениях;
    • Shift+колесо или горизонтальный жест тачпада — плавно листают
      саму ленту;
    • обычная горизонтальная полоса прокрутки остаётся (тонкая).
    """

    def wheelEvent(self, event: QWheelEvent) -> None:
        pixels = event.pixelDelta()
        angle = event.angleDelta()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        delta = pixels if not pixels.isNull() else angle
        horizontal = shift or abs(delta.x()) > abs(delta.y())
        if horizontal and self._scroll_wheel(
            event, self.horizontalScrollBar(), pixels.x() or (pixels.y() if shift else 0),
            angle.x() or (angle.y() if shift else 0), HSCROLL_STEP,
        ):
            return

        if pixels.y() or angle.y():
            self._forward_to_page(event)
            return
        super().wheelEvent(event)

    def _forward_to_page(self, event: QWheelEvent) -> None:
        """Отдать вертикальное колесо ближайшей внешней прокрутке."""
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is None or parent is self:
            event.ignore()
            return
        clone = QWheelEvent(
            QPointF(event.position()),
            QPointF(event.globalPosition()),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
        )
        QApplication.sendEvent(parent.viewport(), clone)
        event.accept()


class Section(QWidget):
    def __init__(self, title: str, cards: list[QWidget] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)

        header = QLabel(title, self)
        header.setObjectName("sectionTitle")
        header.setContentsMargins(EDGE_PAD, 0, 0, 0)  # выравнивание с карточками
        self._layout.addWidget(header)

        self._row: QScrollArea | None = None
        self._empty: QLabel | None = None
        self.set_cards(cards or [])

    # --- Перестройка ряда карточек ---
    def set_cards(self, cards: list[QWidget]) -> None:
        """Заменить карточки секции (старые виджеты удаляются)."""
        # Прежний ряд/подсказку сначала прячем — deleteLater срабатывает
        # в цикле событий, а без hide() виджет дорисовывался бы до удаления
        if self._row is not None:
            self._row.hide()
            self._row.deleteLater()
            self._row = None
        if self._empty is not None:
            self._empty.hide()
            self._empty.deleteLater()
            self._empty = None

        if not cards:
            self._empty = QLabel("Пока пусто", self)
            self._empty.setObjectName("emptyHint")
            self._empty.setContentsMargins(EDGE_PAD, 0, 0, 0)
            self._layout.addWidget(self._empty)
            return

        self._row = self._make_row(cards)
        self._layout.addWidget(self._row)

    def cards(self) -> list[QWidget]:
        """Карточки текущего ряда (для каскадного появления, Task 39)."""
        if self._row is None:
            return []
        inner = self._row.widget()
        layout = inner.layout() if inner is not None else None
        if layout is None:
            return []
        result: list[QWidget] = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                result.append(widget)
        return result

    def _make_row(self, cards: list[QWidget]) -> CardRow:
        """Горизонтальная прокручиваемая лента карточек."""
        row = CardRow(self)
        row.setObjectName("sectionRow")
        row.setFrameShape(CardRow.Shape.NoFrame)
        row.setWidgetResizable(True)
        row.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        row.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row.setFixedHeight(ROW_HEIGHT)

        inner = QWidget(row)
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(EDGE_PAD, EDGE_PAD + 4, EDGE_PAD, 0)
        inner_layout.setSpacing(CARD_SPACING)

        for card in cards:
            inner_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
            # Явный show(): карточки безродные, и добавленные в УЖЕ
            # видимый ряд (refresh при дозагрузке обложек) сами
            # не показываются — главная оставалась бы со старыми
            card.show()
        inner_layout.addStretch(1)  # карточки прижаты к левому краю

        row.setWidget(inner)
        return row
