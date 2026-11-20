"""Select the desktop client before entering listening mode."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import fade_in


class PlaybackChoiceDialog(QDialog):
    selected = Signal(str)

    def __init__(self, parent) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Выбор приложения")
        self.setMinimumWidth(480)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(22)
        title = QLabel("Выберите приложение для прослушивание музыки.", self.card)
        title.setWordWrap(True)
        title.setObjectName("warningTitle")
        layout.addWidget(title)

        buttons = QHBoxLayout()
        self.back_button = HoverButton("Назад", self.card)
        self.back_button.setObjectName("ghostButton")
        self.back_button.clicked.connect(self.reject)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        self.yandex_button = HoverButton("Я.Музыка", self.card)
        self.spotify_button = HoverButton("Spoify", self.card)
        self.spotify_button.setAccessibleName("Spotify")
        for key, button in (("yandex", self.yandex_button), ("spotify", self.spotify_button)):
            button.setObjectName("ghostButton")
            button.clicked.connect(lambda _, source=key: self._select(source))
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.back_button.setFocus()
        fade_in(self.card, 180)

    def _select(self, source: str) -> None:
        self.accept()
        self.selected.emit(source)
