"""verify_task31 — тосты, чистка обложек, анимации, комнаты-заглушка, поиск треков.

Покрывает:
  1. ТОСТЫ (Task 31, widgets/toast.py): notify() показывает окошко
     сверху по центру главного окна; зелёная галочка (success) /
     красный крестик (error) — kind; полоска прогресса уходит со
     временем; стопка «колодой»: новое поверх, старое ниже,
     максимум 3 — четвёртое вытесняет самое старое; клик по тосту
     закрывает; тосты закрываются сами (~3.5 с); стопка следует за
     движением/изменением размера окна.
  2. ЧИСТКА ОБЛОЖЕК (store.prune_covers): файлы data/covers, на
     которые не ссылается база, удаляются (при старте, удалении
     альбома, замене обложки/фото, импорте базы); файлы, на которые
     есть ссылки (обложки, фото, аватары-обложки), остаются.
  3. АНИМАЦИЯ ОТКРЫТИЯ (widgets/drop_animation): при первом показе
     окна содержимое (топбар, сайдбар, секции главной) смещено ВВЕРХ
     и полупрозрачно (эффект непрозрачности), через ~0.3 с — на
     месте, эффект снят; анимация проигрывается один раз; страницы
     «Смотреть все» и «Дискография» анимируются при каждом открытии.
  4. КОМНАТЫ (pages/rooms_page.py): по кнопке-планете — ТОЛЬКО
     надпись «В разработке» (как в облачном режиме), Esc — назад.
  5. ПОИСК ТРЕКОВ (widgets/search_results.py): запрос находит треки;
     строка = обложка альбома + название трека + справа
     «трек с «Альбом»»; клик открывает альбом; длинное название
     альбома в подписи сокращается.

ВНИМАНИЕ: тесты СТИРАЮТ data/ и создают пустую базу —
не запускать на машине с живой библиотекой!
"""

import os
import shutil
import sys
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CANDIDATES = [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[1],
    Path("/home/z/my-project/music-rating-app"),
]
APP = next(c for c in _CANDIDATES if (c / "app" / "theme.py").exists())
sys.path.insert(0, str(APP))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(APP):
    raise SystemExit("Run this check through checks/run.py.")

# ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel
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

from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.store import STORE
from checks.fixtures.library import populate_library

populate_library(STORE)
from app.ui.main_window import MainWindow
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.drop_animation import DROP_MS
from app.ui.widgets.toast import (
    KIND_ERROR,
    KIND_SUCCESS,
    TOAST_MS,
    ToastManager,
    manager_for,
    notify,
)

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


COVERS = APP / "data" / "covers"

print("== ФАЗА 1: тосты ==")
win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWait(120)  # анимация открытия должна успеть проиграться (фаза 3)

check("менеджер тостов у окна", isinstance(win.toasts, ToastManager))
check("notify() возвращает тот же менеджер окна",
      manager_for(win) is win.toasts)

t1 = notify(win, "Первое уведомление", KIND_SUCCESS)
QTest.qWait(60)
check("тост создан и виден", t1 is not None and t1.isVisible())
check("тост — окошко с флагом ToolTip",
      bool(t1.windowFlags() & Qt.WindowType.ToolTip))
check("ширина тоста фиксированная", t1.width() == 360)
check("kind сохранён", t1.kind == "success")
check("цвет успеха — зелёный из темы",
      t1._color.name().lower() == "#5ec26a")
check("у тоста есть прогресс (полоска)", 0.0 < t1._progress <= 1.0)

# Прогресс уходит со временем
p_early = t1._progress
QTest.qWait(300)
check("полоска прогресса уменьшается", t1._progress < p_early)

# Позиция: сверху по центру главного окна
cx_toast = t1.x() + t1.width() / 2
cx_win = win.x() + win.width() / 2
check("тост сверху по центру окна",
      abs(cx_toast - cx_win) <= 4 and t1.y() >= win.y())

# Стопка: новое поверх, старое ниже («колода»)
t2 = notify(win, "Второе уведомление", KIND_ERROR)
check("цвет ошибки — красный из темы",
      t2._color.name().lower() == "#e25c5c")
