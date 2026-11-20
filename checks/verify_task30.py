"""Задача 30: режимы «Локально/Облачно», «Выгрузить», БД в профиле.

Покрывает:
  1. Переключатель режима (кнопка-БД в сайдбаре): клик меняет
     Локально ↔ Облачно; в «Облачно» рабочая зона — «В разработке»,
     поиск выключен, кнопка отмечена (checked); надпись в верхней
     полосе справа («Локально»/«Облачно»); обратное переключение
     возвращает РОВНО ту же страницу; из облака открылись «Комнаты» —
     возврат тоже в облако; локальные действия возвращают «Локально».
  2. Кнопка «Выгрузить» на странице альбома: слева от
     «Редактировать», неактивна (клики невозможны), подсказка
     «В разработке».
  3. Профиль: вкладка «Настройки» переименована в «Данные», добавлена
     новая «Настройки» с «Экспортировать БД»/«Импортировать БД»
     (проводники QFileDialog); экспорт — ZIP (library.db + covers/);
     импорт ZIP и «голого» .db заменяет локальное наполнение (альбомы,
     исполнители, обложки возвращаются); битые файлы дают красную
     ошибку и НЕ меняют базу; база без аккаунтов — возврат к входу;
     сигнал db_imported обновляет главную и возвращает «Локально».

ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
"""

import os
import shutil
import sqlite3
import sys
import zipfile
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

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
)
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

from app.store import STORE
from checks.fixtures.library import populate_library

populate_library(STORE)
from app.ui.main_window import MainWindow

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


# --- Данные: демо-библиотека (после стирания data/) + аккаунт -------------
STORE.register_user("Георгий", "1")
STORE.set_current_user(STORE.find_user("Георгий"))

TMP = APP / "_t30_tmp"
TMP.mkdir(exist_ok=True)

N_ALBUMS = len(STORE.albums)     # 8 демо-альбомов
N_ARTISTS = len(STORE.artists)   # 10 демо-исполнителей

# Файл обложки — проверим, что экспорт/импорт переносит и картинки.
# Привязываем её к альбому ДО создания окна: при старте чистка
# осиротевших картинок (Task 31) удалила бы файл, на который база
# ещё не ссылается
COVERS = APP / "data" / "covers"
COVERS.mkdir(parents=True, exist_ok=True)
(COVERS / "probe_cover.png").write_bytes(b"\x89PNG-fake-cover")
STORE.set_album_cover(STORE.albums[0], "data/covers/probe_cover.png")

win = MainWindow()

# Оповещения — тосты (Task 31): помощник чтения последнего тоста
def last_toast():
    active = win.toasts.active
    return active[0] if active else None

def toasts_clear():
    win.toasts.clear()
    QTest.qWait(50)

win.resize(1200, 800)
win.show()
QTest.qWait(200)

# ============================================================
print("--- 1. Метка режима в верхней полосе ---")
lbl = win.top_bar.mode_label
check("метка существует и «Локально»", lbl.text() == "Локально")
search = win.top_bar.search_input
lbl_x = lbl.mapTo(win, QPoint(0, 0)).x()
search_right = search.mapTo(win, QPoint(0, 0)).x() + search.width()
check("метка СПРАВА от поиска", lbl_x > search_right)
check("метка у правого края полосы",
      win.top_bar.width() - 16 - lbl.width() - lbl_x <= 4)

# ============================================================
print("--- 2. Кнопка-БД в сайдбаре ---")
btn = win.sidebar.btn_mode
check("кнопка существует", btn is not None)
check("квадрат 40×40, как соседи",
      btn.width() == 40 and btn.height() == 40)
check("между профилем и «+»",
      btn.x() > win.sidebar.btn_profile.x()
      and win.sidebar.btn_add.x() > btn.x() + btn.width())
check("checkable, по умолчанию не отмечена",
      btn.isCheckable() and not btn.isChecked())
