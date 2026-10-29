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
# ФАЗА 1. Хранилище: то же имя и тот же пароль запрещены
# ============================================================
print("== ФАЗА 1: store — запрет актуальных значений ==")

u1 = STORE.register_user("Основной", "pass1")[0]
u2 = STORE.register_user("Сосед", "pass2")[0]
check("регистрация Основной", u1 is not None)
check("регистрация Сосед", u2 is not None)

# --- Имя ---
check("имя: то же — ошибка",
      STORE.rename_user(u1, "Основной") == "Это уже ваше текущее имя")
check("имя: то же (с пробелами) — ошибка",
      STORE.rename_user(u1, "  Основной  ") == "Это уже ваше текущее имя")
check("имя: смена только регистра допустима",
      STORE.rename_user(u1, "основной") is None)
check("имя: регистр сменился", u1.username == "основной")
check("имя: обратно регистром допустимо",
      STORE.rename_user(u1, "Основной") is None)
check("имя: данные целы", u1.username == "Основной")

# --- Пароль ---
check("пароль: пустой отклонён",
      STORE.change_password(u1, "") == "Новый пароль не может быть пустым")
check("пароль: тот же — ошибка",
      STORE.change_password(u1, "pass1")
      == "Новый пароль совпадает с текущим")
check("пароль: смена на новый работает",
      STORE.change_password(u1, "pass9") is None)
check("пароль: старый не подходит",
      STORE.authenticate("Основной", "pass1")[0] is None)
check("пароль: новый подходит",
      STORE.authenticate("Основной", "pass9")[0] is not None)
check("пароль: после смены прежний снова «тот же» — ошибка",
      STORE.change_password(u1, "pass9")
      == "Новый пароль совпадает с текущим")

# Персистентность правила
from app.store import MusicStore

store2 = MusicStore()
u1b = store2.find_user("Основной")
check("перезапуск: тот же пароль — ошибка",
      store2.change_password(u1b, "pass9")
      == "Новый пароль совпадает с текущим")
check("перезапуск: то же имя — ошибка",
      store2.rename_user(u1b, "Основной") == "Это уже ваше текущее имя")

# ============================================================
# ФАЗА 2. Окно профиля: статусы, автоскрытие, обрезание
# ============================================================
print("== ФАЗА 2: профиль — статусы и геометрия ==")

STORE.set_current_user(u1)
win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWait(250)

win.open_profile()
ov = win._profile_overlay
wait_overlay(ov)
check("профиль открыт (залогинен)", ov.pages.currentIndex() == 2)

ov.tab_buttons[1].click()
QTest.qWait(30)
check("вкладка «Данные» открыта", ov.tab_content.currentIndex() == 1)

bp = ov.btn_apply_password
bn = ov.btn_apply_name
bd = ov.btn_delete_account
bl = ov.btn_logout
tab = bp.parentWidget()  # страница вкладки «Данные»

# 2) Появление статуса НЕ сдвигает поля и галочки
geo_bp = (bp.x(), bp.y(), bp.width(), bp.height())
geo_bn = (bn.x(), bn.y(), bn.width(), bn.height())
geo_bd = (bd.x(), bd.y(), bd.width(), bd.height())
geo_bl = (bl.x(), bl.y(), bl.width(), bl.height())

ov.in_new_password.clear()
bp.click()
QTest.qWait(30)
# Оповещения — всплывающие тосты (Task 31): появляются над окном,
# сами закрываются; поля и галочки при их появлении не сдвигаются
def last_toast():
    active = win.toasts.active
    return active[0] if active else None

def toasts_clear():
    win.toasts.clear()
    QTest.qWait(50)

toasts_clear()
ov.in_new_password.clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("ошибка «Введите новый пароль» — тост",
      t is not None and t.text == "Введите новый пароль"
      and t.kind == "error")
check("галочка пароля НЕ сдвинулась",
      (bp.x(), bp.y(), bp.width(), bp.height()) == geo_bp)
check("галочка имени НЕ сдвинулась",
      (bn.x(), bn.y(), bn.width(), bn.height()) == geo_bn)
check("«Удалить аккаунт» НЕ сдвинулась",
      (bd.x(), bd.y(), bd.width(), bd.height()) == geo_bd)
check("«Выйти» НЕ сдвинулась",
      (bl.x(), bl.y(), bl.width(), bl.height()) == geo_bl)

# 2) Тост гаснет сам: ~3.5 секунды жизни (полоска уходит), затем
# плавное исчезновение (Task 22, п. 2 в новой механике)
QTest.qWait(4200)
check("тост ошибки закрылся сам", not win.toasts.active)

