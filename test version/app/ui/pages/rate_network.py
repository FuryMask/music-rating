"""Мастер оценивания ПО СЕТИ + реестр комнат (заготовка, Task 25).

Реального сетевого соединения пока нет — всё работает локально.
Заготовка повторяет целевую логику будущего P2P-режима:

  Этап 1 «Лобби» — хост видит, кто подключился. В заглушке участники
      (аккаунты, кроме хоста) «подключаются» сами с задержкой ~1 с;
      если аккаунт только один, к хосту через пару секунд
      присоединяется демо-участник, чтобы поток был проверяем.
      Когда все собрались, хост жмёт «Оценить» → все на этап 2.
  Этап 2 — как в локальном мастере: столбец на КАЖДОГО участника
      лобби (хост + подключившиеся; состав фиксирует лобби —
      _lock_raters запрещает базовому мастеру пересобирать его
      по STORE.raters).
  Этап 3 «Итоги» — без изменений.

Сессия (NetworkSession) живёт в главном окне: выход из оценивания
в ЛЮБОЙ момент сохраняет состав, этап и выставленные оценки —
повторное подключение («По сети» с того же альбома или своя комната
в поиске лобби) возвращает на тот же этап с теми же данными. Если
участник не вернётся до конца оценивания, его оценки исчезнут
(правило будущего соединения; в заглушке «Готово» сохраняет всё
локально, сессия снимается).

Состав лобби: session.joined — ВСЕ участники ВКЛЮЧАЯ хоста
(хост первым). Столбцы этапа 2 строятся ровно из этого списка,
у хоста всегда есть своя колонка.

Реестр комнат (ROOMS) — модульный список лобби для страницы «Комнаты»:
хостская сессия регистрирует комнату при создании, снимает после
«Готово» (или при удалении альбома).
"""

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.store import STORE
from app.ui.pages.rate_album import RATE_STEP_NAMES, RateAlbumOverlay
from app.ui.widgets.flow_layout import FlowLayout

# Задержки симуляции сети (мс): «подключение» участника к лобби
JOIN_DELAY_MS = 1000
HOST_START_DELAY_MS = 3500   # «хост начал оценивание» в гостевом лобби

DEMO_GUEST_NAME = "Демо-гость"


@dataclass
class NetworkSession:
    """Состояние сеанса оценивания по сети (живёт в главном окне).

    Выход из мастера сессию НЕ уничтожает: stage/rater_names/values
    переживают закрытие окна — повторное подключение продолжает с того
    же места. Сессия снимается после «Готово» (оценки сохранены).

    joined — все участники лобби ВКЛЮЧАЯ хоста (хост первым).
    """

    album_id: str
    host_name: str              # имя хоста (кто начал оценивание)
    is_host: bool               # этот пользователь — хост?
    joined: list[str] = field(default_factory=list)   # кто в лобби
    stage: int = 0              # 0 лобби / 1 оценки / 2 итоги
    rater_names: list[str] = field(default_factory=list)  # столбики этапа 2
    values: list = field(default_factory=list)  # матрица оценок


@dataclass
class NetworkRoom:
    """Комната в поиске лобби (заглушка): альбом + имя хоста."""

    album_id: str
    host_name: str


# Активные комнаты лобби (живут, пока жив процесс приложения)
ROOMS: list[NetworkRoom] = []


def register_room(album_id: str, host_name: str) -> None:
    """Хост начал сетевое оценивание — комната появилась в поиске."""
    if not any(room.album_id == album_id for room in ROOMS):
        ROOMS.append(NetworkRoom(album_id=album_id, host_name=host_name))


def unregister_room(album_id: str) -> None:
    """«Готово» хоста (или альбом удалён) — комнаты больше нет."""
    ROOMS[:] = [room for room in ROOMS if room.album_id != album_id]


def find_album(album_id: str):
    """Альбом по id (или None — удалён/не найден)."""
    return next(
        (album for album in STORE.albums if album.id == album_id), None
    )


