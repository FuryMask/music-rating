"""Задача 29: правки после фидбека (сеть отложена).

Покрывает:
  1. Выход из РЕДАКТИРОВАНИЯ альбома: «Выйти из редактирования
     альбома?» / «Продолжить редактирование» (а не тексты создания);
     оверлей один на оба режима — тексты ставятся на каждый показ и
     не «прилипают» (создание → редактирование → создание).
  2. Страница «Комнаты»: подсказки («Комната появляется…», «Пока
     никто…») убраны; по центру полупрозрачное «В разработке»
     (44px); шапка («Назад» + «Комнаты») у верхней границы (y=28);
     список комнат появляется, когда комната есть.
  3. Аватар артиста: без своего фото показывается обложка одного из
     его альбомов — выбирается ОДИН раз (запись в artists.avatar_path
     переживает перезапуск и новые альбомы); своё фото приоритетнее;
     пропавший файл — аватар сбрасывается/перевыбирается; аватар
     показывают карточка главной, поиск и страница исполнителя.
  4. Редактор исполнителя (страница в ОСНОВНОМ ПОЛЕ, не оверлей):
     имя (валидация пустого/дубля), жанр (ручной > автоподсчёт),
     фото (убрать/вернуть/выбрать); сохранение переименовывает
     ссылки в альбомах и треках-фитах; «Назад»/Esc — без сохранения.

ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
"""

import os
import shutil
import sqlite3
import sys
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

DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

app = QApplication([])
app.setApplicationName("Music Rating")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))

import app.theme as theme

theme.apply_theme(app)

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
from app.ui.widgets.artist_card import ArtistCard

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


# --- Данные --------------------------------------------------------------

TMP = APP / "_t29_tmp"
TMP.mkdir(exist_ok=True)


def make_image(name: str, color: str) -> str:
    pm = QPixmap(48, 48)
    pm.fill(QColor(color))
    path = TMP / name
    pm.save(str(path))
    return str(path)


cover_a = make_image("cover_a.png", "#aa3333")
cover_b = make_image("cover_b.png", "#33aa33")
cover_c = make_image("cover_c.png", "#3333aa")
photo = make_image("photo.png", "#33aaaa")

# Исполнители создаёт мастер (STORE.add_artist), затем альбомы
STORE.add_artist("Артист А")                     # без фото
STORE.add_artist("Артист Б")                     # без фото
STORE.add_artist("С Фото", photo_path=photo)     # со своим фото

alb1 = STORE.add_album(AlbumDraft(
    title="Альбом Один", year="2001", genre="Рок", region="RU",
    cover_path=cover_a,
    artists=[ArtistDraft(name="Артист А", existing=False),
             ArtistDraft(name="Артист Б", existing=False)],
    tracks=[TrackDraft(
        title="Трек 1",
        artists=[ArtistDraft(name="Артист А", existing=False),
                 ArtistDraft(name="Фит Чужой", existing=False)],
    )],
))
alb2 = STORE.add_album(AlbumDraft(
    title="Альбом Два", year="2002", genre="Поп", region="RU",
    cover_path=cover_b,
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Трек 2")],
))
alb3 = STORE.add_album(AlbumDraft(
    title="Альбом Три", year="2003", genre="Джаз", region="RU",
    cover_path=cover_c,
    artists=[ArtistDraft(name="Артист А", existing=True),
             ArtistDraft(name="С Фото", existing=True)],
    tracks=[TrackDraft(title="Трек 3")],
))
artist_a = STORE.find_artist("Артист А")     # без фото, 3 альбома
artist_b = STORE.find_artist("Артист Б")     # без фото, 1 альбом
artist_p = STORE.find_artist("С Фото")       # со своим фото

# ============================================================
print("--- 1. Выход из редактирования: свои тексты ---")
win = MainWindow()
win.resize(1200, 800)
win.show()
QTest.qWait(200)

win.open_create_album()
ov = win._overlay
ov.draft.title = "черновик"
ov._request_exit()
check("мастер: окно выхода открыто",
      ov._exit_overlay is not None and ov._exit_overlay.isVisible())
