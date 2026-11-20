"""DarkComboBox — выпадающий список со стрелкой, нарисованной вручную.

Почему стрелка не через QSS: известный трюк «width:0 + прозрачные
боковые границы + цветная верхняя» в Qt рисуется ПРОСТО ПРЯМОУГОЛЬНИКОМ
(QStyleSheetStyle заливает весь прямоугольник субконтрола цветом
верхней границы) — воспроизводится на разных стилях и версиях Qt.
Поэтому стрелка рисуется QPainter-ом в paintEvent, а субконтрол
::down-arrow в QSS обнулён, чтобы стиль не рисовал свой вариант.
"""

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import QComboBox

from app.theme import BG_CARD, BORDER, themed_color
from app.ui.widgets.scroll_bar import install_slim_scrollbars

DROPDOWN_WIDTH = 28     # ширина зоны стрелки (синхронно с QSS ::drop-down)
ARROW_COLOR = "#9a9a9a"
ARROW_COLOR_HOVER = "#c9c9c9"

POPUP_RADIUS = 11


class _RoundedPopup(QObject):
    def eventFilter(self, popup, event) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            self.refresh(popup)
        if event.type() == QEvent.Type.Paint and popup.objectName() == "comboPopup":
            painter = QPainter(popup)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(themed_color(BORDER), 1))
            painter.setBrush(themed_color(BG_CARD))
            bounds = QRectF(popup.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(bounds, POPUP_RADIUS, POPUP_RADIUS)
            return True
        return False

    @staticmethod
    def refresh(popup) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(popup.rect()), POPUP_RADIUS, POPUP_RADIUS)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))


def round_popup(popup) -> None:
    if popup.property("roundedPopup") is None:
        popup.setProperty("roundedPopup", True)
        popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        popup.installEventFilter(_RoundedPopup(popup))
    _RoundedPopup.refresh(popup)


def style_completion_popup(completer) -> None:
    popup = completer.popup()
    popup.setObjectName("completionList")
    install_slim_scrollbars(popup)
    round_popup(popup)


class DarkComboBox(QComboBox):
    """QComboBox в тёмной теме со своей треугольной стрелкой."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        install_slim_scrollbars(self.view())

    def showPopup(self) -> None:
        popup = self.view().window()
        popup.setObjectName("comboPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        round_popup(popup)
        if popup.layout() is not None:
            popup.layout().setContentsMargins(5, 5, 5, 5)
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # поле, рамка, текст из QSS

        cx = self.width() - DROPDOWN_WIDTH / 2
        cy = self.height() / 2
        half_w, half_h = 4.5, 2.25   # половины ширины/высоты треугольника

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 0))
        color = ARROW_COLOR_HOVER if self.underMouse() else ARROW_COLOR
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - half_w, cy - half_h),   # левый верх
            QPointF(cx + half_w, cy - half_h),   # правый верх
            QPointF(cx, cy + half_h),            # низ (острие вниз)
        ]))