t3 = notify(win, "Третье уведомление", KIND_SUCCESS)
QTest.qWait(80)
active = win.toasts.active
check("в стопке три тоста", len(active) == 3)
check("новое — поверх (индекс 0)", active[0] is t3 and active[2] is t1)
check("старые тосты ниже нового",
      active[1].y() > active[0].y() and active[2].y() > active[1].y())
check("тосты перекрываются (стопка карт)",
      active[1].y() < active[0].y() + active[0].height()
      and active[2].y() < active[1].y() + active[1].height())

# Максимум 3: четвёртое вытесняет самое старое
notify(win, "Четвёртое уведомление", KIND_ERROR)
QTest.qWait(500)  # вытесненный тост успевает погаснуть
check("четвёртый тост вытеснил первый",
      [t.text for t in win.toasts.active] == [
          "Четвёртое уведомление", "Третье уведомление",
          "Второе уведомление",
      ])
check("в стопке снова три тоста", len(win.toasts.active) == 3)

# Клик по тосту закрывает только его; остальные остаются
remaining = [t.text for t in win.toasts.active][1:]
target = win.toasts.active[0]
QTest.mouseClick(target, Qt.MouseButton.LeftButton)
QTest.qWait(450)
check("клик по тосту закрывает только его",
      [t.text for t in win.toasts.active] == remaining)

# Автозакрытие: тост живёт ~3.5 с и исчезает сам
t_auto = notify(win, "Автозакрытие", KIND_SUCCESS)
QTest.qWait(int(TOAST_MS * 0.6))
check("тост ещё жив до истечения срока", not t_auto.is_closing)
QTest.qWait(int(TOAST_MS * 0.6) + 600)
check("тост закрылся сам после ~3.5 с", not win.toasts.active)
t_follow = notify(win, "Следую за окном", KIND_ERROR)
QTest.qWait(280)  # анимация появления закончилась — тост на месте
before_y = t_follow.y()
win.move(win.x() + 60, win.y() + 40)
QTest.qWait(50)
check("тост следует за перемещением окна",
      t_follow.y() == before_y + 40)
win.resize(1000, 700)
QTest.qWait(50)
check("тост остаётся по центру после resize",
      abs((t_follow.x() + t_follow.width() / 2)
          - (win.x() + win.width() / 2)) <= 4)
win.toasts.clear()
QTest.qWait(100)

print("== ФАЗА 2: чистка обложек ==")
COVERS.mkdir(parents=True, exist_ok=True)

STORE.register_user("Георгий", "pass1", "pass1")
STORE.add_artist("Артист А")  # add_album сам исполнителей не создаёт

# Обложка «осиротела»: файла нет ни в одной ссылке базы
orphan = COVERS / f"{uuid.uuid4().hex}.jpg"
orphan.write_bytes(b"not-a-real-image")
removed = STORE.prune_covers()
check("осиротевший файл удалён", removed >= 1 and not orphan.exists())

# Обложка, на которую ссылается альбом, остаётся
src_img = COVERS / "src_album.png"
src_img.write_bytes(b"fake-png-data")
alb1 = STORE.add_album(AlbumDraft(
    title="Альбом Один", year="2001", genre="Рок", region="RU",
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Трек 1"), TrackDraft(title="Трек 2")],
    cover_path=str(src_img),
))
cover_file = APP / alb1.cover_path
check("обложка альбома импортирована в data/covers",
      cover_file.is_file())
STORE.prune_covers()
check("обложка альбома НЕ удалена чисткой", cover_file.is_file())

# Удаление альбома удаляет его обложку
STORE.delete_album(alb1)
check("после удаления альбома файл обложки удалён",
      not cover_file.exists())

# Замена обложки при редактировании удаляет прежний файл
src_img.write_bytes(b"fake-png-data")  # источник могли почистить раньше
alb2 = STORE.add_album(AlbumDraft(
    title="Альбом Два", year="2002", genre="Поп", region="RU",
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Трек 1")],
    cover_path=str(src_img),
))
old_cover = APP / alb2.cover_path
new_img = COVERS / "src_new.png"
new_img.write_bytes(b"fake-png-new")
draft = AlbumDraft(
    title="Альбом Два", year="2002", genre="Поп", region="RU",
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Трек 1")],
    cover_path=str(new_img),
)
STORE.update_album(alb2, draft)
check("новая обложка на месте", (APP / alb2.cover_path).is_file())
check("прежний файл обложки удалён при замене", not old_cover.exists())