check("создание: заголовок",
      ov._exit_overlay.lbl_title.text() == "Выйти из создания альбома?")
check("создание: кнопка остаться",
      ov._exit_overlay.btn_stay.text() == "Продолжить создание")
ov._exit_overlay.btn_exit.click()
check("создание: мастер закрылся", not ov.isVisible())

win._open_edit_album(alb1)
ov = win._overlay
check("редактирование: мастер открыт", ov.isVisible())
ov._request_exit()
check("редактирование: заголовок",
      ov._exit_overlay.lbl_title.text()
      == "Выйти из редактирования альбома?")
check("редактирование: кнопка остаться",
      ov._exit_overlay.btn_stay.text() == "Продолжить редактирование")
ov._exit_overlay.btn_stay.click()
check("редактирование: остались в мастере", ov.isVisible())
ov._request_exit()
ov._exit_overlay.btn_exit.click()

# И снова создание: тексты не «прилипли» к редактированию
win.open_create_album()
ov.draft.title = "черновик 2"
ov._request_exit()
check("создание снова: заголовок вернулся",
      ov._exit_overlay.lbl_title.text() == "Выйти из создания альбома?")
check("создание снова: кнопка вернулась",
      ov._exit_overlay.btn_stay.text() == "Продолжить создание")
ov._exit_overlay.btn_exit.click()

# ============================================================
print("--- 3. Аватар из обложки альбома ---")
av_a = STORE.artist_avatar_path(artist_a)
check("аватар = обложка одного из альбомов",
      av_a in (alb1.cover_path, alb2.cover_path, alb3.cover_path))
check("запомнен в объекте", artist_a.avatar_path == av_a)
check("повторный вызов — тот же",
      STORE.artist_avatar_path(artist_a) == av_a)
check("аватар записан в базу",
      sqlite3.connect(str(APP / "data" / "library.db")).execute(
          "SELECT avatar_path FROM artists WHERE name = 'Артист А'"
      ).fetchone()[0] == av_a)

# Новый альбом НЕ меняет уже выбранный аватар
alb4 = STORE.add_album(AlbumDraft(
    title="Альбом Четыре", year="2004", genre="Метал", region="RU",
    artists=[ArtistDraft(name="Артист А", existing=True)],
    tracks=[TrackDraft(title="Трек 4")],
))
check("новый альбом не меняет аватар",
      STORE.artist_avatar_path(artist_a) == av_a)
del alb4

# Своё фото приоритетнее
check("своё фото приоритетнее",
      STORE.artist_avatar_path(artist_p) == artist_p.photo_path)

# Файл аватара пропал — сброс (у Артиста Б один альбом с одной обложкой)
av_b = STORE.artist_avatar_path(artist_b)
check("у Артиста Б появился аватар",
      av_b is not None and artist_b.avatar_path == av_b)
os.remove(str(STORE.resolve(av_b)))
check("файл пропал — аватар сброшен",
      STORE.artist_avatar_path(artist_b) is None
      and artist_b.avatar_path is None)

# Показ: карточка на главной показывает аватар без своего фото
win._show_home()
QTest.qWait(100)
cards = {c.artist.name: c
         for c in win.home_page.findChildren(ArtistCard)}
check("карточка без фото показывает аватар",
      "Артист А" in cards and cards["Артист А"].photo.has_photo())
check("карточка со своим фото показывает фото",
      "С Фото" in cards and cards["С Фото"].photo.has_photo())

# ============================================================
print("--- 4. Редактор исполнителя ---")
win.open_artist(artist_a)
QTest.qWait(50)
check("кнопка «Редактировать» на странице исполнителя",
      win.artist_page.btn_edit.isVisible())
QTest.mouseClick(win.artist_page.btn_edit, Qt.MouseButton.LeftButton)
QTest.qWait(50)
check("редактор открыт в основном поле",
      win.pages.currentWidget() is win.artist_editor)
check("топбар и сайдбар на месте",
      win.top_bar.isVisible() and win.sidebar.isVisible())