# 2) Зелёный тост тоже закрывается сам
ov.in_name.setText("Основной II")
toasts_clear()
bn.click()
QTest.qWait(30)
t = last_toast()
check("имя сменилось — тост успеха", t is not None
      and t.text == "Имя изменено" and t.kind == "success")
QTest.qWait(4200)
check("тост успеха закрылся сам", not win.toasts.active)
check("имя в хранилище сменилось",
      STORE.current_user.username == "Основной II")
STORE.rename_user(STORE.current_user, "Основной")

# 3) То же имя через UI — ошибка тостом с автозакрытием
ov.in_name.setText("Основной")
toasts_clear()
bn.click()
QTest.qWait(30)
t = last_toast()
check("то же имя → ошибка (тост)",
      t is not None and t.text == "Это уже ваше текущее имя"
      and t.kind == "error")
QTest.qWait(4300)
check("ошибка имени погасла сама", not win.toasts.active)

# 3) Тот же пароль через UI — ошибка тостом с автозакрытием
QTest.keyClicks(ov.in_new_password, "pass9")
QTest.keyClicks(ov.in_new_password2, "pass9")
toasts_clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("тот же пароль → ошибка (тост)",
      t is not None and t.text == "Новый пароль совпадает с текущим")
check("пароль НЕ изменился",
      STORE.authenticate("Основной", "pass9")[0] is not None)
QTest.qWait(4300)
check("ошибка пароля погасла сама", not win.toasts.active)

# Регрессия: обычная смена пароля по-прежнему работает
ov.in_new_password.clear()
ov.in_new_password2.clear()
QTest.keyClicks(ov.in_new_password, "pass7")
QTest.keyClicks(ov.in_new_password2, "pass7")
toasts_clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("смена пароля: тост «Пароль изменён»",
      t is not None and t.text == "Пароль изменён"
      and t.kind == "success")
check("смена пароля: поля очищены",
      ov.in_new_password.text() == "" and ov.in_new_password2.text() == "")
check("смена пароля: новый работает",
      STORE.authenticate("Основной", "pass7")[0] is not None)
toasts_clear()

# ============================================================
# Task 23 → Task 31: строки-статусы убраны, оповещения — тосты
# ============================================================
print("== ФАЗА 2.5: строки-статусы убраны (Task 31) ==")

check("держатель статусов «Данные» больше не существует",
      ov.findChild(QWidget, "profileStatusHolder") is None)
check("держатель статусов «Настройки» больше не существует",
      ov.findChild(QWidget, "profileDbStatusHolder") is None)
check("метки статусов не созданы",
      not hasattr(ov, "lbl_account_status")
      and not hasattr(ov, "lbl_settings_error")
      and not hasattr(ov, "lbl_db_status")
      and not hasattr(ov, "lbl_db_error"))

# Тост показывается независимо от активной вкладки, сверху по центру
# главного окна; закрывается кликом
ov.tab_buttons[2].click()   # «Настройки»
QTest.qWait(30)
ov.in_new_password.clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("тост с вкладки «Настройки»: ошибка пароля",
      t is not None and t.text == "Введите новый пароль")
check("тост сверху по центру главного окна",
      t is not None
      and abs((t.x() + t.width() / 2) - (win.x() + win.width() / 2)) <= 4
      and t.y() >= win.y())
check("у тоста полоска прогресса и цвет характера",
      t is not None and 0.0 < t._progress <= 1.0)
t.dismiss()
QTest.qWait(450)
check("dismiss закрывает тост", not win.toasts.active)
ov.tab_buttons[1].click()
QTest.qWait(30)

# 1) Запасы под ховер-рост: ничего не срезается краями вкладки
# Ховер растит кнопку на 10 % вокруг центра → выступ = ширина/20
need_left = bd.width() / 20.0     # «Удалить аккаунт» — влево
check("«Удалить аккаунт»: запас слева",
      bd.x() >= need_left
      and bd.x() + bd.width() <= tab.width() - 1)
need_bottom = bl.height() / 20.0  # «Выйти» — вниз
check("«Выйти»: запас снизу",
      tab.height() - (bl.y() + bl.height()) >= need_bottom)
need_right_p = bp.width() / 20.0  # галочки — вправо
check("галочка пароля: запас справа",
      tab.width() - (bp.x() + bp.width()) >= need_right_p)
check("галочка имени: запас справа",
      tab.width() - (bn.x() + bn.width()) >= bn.width() / 20.0)
check("галочки на прежних местах (статус не мешает)",
      (bp.x(), bp.y()) == geo_bp[:2] and (bn.x(), bn.y()) == geo_bn[:2])

# Esc закрывает окно
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(30)
check("Esc закрыл профиль", not ov.isVisible())

# ============================================================
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
