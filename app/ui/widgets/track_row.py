"""Строка трека в сегменте «Треклист» мастера создания.

Анатомия:
  ┌──────────────────────────────────────────────────┐
  │ 01  Название трека            Земфира · Muse   ✕ │
  └──────────────────────────────────────────────────┘
Длинные названия и списки исполнителей сокращаются многоточием.
Крестик удаления — ChipRemoveButton (БЕЗ ховер-обводки и роста,
как в плитках исполнителей). Последняя строка — без разделителя.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.models import TrackDraft
from app.ui.widgets.artist_chip import ChipRemoveButton

TRACK_ROW_HEIGHT = 48      # высота строки
TRACK_INDEX_WIDTH = 22     # ширина колонки с номером
TRACK_FRAME_EMPTY_H = 56   # высота сегмента «Треклист», когда он пуст


class TrackRow(QWidget):
    """Одна строка списка треков: номер, название, исполнители, «×»."""

    removed = Signal(object)  # TrackDraft этой строки

    def __init__(self, index: int, track: TrackDraft,
                 parent: QWidget | None = None,
                 is_last: bool = False) -> None:
        super().__init__(parent)
        self.track = track
        self.setObjectName("trackRowLast" if is_last else "trackRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TRACK_ROW_HEIGHT)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)

        self.lbl_index = QLabel(f"{index + 1:02d}", self)
        self.lbl_index.setObjectName("trackIndex")
        self.lbl_index.setFixedWidth(TRACK_INDEX_WIDTH)
        row.addWidget(self.lbl_index)

        self.lbl_title = QLabel(track.title, self)
        self.lbl_title.setObjectName("trackRowTitle")
        row.addWidget(self.lbl_title, 1)

        self.lbl_artists = QLabel(self._artists_text(), self)
        self.lbl_artists.setObjectName("trackArtists")
        row.addWidget(self.lbl_artists)

        self.btn_remove = ChipRemoveButton(self)
        self.btn_remove.setToolTip("Удалить трек")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self.track))
        row.addWidget(self.btn_remove)

    # --- Текст исполнителей ---
    def _artists_text(self) -> str:
        names = [a.name for a in self.track.artists]
        return " · ".join(names) if names else "—"

    # --- Сокращение длинных подписей ---
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        artists_w = min(280, max(60, width // 3))
        title_w = max(
            60,
            width - TRACK_INDEX_WIDTH - artists_w - 24 - 12 * 3 - 8,
        )
        title_fm = QFontMetrics(self.lbl_title.font())
        self.lbl_title.setText(title_fm.elidedText(
            self.track.title, Qt.TextElideMode.ElideRight, title_w
        ))
        artists_fm = QFontMetrics(self.lbl_artists.font())
        self.lbl_artists.setText(artists_fm.elidedText(
            self._artists_text(), Qt.TextElideMode.ElideRight, artists_w
        ))