check("подсказка называет текущий режим", "Локально" in btn.toolTip())

# ============================================================
print("--- 3. Переключение в «Облачно» ---")
QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
QTest.qWait(100)
check("надпись сменилась на «Облачно»",
      win.top_bar.mode_label.text() == "Облачно")
check("рабочая зона — заглушка",
      win.pages.currentWidget() is win.cloud_page)
check("кнопка отмечена (checked)", btn.isChecked())
check("подсказка теперь про «Облачно»", "Облачно" in btn.toolTip())
check("сайдбар и полоса на месте (это не оверлей)",
      win.sidebar.isVisible() and win.top_bar.isVisible())
dev = win.cloud_page.lbl_dev
check("текст «В разработке»", dev.text() == "В разработке")
check("крупный полупрозрачный шрифт (44px)",
      dev.font().pixelSize() == 44)
lc, pc = dev.geometry().center(), win.cloud_page.rect().center()
check("надпись по центру рабочей зоны",
      abs(lc.x() - pc.x()) <= 2 and abs(lc.y() - pc.y()) <= 2)
check("поиск выключен в облачном режиме", not search.isEnabled())
check("панель поиска скрыта", not win.search_panel.isVisible())

# Обратно — режим и надпись возвращаются
QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
QTest.qWait(100)
check("обратно: «Локально» в полосе",
      win.top_bar.mode_label.text() == "Локально")
check("обратно: главная в рабочей зоне",
      win.pages.currentWidget() is win.home_page)
check("обратно: кнопка не отмечена", not btn.isChecked())
check("обратно: поиск включён", search.isEnabled())

# ============================================================
print("--- 4. Возврат на ТУ ЖЕ страницу ---")
album0 = STORE.albums[0]
win.open_album(album0)
QTest.qWait(50)
check("открыт альбом", win.pages.currentWidget() is win.album_page)
win.set_view_mode("cloud")
QTest.qWait(50)
check("из альбома в облако — заглушка",
      win.pages.currentWidget() is win.cloud_page)
win.set_view_mode("local")
QTest.qWait(50)
check("из облака — вернулись на страницу альбома",
      win.pages.currentWidget() is win.album_page)

# Локальные действия возвращают «Локально» автоматически
win.set_view_mode("cloud")
win.open_list("albums")
QTest.qWait(50)
check("открытие списка вернуло «Локально»",
      win._view_mode == "local"
      and win.pages.currentWidget() is win.list_page)
win.close_list()

win.set_view_mode("cloud")
win.open_create_choice()
QTest.qWait(50)
check("«+» из облака вернул «Локально» и открыл выбор",
      win._view_mode == "local"
      and win._choice_overlay is not None
      and win._choice_overlay.isVisible())
win._choice_overlay.close_overlay()
QTest.qWait(50)

# ============================================================
print("--- 5. Кнопка «Выгрузить» на странице альбома ---")
win.open_album(album0)
QTest.qWait(50)
up = win.album_page.btn_upload
check("кнопка «Выгрузить» есть", up is not None)
check("текст «Выгрузить»", up.text() == "Выгрузить")
check("неактивна", not up.isEnabled())
check("подсказка «В разработке»", up.toolTip() == "В разработке")
check("слева от «Редактировать»",
      up.x() + up.width() < win.album_page.btn_edit.x())
check("в одном ряду с «Редактировать»",
      abs(up.y() - win.album_page.btn_edit.y()) <= 6)

# ============================================================
print("--- 6. Профиль: вкладки «Данные» и «Настройки» ---")
win.open_profile()
ov = win._profile_overlay
QTest.qWait(250)
check("профиль открыт (залогинен)", ov.pages.currentIndex() == 2)
names = [b.text() for b in ov.tab_buttons]
check("вкладки: Главная/Данные/Настройки/Статистика",
      names == ["Главная", "Данные", "Настройки", "Статистика"])