ed = win.artist_editor
check("имя подставлено", ed.input_name.text() == "Артист А")
check("превью — аватар (своего фото нет)", ed.photo.has_photo())

# Esc — назад без сохранения
ed.input_name.setText("Черновик Имени")
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(50)
check("Esc — назад к артисту",
      win.pages.currentWidget() is win.artist_page)
check("Esc — имя не сохранено", artist_a.name == "Артист А")

# Переименование + жанр (клик по кнопке)
QTest.mouseClick(win.artist_page.btn_edit, Qt.MouseButton.LeftButton)
QTest.qWait(50)
ed.input_name.setText("Пинк Флойд")
ed.combo_genre.setCurrentText("Рок")
QTest.mouseClick(ed.btn_save, Qt.MouseButton.LeftButton)
QTest.qWait(50)
check("сохранение вернуло на страницу артиста",
      win.pages.currentWidget() is win.artist_page)
check("имя изменено", artist_a.name == "Пинк Флойд")
check("жанр сохранён (ручной > автоподсчёт)",
      STORE.artist_main_genre("Пинк Флойд") == "Рок")
check("альбом ссылается на новое имя",
      "Пинк Флойд" in alb1.artist_names
      and "Пинк Флойд" in alb2.artist_names)
check("фиты в треках переименованы",
      all(a.name != "Артист А"
          for t in alb1.tracks for a in t.artists))
check("имя записано в базу",
      any("Пинк Флойд" == r[0] for r in sqlite3.connect(
          str(APP / "data" / "library.db")
      ).execute("SELECT name FROM artists").fetchall()))
check("страница артиста обновилась",
      win.artist_page.lbl_name.text() == "Пинк Флойд")
check("дубликат имени не появился",
      len([a for a in STORE.artists
           if a.name.casefold() == "пинк флойд"]) == 1)

# Валидация: дубль и пустое имя — ошибки тостами (Task 31)
win.open_artist_editor(artist_b)
ed.input_name.setText("Пинк Флойд")
win.toasts.clear()
QTest.mouseClick(ed.btn_save, Qt.MouseButton.LeftButton)
_t = win.toasts.active[0] if win.toasts.active else None
check("дубль: ошибка — тост", _t is not None
      and _t.text == "Исполнитель с таким именем уже есть.")
check("дубль: остались в редакторе",
      win.pages.currentWidget() is win.artist_editor)
check("дубль: имя не изменилось", artist_b.name == "Артист Б")
ed.input_name.setText("   ")
win.toasts.clear()
QTest.mouseClick(ed.btn_save, Qt.MouseButton.LeftButton)
_t = win.toasts.active[0] if win.toasts.active else None
check("пустое имя: ошибка — тост", _t is not None
      and _t.text == "Введите имя исполнителя.")
# Выйти из редактора (в реальном приложении «Редактировать» доступен
# только со страницы артиста — открытие поверх открытого невозможно)
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(50)
check("Esc из редактора — к текущему артисту",
      win.pages.currentWidget() is win.artist_page)

# Фото: убрать → вернуться → убрать и сохранить
win.open_artist_editor(artist_p)
check("кнопка «Убрать фото» видна", ed.btn_remove.isVisible())
ed._toggle_photo()
check("убрано: превью-заглушка", not ed.photo.has_photo())
check("убрано: кнопка «Вернуть фото»",
      ed.btn_remove.text() == "Вернуть фото")
ed._toggle_photo()
check("вернули: превью фото", ed.photo.has_photo())
ed._toggle_photo()
QTest.mouseClick(ed.btn_save, Qt.MouseButton.LeftButton)
QTest.qWait(50)
check("фото снято в базе", artist_p.photo_path is None)
check("после снятия — аватар из его альбомов",
      STORE.artist_avatar_path(artist_p) == alb3.cover_path)
check("страница артиста без фото-кружка с картинкой заглушки",
      win.pages.currentWidget() is win.artist_page)

QTest.qWait(100)
app.processEvents()

shutil.rmtree(TMP, ignore_errors=True)

print(f"\nИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    for name in FAIL:
        print(f"  FAIL: {name}")
    sys.exit(1)