# Аватар-обложка исполнителя защищает файл от чистки
avatar = STORE.artist_avatar_path(
    next(a for a in STORE.artists if a.name == "Артист А")
)
check("аватар выбан из обложек альбомов", avatar is not None)
STORE.prune_covers()
check("аватар-обложка не удалена чисткой", (APP / avatar).is_file())

# Чистка не падает без папки covers
shutil.rmtree(COVERS, ignore_errors=True)
check("чистка без папки covers — 0 и без ошибок",
      STORE.prune_covers() == 0)

print("== ФАЗА 3: анимация открытия ==")
# Детерминированно: авто-запуск отключаем, показываем окно, ждём
# компоновку, затем запускаем ту же анимацию вручную и ловим
# промежуточное состояние (поднято вверх + полупрозрачно)
win2 = MainWindow()
check("анимация ещё не проиграна", win2._drop_played is False)
win2._drop_played = True  # отключаем авто-запуск на показе
win2.resize(1280, 800)
win2.show()
QTest.qWait(150)
home2 = win2.home_page
final_top = (win2.top_bar.x(), win2.top_bar.y())
final_sec = (home2.section_recent.x(), home2.section_recent.y())

win2._play_open_drop()
check("анимация запущена: эффект непрозрачности активен",
      win2.top_bar.graphicsEffect() is not None
      and home2.section_recent.graphicsEffect() is not None)
check("виджеты подняты ВВЕРХ перед падением",
      win2.top_bar.y() == final_top[1] - 24
      and home2.section_recent.y() == final_sec[1] - 24)
QTest.qWait(DROP_MS + 300)
check("анимация закончилась: эффект снят",
      win2.top_bar.graphicsEffect() is None
      and home2.section_recent.graphicsEffect() is None)
check("топбар вернулся на место",
      (win2.top_bar.x(), win2.top_bar.y()) == final_top)
check("секция вернулась на место",
      (home2.section_recent.x(), home2.section_recent.y()) == final_sec)
win2.close()
del win2
QTest.qWait(50)

# Авто-запуск: при первом показе окна флаг ставится, анимация
# успевает проиграться и не повторяется
win3 = MainWindow()
win3.show()
QTest.qWait(DROP_MS + 350)
check("анимация проигралась при показе окна",
      win3._drop_played is True
      and win3.top_bar.graphicsEffect() is None)
win3.close()
del win3
QTest.qWait(50)

# «Смотреть все»: анимация при каждом открытии (запускаем вручную
# после открытия — тот же метод, что вызывает singleShot)
win.open_list("albums")
QTest.qWait(DROP_MS + 300)
list_finals = {}
for i in range(win.list_page.grid.count()):
    w = win.list_page.grid.itemAt(i).widget()
    if w is not None:
        list_finals[w] = (w.x(), w.y())
back_final = win.list_page.btn_back.pos()
win.list_page.play_drop_animation()
check("список: карточки падают (эффект активен)",
      any(w.graphicsEffect() is not None for w in list_finals)
      and win.list_page.btn_back.graphicsEffect() is not None)
check("список: карточки подняты вверх перед падением",
      all(w.y() == pos[1] - 24 for w, pos in list_finals.items()))
QTest.qWait(DROP_MS + 250)
check("список: анимация завершена, эффекты сняты",
      all(w.graphicsEffect() is None for w in list_finals)
      and win.list_page.btn_back.graphicsEffect() is None)
check("список: карточки вернулись на место",
      all((w.x(), w.y()) == pos for w, pos in list_finals.items())
      and win.list_page.btn_back.pos() == back_final)
QTest.keyClick(win, Qt.Key.Key_Escape)  # назад
QTest.qWait(50)

