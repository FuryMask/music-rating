"""Плитка «Смотреть все» — восьмая плитка полной секции главной страницы.

Появляется, когда карточек в сегменте больше семи: в ряд выводятся
первые 7, а эта плитка ведёт на полный список: клик (сигнал clicked)
главная страница превращает в открытие страницы «Смотреть все» —
«Недавно оценённые», «Оценённые альбомы» или «Исполнители»
(см. pages/collection_page.py).

Task 39: плитка получила «живой» указатель — шеврон под подписью,
который при наведении подсвечивается акцентом и сдвигается вправо
за те же 250 мс, что растёт сама плитка. Так край ленты читается
как «дальше есть ещё», без стрелок-эмодзи и лишнего текста.

Ховер — стандарт приложения: белая обводка + рост на 10 % за 250 мс.
"""

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from app.theme import ACCENT, TEXT_MUTED, themed_color
from app.ui.widgets.album_card import CARD_SIZE
from app.ui.widgets.hoverable import Hoverable

TILE_SIZE = CARD_SIZE  # квадратная плитка вровень с обложками карточек
LABEL_BOTTOM_PAD = 26  # подпись выше центра — под ней шеврон


class ViewAllTile(Hoverable, QWidget):
    """Квадратная плитка «Смотреть все»; клик открывает полный список."""

    clicked = Signal()  # клик — главная страница откроет список

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("viewAllTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.label = QLabel("Смотреть все", self)
        self.label.setObjectName("viewAllLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.init_hover(outline_radius=12, outline_on_self=True)

    def sizeHint(self) -> QSize:
        return QSize(TILE_SIZE, TILE_SIZE)

    def minimumSizeHint(self) -> QSize:
        return QSize(TILE_SIZE, TILE_SIZE)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.label.setGeometry(0, 0, self.width(),
                               self.height() - LABEL_BOTTOM_PAD)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон — QSS, обводка — Hoverable
        progress = self._hover_progress
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Цвет шеврона: приглушённый → акцент (как у выбранных элементов)
        muted, accent = themed_color(TEXT_MUTED), themed_color(ACCENT)
        color = QColor(
            round(muted.red() + (accent.red() - muted.red()) * progress),
            round(muted.green() + (accent.green() - muted.green()) * progress),
            round(muted.blue() + (accent.blue() - muted.blue()) * progress),
        )
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        cx = self.width() / 2.0 + 5.0 * progress
        cy = self.height() * 0.5 + 20.0
        arm, head = 4.0, 4.5
        painter.drawLine(QPointF(cx - head, cy - arm),
                         QPointF(cx, cy))
        painter.drawLine(QPointF(cx, cy),
                         QPointF(cx - head, cy + arm))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
