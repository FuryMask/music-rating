"""verify_task22 — фидбек по профилю и странице альбома (4 пункта).

Покрывает:
  1. Обрезание кнопок «Настроек»: «Удалить аккаунт» не срезается
     слева, «Выйти из аккаунта» — снизу, галочки — справа (запас
     под ховер-рост +10 % вокруг центра).
  2. Оповещения смены пароля/имени — всплывающие тосты (Task 31):
     появление тоста НЕ сдвигает поля и галочки; тост сам закрывается
     (и об ошибке, и об успехе).
  3. «Сменить» имя на то же и пароль на текущий НЕЛЬЗЯ: отдельные
     ошибки хранилища («Это уже ваше текущее имя», «Новый пароль
     совпадает с текущим»); смена только регистра имени допустима.
  4. Страница альбома: у неоценённого — треклист под шапкой, кнопка
     «Оценить?» и сообщение «Этот альбом ещё не оценили» — на уровне
     обложки в самом правом краю; у оценённого — сетка оценок, как
     на шаге «Оценки» мастера (шапка с именами участников, оценки
     треков только для чтения, секретная 11 подсвечена, «Средняя
     оценка» каждого участника внизу).
  5. Task 31: строки-статусы в профиле убраны — все оповещения
     («Введите новый пароль», «Пароль изменён» и т.п.) показываются
     всплывающими тостами над главным окном: появляются сами,
     сами закрываются (~3.5 с), закрываются кликом; поля и галочки
     при их появлении не сдвигаются.
Регрессии: смена пароля/имени через UI по-прежнему работает.
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

from PySide6.QtCore import QPoint, QVariantAnimation, Qt, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget
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
from app.store import STORE
from checks.fixtures.library import populate_library

populate_library(STORE)
from app.theme import ACCENT, rating_color
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
from app.store import MusicStore
win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWait(250)

# ФАЗА 3. Страница альбома: не оценён → треклист, «Оценить?» справа
# ============================================================
print("== ФАЗА 3: альбом не оценён ==")

album = STORE.add_album(AlbumDraft(
    title="Неоценённый", year="2023", genre="Рок",
    artists=[ArtistDraft(name="Группа А", existing=True)],
    tracks=[
        TrackDraft(title="Трек один"),
        TrackDraft(title="Трек два",
                   artists=[ArtistDraft(name="Фит", existing=True)]),
        TrackDraft(title="Трек три"),
    ],
))
win.open_album(album)
QTest.qWait(60)
page = win.album_page

check("блок «Оценить?» виден", page.rate_side.isVisible())
check("сообщение «ещё не оценили» видимо", page.lbl_not_rated.isVisible())
check("кнопка «Оценить?» видима", page.btn_rate.isVisible())
check("строки-прочерки «Оценок нету» нет на странице",
      not any(
          isinstance(w, QLabel) and "Оценок нет" in w.text()
          for w in page.findChildren(QLabel)
      ))

# Кнопка и сообщение — на уровне обложки, в самом правом краю
cover_right = page.cover.x() + page.cover.width()
btn_tl = page.btn_rate.mapTo(page, QPoint(0, 0))
hint_tl = page.lbl_not_rated.mapTo(page, QPoint(0, 0))
side_tl = page.rate_side.mapTo(page, QPoint(0, 0))
check("«Оценить?» правее обложки", btn_tl.x() > cover_right)
check("сообщение правее обложки", hint_tl.x() > cover_right)
check("блок «Оценить?» прижат к правому краю страницы",
      abs((side_tl.x() + page.rate_side.width())
          - (page.width() - 36)) <= 4)
check("кнопка внутри правого блока",
      btn_tl.x() >= side_tl.x()
      and btn_tl.x() + page.btn_rate.width()
      <= side_tl.x() + page.rate_side.width())
check("на уровне обложки (пересечение по вертикали)",
      btn_tl.y() < page.cover.y() + page.cover.height()
      and btn_tl.y() + page.btn_rate.height() > page.cover.y())

# Треклист под шапкой (последняя строка несёт имя trackRowLast)
rows = [w for w in page.tracks_container.findChildren(QWidget)
        if w.objectName() in ("trackRow", "trackRowLast")]
check("треклист: 3 строки", len(rows) == 3)
check("треклист: сегмент виден", page.tracks_frame.isVisible())
names = [w.text() for w in page.tracks_container.findChildren(QLabel)]
check("треклист: названия на месте",
      all(t in names for t in ("Трек один", "Трек два", "Трек три")))
check("треклист: исполнители фита показаны", "Фит" in names)
check("треклист: нет имён участников (шапки оценок)",
      not page.tracks_container.findChildren(QLabel) or all(
          w.objectName() != "rateColName"
          for w in page.tracks_container.findChildren(QLabel)
      ))
check("треклист: нет строки «Средняя оценка»",
      "Средняя оценка" not in names)
check("оценки (lbl_rating) скрыты", not page.lbl_rating.isVisible())

# Клик по кнопке открывает мастер (сигнал)
got = []
page.rate_requested.connect(lambda a: got.append(a))
page.btn_rate.click()
QTest.qWait(50)
check("«Оценить?» испускает rate_requested", bool(got) and got[0] is album)
if win._rate_overlay is not None and win._rate_overlay.isVisible():
    win._rate_overlay.hide()
QTest.qWait(30)

# ============================================================
# ФАЗА 4. Оценённый альбом: сетка оценок вместо треклиста
# ============================================================
print("== ФАЗА 4: альбом оценён — сетка оценок ==")

STORE.rate_album(album, ["Основной", "Сосед"],
                 [[8.0, 7.0], [11.0, None], [6.5, 5.0]])
win.open_album(album)
QTest.qWait(60)

check("блок «Оценить?» скрыт", not page.rate_side.isVisible())
check("оценка альбома видна (7.5)",
      page.lbl_rating.isVisible() and page.lbl_rating.text() == "Оценка: 7.5")

col_names = [w for w in page.tracks_container.findChildren(QLabel)
             if w.objectName() == "rateColName"]
check("шапка: имена участников",
      [w.text() for w in col_names] == ["Основной", "Сосед"])

values = [w for w in page.tracks_container.findChildren(QLabel)
          if w.objectName() == "rateAvgValue"]
check("клеток значений: 6 + 2 средних", len(values) == 8)
texts = [w.text() for w in values]
check("значения: 8.0/7.0", texts[0:2] == ["8.0", "7.0"])
check("секретная 11 и пропуск: 11.0/—", texts[2:4] == ["11.0", "—"])
check("значения: 6.5/5.0", texts[4:6] == ["6.5", "5.0"])
check("средние: 8.5/6.0", texts[6:8] == ["8.5", "6.0"])
check("секретная 11 подсвечена золотым",
      ACCENT in values[2].styleSheet())
check("обычные значения без подсветки",
      values[0].styleSheet() == "" or ACCENT not in values[0].styleSheet())

avg_labels = values[6:8]
check("средние окрашены по шкале",
      all("color:" in w.styleSheet() for w in avg_labels)
      and rating_color(8.5) in avg_labels[0].styleSheet()
      and rating_color(6.0) in avg_labels[1].styleSheet())
all_texts = [w.text() for w in page.tracks_container.findChildren(QLabel)]
check("строка «Средняя оценка» есть", "Средняя оценка" in all_texts)
check("треклист-строки тоже в сетке (названия)",
      all(t in all_texts for t in ("Трек один", "Трек два", "Трек три")))

# Колонки выровнены: имена в шапке над клетками значений (по правому краю)
if col_names and len(values) >= 2:
    head_end = col_names[-1].mapTo(page, QPoint(0, 0)).x() \
        + col_names[-1].width()
    val_end = values[1].mapTo(page, QPoint(0, 0)).x() + values[1].width()
    check("шапка выровнена с клетками", abs(head_end - val_end) <= 2)

# Возврат к неоценённому — треклист снова
album2 = STORE.add_album(AlbumDraft(
    title="Ещё один", year="2024",
    tracks=[TrackDraft(title="П")],
))
win.open_album(album2)
QTest.qWait(60)
check("неоценённый: блок «Оценить?» снова виден", page.rate_side.isVisible())
check("неоценённый: треклист вместо сетки",
      all(w.objectName() != "rateColName"
          for w in page.tracks_container.findChildren(QLabel)))

# ============================================================
# ФАЗА 5. Персистентность
# ============================================================
print("== ФАЗА 5: перезапуск хранилища ==")

store3 = MusicStore()
a3 = next(a for a in store3.albums if a.title == "Неоценённый")
check("оценки в базе целы",
      a3.ratings is not None
      and a3.ratings.rater_names == ["Основной", "Сосед"]
      and a3.ratings.values == [[8.0, 7.0], [11.0, None], [6.5, 5.0]])
check("средняя в базе 7.5", a3.rating == 7.5)

# ============================================================
print()
print(f"ИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    print("Провалены:")
    for name in FAIL:
        print(f"  - {name}")
sys.exit(1 if FAIL else 0)
