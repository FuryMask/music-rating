"""Стеклянная навигация медиатеки и панель быстрых действий."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Signal
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.widgets.glass import line_icon, paint_glass
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import reduced_motion
from app.version import VERSION

SIDEBAR_WIDTH = 224    # ширина панели
PLUS_BUTTON_SIZE = 40  # сторона квадратной кнопки


class ActionButton(HoverButton):
    def __init__(self, icon: str, parent: QWidget | None) -> None:
        super().__init__("", parent, outline_radius=12)
        self.setFixedSize(PLUS_BUTTON_SIZE, PLUS_BUTTON_SIZE)
        self.setIcon(line_icon(icon, 23))
        self.setIconSize(QSize(23, 23))


class PlusButton(ActionButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("add-album", parent)


class ProfileButton(ActionButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("account", parent)


class Sidebar(QFrame):
    add_album_clicked = Signal()
    profile_clicked = Signal()
    update_clicked = Signal()
    cloud_upload_clicked = Signal()
    destination_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(6)
        self._destinations: dict[str, HoverButton] = {}
        caption = QLabel("Медиатека", self)
        caption.setObjectName("sidebarCaption")
        layout.addWidget(caption)
        for destination, title in (
            ("home", "Главная"), ("recent", "Недавно оценённые"),
            ("albums", "Альбомы"), ("artists", "Исполнители"),
        ):
            button = HoverButton(title, self, outline_radius=14)
            button.setIcon(line_icon(destination))
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked, key=destination: self.destination_clicked.emit(key)
            )
            self._destinations[destination] = button
            layout.addWidget(button)
        layout.addStretch(1)

        self.btn_update = HoverButton("Обновить", self, outline_radius=14)
        self.btn_update.setIcon(line_icon("update"))
        self.btn_update.setObjectName("updateButton")
        self.btn_update.clicked.connect(self.update_clicked.emit)
        layout.addWidget(self.btn_update)
        self._update_opacity = QGraphicsOpacityEffect(self.btn_update)
        self.btn_update.setGraphicsEffect(self._update_opacity)
        self._update_pulse = QPropertyAnimation(self._update_opacity, b"opacity", self)
        self._update_pulse.setDuration(2400)
        self._update_pulse.setStartValue(1.0)
        self._update_pulse.setKeyValueAt(0.5, 0.72)
        self._update_pulse.setEndValue(1.0)
        self._update_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._update_pulse.setLoopCount(-1)
        self.set_update_state()

        footer = QLabel("Действия", self)
        footer.setObjectName("sidebarCaption")
        layout.addWidget(footer)
        layout.addSpacing(4)

        self.btn_profile = ProfileButton(self)
        self.btn_profile.setObjectName("profileButton")
        self.btn_profile.setToolTip("Профиль")
        self.btn_profile.setAccessibleName("Профиль")
        self.btn_profile.clicked.connect(self.profile_clicked.emit)

        self.btn_cloud_upload = ActionButton("cloud-upload", self)
        self.btn_cloud_upload.setObjectName("cloudUploadButton")
        self.btn_cloud_upload.setToolTip("Загрузить в облако")
        self.btn_cloud_upload.setAccessibleName("Загрузить в облако")
        self.btn_cloud_upload.clicked.connect(self.cloud_upload_clicked.emit)

        self.btn_add = PlusButton(self)
        self.btn_add.setObjectName("plusButton")
        self.btn_add.setToolTip("Добавить альбом")
        self.btn_add.setAccessibleName("Добавить альбом")
        self.btn_add.clicked.connect(self.add_album_clicked.emit)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self.btn_profile)
        row.addWidget(self.btn_cloud_upload)
        row.addWidget(self.btn_add)
        row.addStretch()
        layout.addLayout(row)
        self.version_label = QLabel(VERSION, self)
        self.version_label.setObjectName("appVersion")
        layout.addWidget(self.version_label)

        self.set_destination("home")

    def paintEvent(self, event) -> None:
        paint_glass(self, 23, vertical=True)

    def set_update_state(self, version: str = "", progress: int | None = None) -> None:
        available = bool(version) and progress is None
        self.btn_update.setEnabled(available)
        self.btn_update.setText("Обновить" if progress is None else f"Загрузка… {progress}%")
        self.btn_update.setToolTip(f"Доступна версия {version}" if version else "Нет доступных обновлений")
        self._update_pulse.stop()
        self._update_opacity.setOpacity(1.0)
        self._update_opacity.setEnabled(available and not reduced_motion())
        if self._update_opacity.isEnabled():
            self._update_pulse.start()

    def set_destination(self, destination: str | None) -> None:
        for key, button in self._destinations.items():
            button.setChecked(key == destination)
