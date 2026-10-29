"""verify_task25 — интерфейс одновременного оценивания по сети (заготовка).

Покрывает:
  1. Сайдбар: профиль — САМЫЙ ЛЕВЫЙ, рядом кнопка-планета (сети), «+» справа.
  2. Страница «Комнаты» (по планете): заглушка «В разработке»
     (Task 31: интерфейса комнат больше нет), Esc — назад.
  3. «Оценить?» → окно «Локально или по сети?» (Нет/Локально/По сети);
     «Нет» закрывает, «Локально» — обычный мастер; после создания
     альбома режим тоже выбирается в этом окне.
  4. Сетевой мастер (хост): лобби → симуляция подключения участников →
     «Оценить» → этап 2 СО СТОЛБЦОМ ХОСТА и каждого участника → итоги →
     «Готово»: оценки в базе, комната снята, сессия удалена.
  5. Выход в любой момент: сессия хранит этап/столбики/значения;
     повторное «По сети» возвращает на тот же этап с теми же клетками.
  6. Комнаты — заглушка: реестр ROOMS продолжает жить (для сетевых
     сессий), но строки/лобби-переходы на странице не показываются.
  7. Уборка: удаление альбома снимает сессии и комнату (реестр);
     register_room/unregister_room работают; NetworkRateOverlay.open_for
     запрещён.
  8. Смоук main.py (offscreen) без traceback.

ВНИМАНИЕ: тесты СТИРАЮТ data/ и создают пустую базу —
не запускать на машине с живой библиотекой!
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Путь к корню приложения определяем по расположению самого скрипта
_CANDIDATES = [
    Path(__file__).resolve().parent,        # <app>/verify_*.py
    Path(__file__).resolve().parents[1],    # <app>/dev/verify_*.py
    Path("/home/z/my-project/music-rating-app"),  # песочница (Linux)
]
APP = next(c for c in _CANDIDATES if (c / "app" / "theme.py").exists())
sys.path.insert(0, str(APP))

# ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtTest import QTest

app = QApplication([])
app.setApplicationName("Music Rating")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))

import app.theme as theme

theme.apply_theme(app)

# Заглушка фоновой дозагрузки фото (без сети)
import app.services.backfill as bf


class _StubBackfiller(QObject):
    changed = Signal()

    def __init__(self, *a, **k) -> None:
        super().__init__()

    def start(self) -> None:
        pass


bf.ArtBackfiller = _StubBackfiller

import app.ui.pages.rate_network as rn
from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.store import STORE
from app.ui.main_window import MainWindow
from app.ui.pages.rate_network import (
    DEMO_GUEST_NAME,
    ROOMS,
    NetworkRateOverlay,
    find_album,
    register_room,
    unregister_room,
)
from app.ui.sidebar import PlanetButton

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


def button_by_text(holder, text: str):
    """Кнопка с точным текстом среди детей holder (для оверлеев)."""
    for btn in holder.findChildren(QPushButton):
        if btn.text() == text:
            return btn
    return None


def visible_buttons(holder) -> list[str]:
    return [
        btn.text() for btn in holder.findChildren(QPushButton)
        if btn.text() and btn.isVisible()
    ]


# Задержки симуляции сети — ускоряем (патч ДО создания оверлеев)
rn.JOIN_DELAY_MS = 120
rn.HOST_START_DELAY_MS = 450
JOIN_WAIT = 400     # больше задержки подключения
START_WAIT = 800    # больше задержки «хост начал»

# --- Данные: аккаунты и альбомы -------------------------------------------
STORE.register_user("Георгий", "1")
STORE.register_user("Аркадий", "2")
georgy = STORE.find_user("Георгий")
STORE.set_current_user(georgy)

net_album = STORE.add_album(AlbumDraft(
    title="Сетевой альбом", year="2024", region="RU",
    artists=[ArtistDraft(name="Группа A", existing=False)],
    tracks=[TrackDraft(title="Трек 1"), TrackDraft(title="Трек 2")],
))
del_album = STORE.add_album(AlbumDraft(
    title="Одноразовый альбом", year="2023", region="RU",
    tracks=[TrackDraft(title="Трек X")],
))
local_album = STORE.add_album(AlbumDraft(
    title="Локальный альбом", year="2022", region="RU",
    tracks=[TrackDraft(title="Лок-трек 1"), TrackDraft(title="Лок-трек 2")],
))

win = MainWindow()
win.resize(1100, 700)
win.show()
QTest.qWait(250)

# ============================================================
print("--- 1. Сайдбар: профиль слева, планета рядом, «+» справа ---")
check("планета — PlanetButton",
      isinstance(win.sidebar.btn_network, PlanetButton))
check("профиль самый левый",
      win.sidebar.btn_profile.x() < win.sidebar.btn_network.x()
      < win.sidebar.btn_add.x())
check("профиль и планета в одном ряду",
      win.sidebar.btn_profile.y() == win.sidebar.btn_network.y())
check("у планеты подсказка «Оценивание по сети»",
      win.sidebar.btn_network.toolTip() == "Оценивание по сети")

# ============================================================
print("--- 2. Страница «Комнаты»: заглушка «В разработке» ---")
QTest.mouseClick(win.sidebar.btn_network, Qt.MouseButton.LeftButton)
QTest.qWait(100)
check("планета открывает страницу комнат",
      win.pages.currentWidget() is win.rooms_page)
check("комнат нет — «В разработке» видно",
      win.rooms_page.lbl_dev.isVisible()
      and win.rooms_page.lbl_dev.text() == "В разработке")
check("интерфейса комнат больше нет (Task 31: только текст)",
      not hasattr(win.rooms_page, "list_frame")
      and not hasattr(win.rooms_page, "rows_v")
      and not hasattr(win.rooms_page, "btn_back"))
QTest.keyClick(win, Qt.Key.Key_Escape)  # Esc — назад со страницы комнат
QTest.qWait(100)
check("назад со страницы комнат — на главную",
      win.pages.currentWidget() is win.home_page)

# ============================================================
print("--- 3. «Оценить?» → выбор режима ---")
win.open_rate_album(local_album)
QTest.qWait(400)
mode = win._rate_mode_overlay
check("открылось окно выбора режима", mode is not None and mode.isVisible())
check("текст вопроса режима",
      mode.card.findChildren(QLabel)[0].text()
      == "Вы хотите оценить локально или по сети?")
btns = visible_buttons(mode.card)
check("кнопки режима: Нет/По сети/Локально",
      btns == ["Нет", "По сети", "Локально"])
QTest.mouseClick(button_by_text(mode.card, "Нет"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(150)
check("«Нет» закрывает окно, мастер не открыт",
      not mode.isVisible() and win._rate_overlay is None
      and win._network_overlay is None)

win.open_rate_album(local_album)
QTest.qWait(400)
QTest.mouseClick(button_by_text(mode.card, "Локально"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(300)
local = win._rate_overlay
check("«Локально» открывает обычный мастер",
      local is not None and local.isVisible()
      and local.steps.currentIndex() == 0)
QTest.mouseClick(local.btn_cancel, Qt.MouseButton.LeftButton)
QTest.qWait(150)
check("локальный мастер закрыт (нечего терять — без подтверждения)",
      not local.isVisible())

# После создания альбома — тоже окно режима
win._offer_rate_after_create(local_album)
QTest.qWait(400)
after = win._after_create_overlay
check("предложение «оценить сейчас?» видно",
      after is not None and after.isVisible())
QTest.mouseClick(after.btn_yes, Qt.MouseButton.LeftButton)
QTest.qWait(400)
check("после создания — окно режима (не мастер сразу)",
      mode.isVisible() and not (win._rate_overlay
                                and win._rate_overlay.isVisible()))
QTest.mouseClick(button_by_text(mode.card, "Нет"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(150)

# ============================================================
print("--- 4. Сетевой мастер (хост): лобби → оценки → итоги ---")
win.open_rate_album(net_album)
QTest.qWait(60)  # меньше интервала подключения — лобби ещё «пустое»
QTest.mouseClick(button_by_text(mode.card, "По сети"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(60)  # сессия/комната создаются синхронно, тик таймера ещё не был
net = win._network_overlay
check("«По сети» открывает сетевой мастер",
      net is not None and net.isVisible())
check("заголовок окна «Оценивание по сети»",
      net.windowTitle() == "Оценивание по сети")
check("этап 1 называется «Лобби»",
      "Лобби" in net.lbl_step.text())
session = win._network_sessions.get((net_album.id, True))
check("сессия хоста создана", session is not None and session.is_host)
check("хост сессии — текущий аккаунт",
      session.host_name == "Георгий" and session.joined == ["Георгий"])
check("комната зарегистрирована",
      any(r.album_id == net_album.id for r in ROOMS))
check("подпись лобби: «Вы — хост»",
      "Вы — хост" in net.lbl_lobby_host.text()
      and "Сетевой альбом" in net.lbl_lobby_host.text())
check("один в лобби — «Оценить» недоступна",
      net.btn_next.text() == "Оценить" and not net.btn_next.isEnabled())

QTest.qWait(JOIN_WAIT)  # Аркадий «подключается»
check("участник подключился к лобби",
      session.joined == ["Георгий", "Аркадий"])
check("плиток лобби две", net.lobby_flow.count() == 2)
check("«Оценить» доступна", net.btn_next.isEnabled())
check("подсказка перечисляет лобби",
      "Георгий" in net.lbl_lobby_hint.text()
      and "Аркадий" in net.lbl_lobby_hint.text())

QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)
QTest.qWait(300)
check("этап 2 «Оценки»", net.steps.currentIndex() == 1)
check("столбик ЕСТЬ у хоста",
      net._raters == ["Георгий", "Аркадий"])
check("средних по числу столбиков", len(net._avg_labels) == 2)
QTest.keyClicks(net._cells[0][0], "7")
QTest.qWait(80)
check("значение клетки хоста записалось",
      net._values[0][0] == 7.0)
QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)
QTest.qWait(300)
check("этап 3 «Итоги»", net.steps.currentIndex() == 2)
QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)  # «Готово»
QTest.qWait(300)
check("мастер закрыт", not net.isVisible())
check("оценки сохранены в базу",
      net_album.ratings is not None
      and net_album.ratings.rater_names == ["Георгий", "Аркадий"])
check("сессия снята после «Готово»",
      (net_album.id, True) not in win._network_sessions)
check("комната снята после «Готово»",
      not any(r.album_id == net_album.id for r in ROOMS))
check("средняя альбома на странице",
      net_album.rating is not None)

# ============================================================
print("--- 5. Выход в любой момент + переподключение (хост) ---")
win.open_rate_album(net_album)
QTest.qWait(400)
QTest.mouseClick(button_by_text(mode.card, "По сети"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(300)
session2 = win._network_sessions.get((net_album.id, True))
check("новая сессия хоста (после «Готово» старая снята)",
      session2 is not None and session2 is not session)
QTest.qWait(JOIN_WAIT)
QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)
QTest.qWait(300)
QTest.keyClicks(net._cells[0][0], "8")
QTest.qWait(80)
QTest.keyClicks(net._cells[1][1], "6.5")
QTest.qWait(80)
QTest.mouseClick(net.btn_cancel, Qt.MouseButton.LeftButton)
QTest.qWait(200)
check("выход по «Отмена» — окно закрыто", not net.isVisible())
check("сессия хранит этап и значения",
      session2.stage == 1
      and session2.values[0][0] == 8.0
      and session2.values[1][1] == 6.5
      and session2.rater_names == ["Георгий", "Аркадий"])
check("комната осталась после выхода",
      any(r.album_id == net_album.id for r in ROOMS))

win.open_rate_album(net_album)
QTest.qWait(400)
QTest.mouseClick(button_by_text(mode.card, "По сети"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(300)
check("переподключение — ТА ЖЕ сессия",
      win._network_sessions.get((net_album.id, True)) is session2)
check("возврат на этап 2 (Оценки)", net.steps.currentIndex() == 1)
check("клетки восстановлены",
      net._cells[0][0].text() == "8.0"
      and net._cells[1][1].text() == "6.5")
QTest.mouseClick(net.btn_cancel, Qt.MouseButton.LeftButton)
QTest.qWait(200)

# ============================================================
print("--- 6. Комнаты — заглушка: интерфейса строк нет (Task 31) ---")
# Комната хоста зарегистрирована в реестре (создана в разделе 5),
# но страницей больше не показывается — только «В разработке»
QTest.mouseClick(win.sidebar.btn_network, Qt.MouseButton.LeftButton)
QTest.qWait(150)
rooms = win.rooms_page
check("страница комнат — только надпись «В разработке»",
      rooms.lbl_dev.isVisible()
      and not hasattr(rooms, "rows_v"))
check("строк-комнат нет (интерфейс удалён)",
      not hasattr(rooms, "row_count")
      and not hasattr(rooms, "room_at"))
check("реестр комнат жив (для сетевых сессий)",
      any(r.album_id == net_album.id for r in ROOMS))
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(100)
check("Esc возвращает со страницы комнат",
      win.pages.currentWidget() is win.home_page)

# ============================================================
print("--- 7. Хост завершает: комната снята ---")
win.open_rate_album(net_album)
QTest.qWait(400)
QTest.mouseClick(button_by_text(mode.card, "По сети"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(300)
check("хост вернулся на свой этап 2",
      net.steps.currentIndex() == 1
      and win._network_sessions.get((net_album.id, True)) is session2)
QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)
QTest.qWait(300)
QTest.mouseClick(net.btn_next, Qt.MouseButton.LeftButton)  # «Готово»
QTest.qWait(300)
check("оценки хоста перезаписали гостевые",
      net_album.ratings.rater_names == ["Георгий", "Аркадий"])
check("комната снята, сессий нет",
      not any(r.album_id == net_album.id for r in ROOMS)
      and not win._network_sessions)
QTest.mouseClick(win.sidebar.btn_network, Qt.MouseButton.LeftButton)
QTest.qWait(150)
check("страница комнат снова показывает «В разработке»",
      win.pages.currentWidget() is win.rooms_page
      and win.rooms_page.lbl_dev.isVisible())

# ============================================================
print("--- 8. Уборка: реестр комнат и удаление альбома ---")
register_room("dead-id", "Кто-то")
check("мертвая комната зарегистрирована в реестре",
      any(r.album_id == "dead-id" for r in ROOMS))
unregister_room("dead-id")
check("unregister_room снимает устаревшую комнату",
      not any(r.album_id == "dead-id" for r in ROOMS))

win.open_rate_album(del_album)
QTest.qWait(400)
QTest.mouseClick(button_by_text(mode.card, "По сети"),
                 Qt.MouseButton.LeftButton)
QTest.qWait(300)
check("комната одноразового альбома создана",
      any(r.album_id == del_album.id for r in ROOMS))
win._pending_delete = del_album
win._delete_current_album()
QTest.qWait(150)
check("удаление альбома сняло сессии и комнату",
      (del_album.id, True) not in win._network_sessions
      and not any(r.album_id == del_album.id for r in ROOMS))
check("удалённого альбома нет в базе", find_album(del_album.id) is None)

try:
    win._network_overlay.open_for(net_album)
    check("open_for сетевого мастера запрещён", False)
except RuntimeError:
    check("open_for сетевого мастера запрещён", True)

# ============================================================
print("--- 9. Смоук main.py ---")
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
try:
    proc = subprocess.run(
        [sys.executable, "main.py"], cwd=str(APP), env=env,
        capture_output=True, text=True, timeout=20,
    )
    out = proc.stdout + proc.stderr
    check("main.py без traceback", "Traceback" not in out)
except subprocess.TimeoutExpired as e:
    # Приложение работает, пока его не убить — это норма; важен вывод
    out = (e.stdout or "") + (e.stderr or "")
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    check("main.py жил до таймаута (не упал)", True)
check("main.py без предупреждений Qt",
      "QPainter::begin" not in out and "Painter not active" not in out
      and "Traceback" not in out)

# ============================================================
print()
print(f"ИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    print("Провалены:")
    for name in FAIL:
        print(f"  - {name}")
sys.exit(1 if FAIL else 0)
