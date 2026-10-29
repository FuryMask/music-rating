"""Левая панель приложения.

Внизу — ряд квадратных кнопок: профиль (иконка «человек», САМЫЙ
ЛЕВЫЙ), сетевые комнаты (иконка «планета», рядом), переключатель
режима просмотра (иконка «БД»: Локально/Облачно) и «+» (справа).
Профиль открывает окно входа/регистрации или карточку аккаунта
(см. dialogs/profile_dialog.py), планета — страницу поиска комнат
оценивания по сети (см. pages/rooms_page.py), БД переключает режим
просмотра: Локально (своё) / Облачно (загруженное всеми; пока
сетевых функций нет — «В разработке»), «+» открывает мастер
создания альбома. Навигационные пункты появятся позже.
"""

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from app.ui.widgets.hoverable import HoverButton

SIDEBAR_WIDTH = 216    # ширина панели
PLUS_BUTTON_SIZE = 40  # сторона квадратной кнопки


class PlusButton(HoverButton):
    """Кнопка «+»: плюс рисуется вручную — строго по центру.

    Знак «+» шрифтом в QPushButton садится чуть ниже оптического
    центра (так устроены метрики глифа), поэтому рисуем две линии.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=10)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон и рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e8e8e8"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        arm = 8.0
        painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


class ProfileButton(HoverButton):
    """Кнопка профиля: стандартная иконка «человек» рисуется линиями.

    Как и у «+», иконка рисуется в paintEvent (голова — окружность,
    плечи — верхняя половина окружности): текст/эмодзи шрифтом
    смотрятся грубо и по-разному на разных системах. Стиль линий —
    как у кнопки «назад» на странице альбома.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=10)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон и рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e8e8e8"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        # Голова — окружность над центром
        painter.drawEllipse(QPointF(cx, cy - 4.5), 4.2, 4.2)
        # Плечи — верхняя половина окружности с центром ниже
        painter.drawArc(QRectF(cx - 8.5, cy + 0.5, 17, 17), 0, 180 * 16)


class PlanetButton(HoverButton):
    """Кнопка сетевых комнат: иконка «планета» рисуется линиями.

    Круг-планета + меридиан (узкий эллипс) + кольцо (плоский эллипс,
    как у Сатурна) — читается как «интернет/сеть». Стиль линий —
    как у соседних кнопок профиля и «+».
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=10)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон и рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e8e8e8"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        # Планета — окружность в центре
        painter.drawEllipse(QPointF(cx, cy), 5.4, 5.4)
        # Меридиан — узкий вертикальный эллипс внутри планеты
        painter.drawEllipse(QPointF(cx, cy), 2.3, 5.4)
        # Кольцо — плоский эллипс вокруг планеты
        painter.drawEllipse(QPointF(cx, cy), 9.4, 3.4)


class DbModeButton(HoverButton):
    """Переключатель режима просмотра: иконка «БД» (цилиндр).

    Классическая пиктограмма базы данных: верхний эллипс, боковые
    линии вниз, нижняя дуга и дуга «слоя» посередине. Кнопка
    checkable: отмеченное состояние (QSS :checked) означает режим
    «Облачно». Стиль линий — как у соседних кнопок сайдбара.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent, outline_radius=10)
        self.setCheckable(True)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # фон и рамка из QSS (текст пустой)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e8e8e8"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2, self.height() / 2
        rx, ry = 7.0, 2.8          # радиусы эллипса-«крышки»
        top = cy - 6.0             # центр верхней крышки
        bottom = cy + 6.0          # центр нижней дуги
        # Крышка — полный эллипс сверху
        painter.drawEllipse(QPointF(cx, top), rx, ry)
        # Боковые стенки
        painter.drawLine(QPointF(cx - rx, top), QPointF(cx - rx, bottom))
        painter.drawLine(QPointF(cx + rx, top), QPointF(cx + rx, bottom))
        # Дно — нижняя половина эллипса (180°…360° в единицах 1/16°)
        painter.drawArc(
            QRectF(cx - rx, bottom - ry, rx * 2, ry * 2), 180 * 16, 180 * 16
        )
        # Слой посередине — тоже нижняя дуга
        painter.drawArc(
            QRectF(cx - rx, cy - ry, rx * 2, ry * 2), 180 * 16, 180 * 16
        )


class Sidebar(QFrame):
    add_album_clicked = Signal()
    profile_clicked = Signal()
    network_clicked = Signal()
    mode_clicked = Signal()  # переключить режим Локально/Облачно

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        layout.addStretch(1)  # навигация появится здесь позже

        # Кнопки в нижнем углу панели: профиль — САМЫЙ ЛЕВЫЙ, планета
        # (сети) рядом, переключатель режима просмотра рядом с ними,
        # «+» остаётся справа
        self.btn_profile = ProfileButton(self)
        self.btn_profile.setObjectName("profileButton")
        self.btn_profile.setFixedSize(PLUS_BUTTON_SIZE, PLUS_BUTTON_SIZE)
        self.btn_profile.setToolTip("Профиль")
        self.btn_profile.clicked.connect(self.profile_clicked.emit)

        self.btn_network = PlanetButton(self)
        self.btn_network.setObjectName("networkButton")
        self.btn_network.setFixedSize(PLUS_BUTTON_SIZE, PLUS_BUTTON_SIZE)
        self.btn_network.setToolTip("Оценивание по сети")
        self.btn_network.clicked.connect(self.network_clicked.emit)

        self.btn_mode = DbModeButton(self)
        self.btn_mode.setObjectName("modeButton")
        self.btn_mode.setFixedSize(PLUS_BUTTON_SIZE, PLUS_BUTTON_SIZE)
        self.btn_mode.clicked.connect(self.mode_clicked.emit)

        self.btn_add = PlusButton(self)
        self.btn_add.setObjectName("plusButton")
        self.btn_add.setFixedSize(PLUS_BUTTON_SIZE, PLUS_BUTTON_SIZE)
        self.btn_add.setToolTip("Добавить альбом")
        self.btn_add.clicked.connect(self.add_album_clicked.emit)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)  # зазор между кнопками задаёт компоновка
        row.addWidget(self.btn_profile)
        row.addWidget(self.btn_network)
        row.addWidget(self.btn_mode)
        row.addStretch(1)
        row.addWidget(self.btn_add)
        layout.addLayout(row)

        self.set_view_mode(cloud=False)

    def set_view_mode(self, cloud: bool) -> None:
        """Отразить режим на кнопке: checked = «Облачно».

        Заодно подсказка на кнопке называет ОБА режима и текущий:
        иконка-цилиндр молчит, а надпись в верхней полосе
        (TopBar.mode_label) дублирует режим для уверенности.
        """
        self.btn_mode.setChecked(cloud)
        current = "Облачно" if cloud else "Локально"
        other = "Локально" if cloud else "Облачно"
        self.btn_mode.setToolTip(
            f"Режим просмотра: {current}. Нажмите — «{other}»"
        )
