"""Подтверждение выхода из создания альбома («Отмена»/Esc в мастере).

По ТЗ: выход из создания альбома требует предупреждения — случайное
нажатие не должно молча выбрасывать пользователя с потерей введённых
данных. Открывается ТОЛЬКО когда в мастере что-то введено (решение
принимает create_album._request_exit).

Стиль — как у остальных внутриприложных окон (см.
dialogs/delete_confirm_dialog.py): блюр-фон мастера + подъём карточки
из низа с проявлением. «Продолжить создание» (primary) возвращает к
мастеру, «Выйти» (ghost) закрывает его (сигнал confirmed). Своего
Esc-шортката у окна НЕТ — Esc обрабатывает мастер: два сработавших
сразу обработчика могли бы открыть окно снова.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.theme import BG_MAIN, themed_color
from app.ui.widgets.hoverable import HoverButton

CARD_SIZE = (460, 220)
RISE_MS = 320
BLUR_RADIUS = 26


def _make_blurred(source: QPixmap) -> QPixmap:
    """Размытый снимок содержимого окна — фон под карточкой.

    Единственная реализация для всех оверлеев (остальные диалоги
    импортируют её отсюда). parent.grab() на экране с масштабированием
    (Windows 125–150 %, DPR > 1) возвращает пиксели в физическом
    разрешении с devicePixelRatio > 1: сцена же раскладывает pixmap
    по ЛОГИЧЕСКОМУ размеру (size / DPR). Если не привести всё к одной
    системе координат, в render() попадает source-прямоугольник в
    физических пикселях при контенте в логических — содержимое
    уменьшается и прижимается к левому верхнему углу. Поэтому работаем
    в физических пикселях (DPR сцены = 1), а результату возвращаем DPR
    источника.
    """
    dpr = source.devicePixelRatio()
    physical = QPixmap(source)
    physical.setDevicePixelRatio(1.0)

    scene = QGraphicsScene()
    item = scene.addPixmap(physical)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(BLUR_RADIUS * dpr)   # сила блюра — в логических px
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)

    result = QPixmap(physical.size())
    result.fill(themed_color(BG_MAIN))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(result.rect()), QRectF(physical.rect()))
    painter.end()
    result.setDevicePixelRatio(dpr)
    return result


class ExitConfirmOverlay(QWidget):
    """Оверлей подтверждения выхода с потерей введённых данных.

    Используется мастером создания («Выйти из создания альбома?») и
    мастером оценивания («Выйти из оценивания?»): тексты и подписи
    кнопок задаются параметрами (по умолчанию — вариант создания).
    """

    confirmed = Signal()  # «Выйти» — мастер закрывается

    def __init__(
        self,
        parent: QWidget,
        title: str = "Выйти из создания альбома?",
        body: str = "Введённые данные не сохранятся.",
        exit_text: str = "Выйти",
        stay_text: str = "Продолжить создание",
        title_name: str = "warningTitle",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("exitConfirmOverlay")
        self._bg: QPixmap | None = None

        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(*CARD_SIZE)

        self._fx = QGraphicsOpacityEffect(self.card)
        self._fx.setOpacity(1.0)
        self.card.setGraphicsEffect(self._fx)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(12)

        title_lbl = QLabel(title, self.card)
        title_lbl.setObjectName(title_name)
        title_lbl.setWordWrap(True)
        v.addWidget(title_lbl)
        self.lbl_title = title_lbl  # тексты зависят от режима мастера

        body_lbl = QLabel(body, self.card)
        body_lbl.setObjectName("warningBody")
        body_lbl.setWordWrap(True)
        v.addWidget(body_lbl)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_exit = HoverButton(exit_text, self.card)
        self.btn_exit.setObjectName("ghostButton")
        self.btn_exit.clicked.connect(self._confirm_exit)
        buttons.addWidget(self.btn_exit)
        buttons.addStretch(1)
        self.btn_stay = HoverButton(stay_text, self.card)
        self.btn_stay.setObjectName("primaryButton")
        self.btn_stay.clicked.connect(self.close_overlay)
        buttons.addWidget(self.btn_stay)
        v.addLayout(buttons)

    # --- Открытие / закрытие -----------------------------------------------
    def set_texts(self, title: str, stay_text: str) -> None:
        """Обновить тексты под режим мастера (создание/редактирование).

        Мастер один на оба режима — оверлей создаётся один раз и живёт
        до закрытия окна; без этого «Выйти из создания…» прилипал бы
        и показывался при выходе из редактирования (наоборот — тоже).
        """
        self.lbl_title.setText(title)
        self.btn_stay.setText(stay_text)

    def open(self) -> None:
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        self.show()
        self.raise_()

        target = QPoint(
            (self.width() - CARD_SIZE[0]) // 2,
            (self.height() - CARD_SIZE[1]) // 2,
        )
        self._fx.setOpacity(0.0)
        self.card.move(target.x(), self.height() + 8)

        pos_anim = QPropertyAnimation(self.card, b"pos", self.card)
        pos_anim.setDuration(RISE_MS)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        pos_anim.setStartValue(self.card.pos())
        pos_anim.setEndValue(target)
        fade_anim = QPropertyAnimation(self._fx, b"opacity", self.card)
        fade_anim.setDuration(RISE_MS)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        self.btn_stay.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def _confirm_exit(self) -> None:
        self.close_overlay()
        self.confirmed.emit()

    # --- Отрисовка и геометрия ---------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._bg is not None:
            painter.drawPixmap(self.rect(), self._bg)
        else:
            painter.fillRect(self.rect(), themed_color(BG_MAIN))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self.card.move(
                (self.width() - CARD_SIZE[0]) // 2,
                (self.height() - CARD_SIZE[1]) // 2,
            )
            self._fx.setOpacity(1.0)

    def mousePressEvent(self, event) -> None:
        event.accept()