ov.tab_buttons[1].click()
QTest.qWait(30)
check("индекс 1 — «Данные» (поля пароля здесь)",
      ov.tab_content.currentIndex() == 1
      and hasattr(ov, "in_new_password"))

ov.tab_buttons[2].click()
QTest.qWait(30)
check("индекс 2 — «Настройки» открыта",
      ov.tab_content.currentIndex() == 2)
check("кнопка «Экспортировать БД»",
      ov.btn_export_db.text() == "Экспортировать БД"
      and ov.btn_export_db.isVisible())
check("кнопка «Импортировать БД»",
      ov.btn_import_db.text() == "Импортировать БД"
      and ov.btn_import_db.isVisible())
check("обе кнопки — единственные на вкладке",
      len([w for w in ov.tab_content.currentWidget().findChildren(
          QPushButton) if w.isVisible()]) == 2)
check("строк статусов больше нет (Task 31: тосты)",
      not hasattr(ov, "lbl_db_status") and not hasattr(ov, "lbl_db_error"))
hints = [l.text() for l in ov.tab_content.currentWidget().findChildren(
    QLabel) if l.objectName() == "fieldLabel"]
check("пояснение про ZIP и замену наполнения",
      any("ZIP" in t and "заменяет" in t for t in hints))

ov.tab_buttons[3].click()
QTest.qWait(30)
check("индекс 3 — «Статистика»",
      ov.tab_content.currentIndex() == 3
      and ov.lbl_stat_count.text().startswith("Оценено альбомов"))
ov.tab_buttons[2].click()
QTest.qWait(30)

# ============================================================
print("--- 7. Экспорт БД (ZIP: база + обложки) ---")
EXPORT_ZIP = TMP / "выгрузка-библиотеки"   # без расширения — добавится .zip
_orig_save = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = (
    staticmethod(lambda *a, **k: (str(EXPORT_ZIP), "База Music Rating (*.zip)"))
)
QTest.mouseClick(ov.btn_export_db, Qt.MouseButton.LeftButton)
QTest.qWait(300)
QFileDialog.getSaveFileName = _orig_save

zip_path = TMP / "выгрузка-библиотеки.zip"
check("файл создан с .zip", zip_path.is_file())
_t = last_toast()
check("тост «База сохранена»",
      _t is not None and _t.text == "База сохранена"
      and _t.kind == "success")
with zipfile.ZipFile(zip_path) as zf:
    entry_names = zf.namelist()
check("в архиве есть library.db", "library.db" in entry_names)
check("в архиве есть обложки", "covers/probe_cover.png" in entry_names)

# Содержимое выгруженной базы (через временный файл)
from app.store import EXPORT_DB_ENTRY as _DB_ENTRY  # noqa: E402

with zipfile.ZipFile(zip_path) as zf:
    zf.extract(_DB_ENTRY, str(TMP / "snap"))
snap = sqlite3.connect(str(TMP / "snap" / _DB_ENTRY))
snap_titles = {r[0] for r in snap.execute("SELECT title FROM albums")}
snap_users = {r[0] for r in snap.execute("SELECT username FROM users")}
snap.close()
check("в выгруженной базе все альбомы", len(snap_titles) == N_ALBUMS)
check("в выгруженной базе аккаунт Георгий", snap_users == {"Георгий"})

# ============================================================
print("--- 8. Импорт ZIP меняет локальное наполнение ---")
STORE.delete_album(STORE.albums[0])          # библиотека изменилась
# Обложка удалённого альбома больше не нужна: чистка осиротевших
# картинок (Task 31) убрала файл вместе с альбомом
check("обложка удалённого альбома вычищена с диска",
      not (COVERS / "probe_cover.png").is_file())
check("альбом удалён для теста", len(STORE.albums) == N_ALBUMS - 1)