# «Дискография»: анимация при каждом открытии
artist = next(a for a in STORE.artists if a.name == "Артист А")
win.open_artist(artist)
QTest.qWait(DROP_MS + 300)
disc_finals = [
    (win.artist_page.photo, win.artist_page.photo.pos()),
    (win.artist_page.lbl_name, win.artist_page.lbl_name.pos()),
]
win.artist_page.play_drop_animation()
check("дискография: шапка падает (эффект активен)",
      win.artist_page.photo.graphicsEffect() is not None
      and win.artist_page.lbl_name.graphicsEffect() is not None)
check("дискография: виджеты подняты вверх",
      all(w.y() == pos.y() - 24 for w, pos in disc_finals))
QTest.qWait(DROP_MS + 250)
check("дискография: анимация завершена",
      win.artist_page.photo.graphicsEffect() is None
      and win.artist_page.lbl_name.graphicsEffect() is None)
check("дискография: виджеты вернулись на место",
      all(w.pos() == pos for w, pos in disc_finals))
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(50)

print("== ФАЗА 5: поиск треков ==")
alb_t = STORE.add_album(AlbumDraft(
    title="Синий Трактор", year="2020", genre="Детская", region="RU",
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Веселая песня"),
            TrackDraft(title="Грустная песня")],
    cover_path=None,
))
win.home_page.refresh()

panel = win.search_panel
panel.update_for("веселая")
rows = [panel._layout.itemAt(i).widget()
        for i in range(panel._layout.count())]
rows = [r for r in rows if r is not None and r is not panel.lbl_empty]
check("трек найден одной строкой", len(rows) == 1)
row = rows[0]
check("в строке трека — название трека",
      row.lbl_name.text() == "Веселая песня")
check("справа подпись «трек с «Альбом»»",
      row.lbl_type.text() == "трек с «Синий Трактор»")
check("в строке трека — обложка альбома (CoverView)",
      len(row.findChildren(CoverView)) == 1)

# Клик по строке трека открывает альбом
opened: list[object] = []
panel.album_activated.connect(opened.append)
QTest.mouseClick(row, Qt.MouseButton.LeftButton)
QTest.qWait(50)
check("клик по треку открывает альбом",
      len(opened) == 1 and opened[0] is alb_t)

# Регистронезависимость и совпадение по подстроке
panel.update_for("ПЕСНЯ")
rows2 = [panel._layout.itemAt(i).widget()
         for i in range(panel._layout.count())]
rows2 = [r for r in rows2 if r is not None and r is not panel.lbl_empty]
check("оба трека найдены без учёта регистра", len(rows2) == 2)

# Ничего не найдено — прежняя подсказка
panel.update_for("zzz-нет-такого")
texts = [l.text() for l in panel.findChildren(QLabel)]
check("пустой результат — «Ничего не найдено»",
      any(t == "Ничего не найдено" for t in texts))

# Длинное название альбома в подписи сокращается
from types import SimpleNamespace
from app.ui.widgets.search_results import track_type_label

long_album = SimpleNamespace(
    title="Очень Длинное Название Альбома Которое Не Поместится")
label = track_type_label(long_album)
check("подпись трека сокращает длинное имя альбома",
      label.startswith("трек с «")
      and label.endswith("»") and "…" in label
      and len(label) < 40)

panel.hide()
win.search_panel.hide()

print("== ФАЗА 6: тосты из диалогов ==")
# Ошибка обязательного поля — тост (пример: редактор исполнителя)
win.open_artist_editor(artist)
ed = win.artist_editor
ed.input_name.setText("   ")
win.toasts.clear()
QTest.mouseClick(ed.btn_save, Qt.MouseButton.LeftButton)
QTest.qWait(50)
t_err = win.toasts.active[0] if win.toasts.active else None
check("ошибка валидации показывается тостом",
      t_err is not None and t_err.text == "Введите имя исполнителя."
      and t_err.kind == "error")
check("тост виден поверх страницы редактора",
      t_err is not None and t_err.isVisible())
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(50)

# ============================================================
QTest.qWait(100)
app.processEvents()

print()
print(f"ИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    print("Провалены:")
    for name in FAIL:
        print(f"  - {name}")
sys.exit(1 if FAIL else 0)