class NetworkRateOverlay(RateAlbumOverlay):
    """Мастер оценивания по сети: лобби → оценки → итоги (заглушка)."""

    session_finished = Signal(str, bool)  # album_id, был ли это хост

    def __init__(self, parent: QWidget) -> None:
        self._session: NetworkSession | None = None
        super().__init__(parent)
        self._lock_raters = True
        self.setWindowTitle("Оценивание по сети")
        self._join_timer = QTimer(self)
        self._join_timer.setInterval(JOIN_DELAY_MS)
        self._join_timer.timeout.connect(self._simulate_join)

    # ================= Этап 1: лобби =================
    def _make_raters_step(self) -> QWidget:
        """Лобби вместо выбора участников (переопределение этапа 1)."""
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(14)

        title = QLabel("Лобби", page)
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        self.lbl_lobby_host = QLabel("", page)
        self.lbl_lobby_host.setObjectName("stepHint")
        self.lbl_lobby_host.setWordWrap(True)
        v.addWidget(self.lbl_lobby_host)

        self.lbl_lobby_hint = QLabel("", page)
        self.lbl_lobby_hint.setObjectName("emptyHint")
        self.lbl_lobby_hint.setWordWrap(True)
        v.addWidget(self.lbl_lobby_hint)

        # Список подключившихся — плитки-имена (не кликаются),
        # та же компоновка, что у плиток участников локального мастера
        chips_holder = QWidget(page)
        self.lobby_flow = FlowLayout(chips_holder, spacing=10)
        self.lobby_flow.setContentsMargins(10, 10, 10, 10)
        v.addWidget(chips_holder)

        v.addStretch(1)
        return page

    def _rebuild_lobby(self) -> None:
        """Перечитать список подключившихся из сессии в плитки лобби."""
        session = self._session
        if session is None or self._album is None:
            return
        while self.lobby_flow.count():
            item = self.lobby_flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        role = "Вы — хост" if session.is_host else "Хост"
        self.lbl_lobby_host.setText(
            f"{role}: {session.host_name} · Альбом: {self._album.title}"
        )
        if session.joined:
            self.lbl_lobby_hint.setText(
                f"В лобби: {', '.join(session.joined)}"
            )
        else:
            self.lbl_lobby_hint.setText(
                "Ожидание участников…"
                if session.is_host
                else "Ожидание хоста…"
            )
        for name in session.joined:
            chip = QLabel(name, self.lobby_flow.parentWidget())
            chip.setObjectName("raterChip")
            chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lobby_flow.addWidget(chip)
            chip.show()
        self._update_next_state()

    def _simulate_join(self) -> None:
        """Заглушка сети: участники подключаются к лобби по очереди."""
        session = self._session
        if session is None or session.stage != 0 or not session.is_host:
            self._join_timer.stop()
            return
        others = [
            name for name in STORE.raters if name != session.host_name
        ]
        pending = [name for name in others if name not in session.joined]
        if pending:
            session.joined.append(pending[0])
            self._rebuild_lobby()
            return
        if not others and DEMO_GUEST_NAME not in session.joined:
            # Аккаунтов, кроме хоста, нет — «подключается» демо-гость
            session.joined.append(DEMO_GUEST_NAME)
            self._rebuild_lobby()
            return
        self._join_timer.stop()  # все, кто мог, уже в лобби

    # --- Переопределения базового мастера --------------------------------
    def _rebuild_rater_chips(self) -> None:
        """Этап 1 заменён лобби — базовая пересборка плиток не нужна."""

    def _ensure_values_shape(self) -> None:
        """Матрица оценок всегда [треки][участники лобби].

        Несовпадение размера (первый вход на этап 2, правка треклиста
        альбома посреди сессии) — матрица создаётся заново.
        """
        session = self._session
        if session is None or self._album is None:
            return
        rows, cols = len(self._album.tracks), len(session.joined)
        values = session.values
        if len(values) != rows or any(
            len(row) != cols for row in values
        ):
            session.values = [
                [None] * cols for _ in range(rows)
            ]

    def open_for_session(self, session: NetworkSession, album) -> None:
        """Открыть мастер на СОСТОЯНИИ сессии (лобби или позже)."""
        stage = session.stage  # super().open_for сбросит его через шаг 0
        self._session = session
        self._join_timer.stop()
        # Базовое open_for сбрасывает _selected/_raters/_values и
        # показывает шаг 0 — сетевое состояние восстановим поверх
        super().open_for(album)
        self.setWindowTitle("Оценивание по сети")
        if stage == 0:
            if session.is_host:
                self._join_timer.start()
            else:
                self.simulate_guest_lobby()
        else:
            # Повторное подключение к идущему оцениванию: тот же этап,
            # те же столбики и значения
            self._raters = (
                list(session.rater_names) or list(session.joined)
            )
            self._selected = set(self._raters)
            self._ensure_values_shape()
            self._values = session.values
            self.go_to_step(stage)

    def _step_text(self, index: int) -> str:
        names = ["Лобби", "Оценки", "Итоги"]
        return f"Шаг {index + 1} из {len(RATE_STEP_NAMES)} · {names[index]}"

    def go_to_step(self, index: int) -> None:
        session = self._session
        if session is not None:
            if index == 1:
                # Столбики = состав лобби (хост + подключившиеся)
                self._raters = list(session.joined)
                self._selected = set(self._raters)
                self._ensure_values_shape()
                self._values = session.values
            elif index == 2:
                session.values = self._values
            session.stage = index
        super().go_to_step(index)
        if index == 0 and session is not None:
            self.btn_next.setText("Оценить")
            self._rebuild_lobby()
        # Лобби → «Далее» ведёт сразу на оценки; «Назад» с оценок
        # возвращает в лобби (сессия сохраняется)

    def _update_next_state(self) -> None:
        session = self._session
        if session is not None and self.steps.currentIndex() == 0:
            # Хост может начать, когда в лобби есть кто-то кроме него;
            # гость ждёт хоста (кнопка недоступна всегда)
            ready = session.is_host and any(
                name != session.host_name for name in session.joined
            )
            self.btn_next.setEnabled(ready)
            return
        super()._update_next_state()

    def _request_exit(self) -> None:
        """Выход в любой момент: сессия и оценки сохраняются."""
        if not self.isVisible():
            return
        self._join_timer.stop()
        if self._exit_overlay is not None and self._exit_overlay.isVisible():
            self._exit_overlay.close_overlay()
        session = self._session
        if session is not None and self.steps.currentIndex() >= 1:
            session.values = self._values
            session.rater_names = list(self._raters)
        self.hide()

    def open_for(self, album) -> None:  # noqa: D102 — запрещён: только сессия
        raise RuntimeError(
            "NetworkRateOverlay.open_for запрещён — используйте "
            "open_for_session (сетевое оценивание живёт в сессии)"
        )

    # --- Гостевой сценарий (заглушка) ------------------------------------
    def simulate_guest_lobby(self) -> None:
        """Гостевое лобби: через паузу «хост» начинает оценивание."""
        session = self._session
        if session is None or session.is_host:
            return

        def host_start() -> None:
            if (
                self._session is session
                and self.isVisible()
                and session.stage == 0
            ):
                self.go_to_step(1)

        QTimer.singleShot(HOST_START_DELAY_MS, host_start)

    # --- Завершение --------------------------------------------------------
    def _finish(self) -> None:
        """«Готово»: в заглушке сохраняем оценки локально, сессия снята."""
        session = self._session
        self._join_timer.stop()
        album = self._album
        STORE.rate_album(album, self._raters, self._values)
        self.hide()
        if session is not None:
            session.stage = 2
            self.session_finished.emit(session.album_id, session.is_host)
        self._session = None
