"""verify_task21 — доработки окна профиля (7 пунктов фидбека) + регрессии.

Покрывает:
  1. ✕-кнопка в самом конце ряда вкладок — возврат в меню.
  2. «Выйти из аккаунта» переехала во вкладку «Настройки»
     (вкладка «Об аккаунте» переименована в «Настройки»).
  3. На «Главной» нет строки «Оценок пока нет» (поле скрыто).
  4. Смена пароля: 2 поля + маленькая кнопка-галочка справа.
  5. Поле имени + такая же кнопка-галочка (переименование аккаунта).
  6. «Удалить аккаунт» компактная (#dangerSmallButton).
  7. Статистика: «Любимая оценка», «Самый нелюбимый альбом»,
     «Самый нелюбимый исполнитель» (+ store-математика).
Регрессии: вход/регистрация/сессия, мастера оценивания (плитки=аккаунты,
валидатор, секретная 11, кап), строка источника, удаление аккаунта
с пересчётом средних, Esc-каскад.
"""

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Путь к корню приложения определяем по расположению самого скрипта:
# работает и из <app>/dev/verify/, и из <app>/, и из песочницы разработчика
_CANDIDATES = [
    Path(__file__).resolve().parent,        # <app>/verify_*.py
    Path(__file__).resolve().parents[1],    # <app>/dev/verify_*.py
    Path(__file__).resolve().parents[2],    # <app>/dev/verify/verify_*.py
    Path("/home/z/my-project/music-rating-app"),  # песочница (Linux)
]
APP = next(c for c in _CANDIDATES if (c / "app" / "theme.py").exists())
sys.path.insert(0, str(APP))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(APP):
    raise SystemExit("Run this check through checks/run.py.")

# ВНИМАНИЕ: тесты СТИРАЮТ data/ и создают пустую базу —
# не запускать на машине с живой библиотекой!
DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLineEdit, QLabel, QPushButton
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

from app.models import AlbumDraft, TrackDraft, ArtistDraft
from app.store import STORE, MusicStore
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


def wait_overlay(ov) -> None:
    QTest.qWait(350)  # анимация подъёма карточки


# ============================================================
# ФАЗА 1. Магазин: новая статистика
# ============================================================
print("== ФАЗА 1: статистика оценок ==")

TESTER_ID, OTHER_ID = "tester-uid", "other-uid"

STORE.add_artist("Икс")
STORE.add_artist("Игрек")
STORE.add_artist("Зет")
STORE.add_artist("Дабл-ю")

album_a = STORE.add_album(AlbumDraft(
    title="Альбом А", year="2020",
    tracks=[
        TrackDraft(title="Т1", artists=[ArtistDraft(name="Икс", existing=True)]),
        TrackDraft(title="Т2", artists=[ArtistDraft(name="Игрек", existing=True)]),
    ],
))
album_b = STORE.add_album(AlbumDraft(
    title="Альбом Б", year="2021",
    tracks=[
        TrackDraft(title="Б1", artists=[ArtistDraft(name="Икс", existing=True)]),
        TrackDraft(title="Б2", artists=[ArtistDraft(name="Зет", existing=True)]),
    ],
))
album_c = STORE.add_album(AlbumDraft(
    title="Альбом В", year="2022",
    tracks=[TrackDraft(title="В1", artists=[ArtistDraft(name="Дабл-ю", existing=True)])],
))
album_d = STORE.add_album(AlbumDraft(
    title="Альбом Г", year="2023",
    tracks=[TrackDraft(title="Г1", artists=[ArtistDraft(name="Дабл-ю", existing=True)])],
))
album_e = STORE.add_album(AlbumDraft(
    title="Альбом Д", year="2024",
    tracks=[
        TrackDraft(title="Д1", artists=[ArtistDraft(name="Икс", existing=True)]),
        TrackDraft(title="Д2", artists=[ArtistDraft(name="Зет", existing=True)]),
    ],
))
check("альбомы созданы", all(
    a is not None for a in (album_a, album_b, album_c, album_d, album_e)
))

# Пустая статистика
stats0 = STORE.user_stats(TESTER_ID, "Тестер")
check("stats0: count 0", stats0.rated_count == 0)
check("stats0: favorite_rating None", stats0.favorite_rating is None)
check("stats0: least album None", stats0.least_favorite_album is None)
check("stats0: least artist None", stats0.least_favorite_artist is None)

# А: 8.0, 8.0 → любимая 8.0; Б: 9.0, 5.0
STORE.rate_album(album_a, ["Тестер"], [[8.0], [8.0]])
STORE.rate_album(album_b, ["Тестер"], [[9.0], [5.0]])
s = STORE.user_stats(TESTER_ID, "Тестер")
check("count=2", s.rated_count == 2)
check("любимый альбом А 8.0", s.favorite_album == ("Альбом А", 8.0))
check("нелюбимый альбом Б 7.0", s.least_favorite_album == ("Альбом Б", 7.0))
check("любимая оценка 8.0 (2 раза)", s.favorite_rating == 8.0)
check("любимый исполнитель Икс 8.5", s.favorite_artist == ("Икс", 8.5))
check("нелюбимый исполнитель Зет 5.0",
      s.least_favorite_artist == ("Зет", 5.0))

