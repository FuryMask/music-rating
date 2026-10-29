"""Секция главной страницы: заголовок + горизонтальный ряд карточек.

Ряд перестраивается методом set_cards() — главная страница вызывает
его после каждого изменения базы (создание альбома, оценка и т.д.).
Сегмент показывает максимум 7 карточек; когда их больше, главной
страницей добавляется 8-я плитка «Смотреть все» (см. view_all_tile).
Если карточек нет — приглушённая надпись «Пока пусто».

Ряд прокручивается по горизонтали, когда карточки не помещаются.
Внутренние поля ленты оставляют запас, чтобы карточка при
ховер-увеличении (+10 %) не обрезалась краем viewport.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.album_card import CARD_HEIGHT

CARD_SPACING = 16             # расстояние между карточками в ряду
ROW_HEIGHT = CARD_HEIGHT + 28  # запас под ховер-масштаб и скроллбар
EDGE_PAD = 8                  # запас по краям ленты для ховер-масштаба


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

    def _make_row(self, cards: list[QWidget]) -> QScrollArea:
        """Горизонтальная прокручиваемая лента карточек."""
        row = QScrollArea(self)
        row.setObjectName("sectionRow")
        row.setFrameShape(QScrollArea.Shape.NoFrame)
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