_orig_open = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (str(zip_path), "База Music Rating (*.zip)")
)
QTest.mouseClick(ov.btn_import_db, Qt.MouseButton.LeftButton)
QTest.qWait(400)
QFileDialog.getOpenFileName = _orig_open

_t = last_toast()
check("тост «База импортирована»",
      _t is not None and _t.text == "База импортирована"
      and _t.kind == "success")
check("альбомы вернулись", len(STORE.albums) == N_ALBUMS)
check("исполнители на месте", len(STORE.artists) == N_ARTISTS)
check("обложка из архива распакована",
      (COVERS / "probe_cover.png").is_file())
check("сессия пережила импорт",
      STORE.current_user is not None
      and STORE.current_user.username == "Георгий")
check("сигнал db_imported: главная показана, стек очищен",
      win.pages.currentWidget() is win.home_page
      and win._nav_stack == [])
check("режим после импорта — «Локально»", win._view_mode == "local")
check("карточка профиля перечитана",
      ov.lbl_name.text() == "Георгий")

# ============================================================
print("--- 9. Импорт «голого» .db и битых файлов ---")
bare = TMP / "library.db"
shutil.copyfile(TMP / "snap" / _DB_ENTRY, bare)  # «голая» база из выгрузки
STORE.delete_album(STORE.albums[-1])         # снова меняем наполнение
error = STORE.import_library(bare)
check("голый .db импортирован без ошибок", error is None)
check("наполнение восстановлено", len(STORE.albums) == N_ALBUMS)

# Битые файлы: база НЕ меняется, ошибка текстом
bad_text = TMP / "not-a-db.txt"
bad_text.write_text("это точно не база", encoding="utf-8")
before = len(STORE.albums)
check("текстовый файл: ошибка",
      STORE.import_library(bad_text) is not None
      and len(STORE.albums) == before)

empty_zip = TMP / "empty.zip"
with zipfile.ZipFile(empty_zip, "w") as zf:
    zf.writestr("readme.txt", "нет базы внутри")
check("zip без library.db: ошибка",
      STORE.import_library(empty_zip) is not None
      and len(STORE.albums) == before)

# Через диалог: красный статус на вкладке «Настройки»
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (str(bad_text), "Все файлы (*)")
)
QTest.mouseClick(ov.btn_import_db, Qt.MouseButton.LeftButton)
QTest.qWait(300)
QFileDialog.getOpenFileName = _orig_open
_t = last_toast()
check("ошибка импорта — красный тост",
      _t is not None and _t.text != "" and _t.kind == "error")
check("наполнение не изменилось", len(STORE.albums) == before)

# ============================================================
print("--- 10. Импорт базы без аккаунтов → вход ---")
no_users = TMP / "no-users.db"
shutil.copyfile(bare, no_users)
conn = sqlite3.connect(str(no_users))
conn.execute("DELETE FROM users")
conn.execute("DELETE FROM meta WHERE key = 'current_user_id'")
conn.commit()
conn.close()
# Полный поток — через окно профиля (вход показывается обработчиком)
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (str(no_users), "База SQLite (*.db)")
)
QTest.mouseClick(ov.btn_import_db, Qt.MouseButton.LeftButton)
QTest.qWait(400)
QFileDialog.getOpenFileName = _orig_open
_t = last_toast()
check("импорт прошёл (тост успеха)",
      _t is not None and _t.text == "База импортирована"
      and _t.kind == "success")
check("аккаунтов нет — сессия снята", STORE.current_user is None)
check("профиль показал вход",
      ov.pages.currentIndex() == 0)
check("наполнение из базы без аккаунтов загружено",
      len(STORE.albums) == N_ALBUMS)
check("после импорта появился главный экран",
      win.pages.currentWidget() is win.home_page)

# ============================================================
QTest.qWait(100)
app.processEvents()
shutil.rmtree(TMP, ignore_errors=True)

print(f"\nИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    for name in FAIL:
        print(f"  FAIL: {name}")
    sys.exit(1)