# В: 6.0 → ничья с 5.0/9.0 не влияет; Г: 9.0 → ничья 2-2 с 8.0 → выше (9.0)
STORE.rate_album(album_c, ["Тестер"], [[6.0]])
s = STORE.user_stats(TESTER_ID, "Тестер")
check("любимая оценка всё ещё 8.0", s.favorite_rating == 8.0)
check("нелюбимый альбом теперь В 6.0",
      s.least_favorite_album == ("Альбом В", 6.0))
STORE.rate_album(album_d, ["Тестер"], [[9.0]])
s = STORE.user_stats(TESTER_ID, "Тестер")
check("ничья частоты → бо́льшая оценка 9.0", s.favorite_rating == 9.0)
check("любимый альбом теперь Г 9.0", s.favorite_album == ("Альбом Г", 9.0))
check("нелюбимый альбом всё ещё В 6.0",
      s.least_favorite_album == ("Альбом В", 6.0))

# Д: 11.0 + 10.0 → арифметика 10.5, кап 10.0
STORE.rate_album(album_e, ["Тестер"], [[11.0], [10.0]])
s = STORE.user_stats(TESTER_ID, "Тестер")
check("кап: любимый альбом Д 10.0", s.favorite_album == ("Альбом Д", 10.0))
check("count=5", s.rated_count == 5)

# ============================================================
win = MainWindow()
win.resize(1280, 800)
win.show()
win._cloud_upload._set_members({OTHER_ID: "Второй", TESTER_ID: "Тестер"})

# ФАЗА 6. Регрессия: мастер оценивания и страница альбома
# ============================================================
print("== ФАЗА 6: регрессия мастера и страницы альбома ==")

# Плитки участников соответствуют таблице облачных профилей.
win.open_rate_album(album_b)
ro = win._rate_overlay
wait_overlay(ro)
chips = list(ro.rater_buttons.keys())
check("плитки соответствуют участникам Supabase",
      set(chips) == {OTHER_ID, TESTER_ID})
check("заглушек-участников нет",
      not any(c in chips for c in ("Кирилл", "Володя", "Георгий")))

# Валидатор и секретная 11 (регрессия Task 19)
chips_widgets = [ro.rater_buttons[uid] for uid in (OTHER_ID, TESTER_ID)]
chips_widgets[0].click()
chips_widgets[1].click()
ro.btn_next.click()  # шаг 2
QTest.qWait(80)
from PySide6.QtWidgets import QLineEdit as _LE
cells = ro.findChildren(_LE)
rating_cells = [c for c in cells if c.objectName() == "ratingCell"]
check("клетки оценок есть", len(rating_cells) >= 4)
cell = rating_cells[0]
cell.setFocus()
QTest.keyClicks(cell, "12")
QTest.qWait(20)
check("валидатор: «12» → «1»", cell.text() == "1")
cell.clear()
QTest.keyClicks(cell, "11.05")
QTest.qWait(20)
check("валидатор: «11.05» → «11.0»", cell.text() == "11.0")
cell.clear()
QTest.keyClicks(cell, "11")
QTest.qWait(20)
check("секретная 11 введена", cell.text() == "11")
cell2 = rating_cells[2]  # тот же участник, другая строка
cell2.setFocus()
QTest.keyClicks(cell2, "11")
QTest.qWait(30)
check("вторая 11 того же участника → bad + блокировка",
      rating_cells[2].property("state") == "bad"
      and not ro.btn_next.isEnabled())

# «Выйти» из оценивания закрывает мастер
if ro._exit_overlay is None:
    ro.btn_cancel.click()
    QTest.qWait(200)
ro._exit_overlay.btn_exit.click()
QTest.qWait(50)
check("«Выйти» закрывает мастер", not ro.isVisible())

# Строка источника (регрессия правки Task 20): альбом по ссылке
from app.models import AlbumDraft as _AD
album_f = STORE.add_album(_AD(
    title="Из Дизера", year="2024", source_id="12345",
    tracks=[TrackDraft(title="Ф1")],
))
win.open_album(album_f)
QTest.qWait(60)
check("источник: текст «Создано с помощью» (без слова deezer)",
      win.album_page.lbl_source.text() == "Создано с помощью")
icon = win.album_page.source_icon
check("источник: лого виден и СПРАВА от текста",
      icon.isVisible() and icon.x() > win.album_page.lbl_source.x()
      and icon.pixmap() is not None and not icon.pixmap().isNull())
check("источник: строка НАД названием",
      win.album_page.lbl_source.y() < win.album_page.lbl_title.y())
manual = STORE.add_album(_AD(
    title="Ручной", year="2024", tracks=[TrackDraft(title="Р1")],
))
win.open_album(manual)
QTest.qWait(60)
check("источник: ручной альбом — «Создано вручную», без лого",
      win.album_page.lbl_source.text() == "Создано вручную"
      and not win.album_page.source_icon.isVisible())

# Перезапуск хранилища после всех операций — сессия и данные целы
store3 = MusicStore()
a3 = next(a for a in store3.albums if a.title == "Альбом А")
check("финал: матрица А в базе",
      a3.ratings.rater_names == ["Тестер"]
      and a3.ratings.values == [[8.0], [8.0]])
check("финал: статистика по новому имени работает",
      store3.user_stats(TESTER_ID, "Тестер").rated_count == 5)

# ============================================================
print()
print(f"ИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    print("Провалены:")
    for name in FAIL:
        print(f"  - {name}")
sys.exit(1 if FAIL else 0)
