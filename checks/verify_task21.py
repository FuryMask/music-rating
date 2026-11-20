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
print("== ФАЗА 1: store — статистика, переименование, пароль ==")

u_t = STORE.register_user("Тестер", "pass1")[0]
u_v = STORE.register_user("Второй", "pass2")[0]
check("регистрация Тестер", u_t is not None)
check("регистрация Второй", u_v is not None)

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
stats0 = STORE.user_stats(u_t)
check("stats0: count 0", stats0.rated_count == 0)
check("stats0: favorite_rating None", stats0.favorite_rating is None)
check("stats0: least album None", stats0.least_favorite_album is None)
check("stats0: least artist None", stats0.least_favorite_artist is None)

# А: 8.0, 8.0 → любимая 8.0; Б: 9.0, 5.0
STORE.rate_album(album_a, ["Тестер"], [[8.0], [8.0]])
STORE.rate_album(album_b, ["Тестер"], [[9.0], [5.0]])
s = STORE.user_stats(u_t)
check("count=2", s.rated_count == 2)
check("любимый альбом А 8.0", s.favorite_album == ("Альбом А", 8.0))
check("нелюбимый альбом Б 7.0", s.least_favorite_album == ("Альбом Б", 7.0))
check("любимая оценка 8.0 (2 раза)", s.favorite_rating == 8.0)
check("любимый исполнитель Икс 8.5", s.favorite_artist == ("Икс", 8.5))
check("нелюбимый исполнитель Зет 5.0",
      s.least_favorite_artist == ("Зет", 5.0))

# В: 6.0 → ничья с 5.0/9.0 не влияет; Г: 9.0 → ничья 2-2 с 8.0 → выше (9.0)
STORE.rate_album(album_c, ["Тестер"], [[6.0]])
s = STORE.user_stats(u_t)
check("любимая оценка всё ещё 8.0", s.favorite_rating == 8.0)
check("нелюбимый альбом теперь В 6.0",
      s.least_favorite_album == ("Альбом В", 6.0))
STORE.rate_album(album_d, ["Тестер"], [[9.0]])
s = STORE.user_stats(u_t)
check("ничья частоты → бо́льшая оценка 9.0", s.favorite_rating == 9.0)
check("любимый альбом теперь Г 9.0", s.favorite_album == ("Альбом Г", 9.0))
check("нелюбимый альбом всё ещё В 6.0",
      s.least_favorite_album == ("Альбом В", 6.0))

# Д: 11.0 + 10.0 → арифметика 10.5, кап 10.0
STORE.rate_album(album_e, ["Тестер"], [[11.0], [10.0]])
s = STORE.user_stats(u_t)
check("кап: любимый альбом Д 10.0", s.favorite_album == ("Альбом Д", 10.0))
check("count=5", s.rated_count == 5)

# ============================================================
# ФАЗА 2. Переименование аккаунта
# ============================================================
print("== ФАЗА 2: rename_user ==")

check("rename: пустое имя", STORE.rename_user(u_t, "   ") == "Введите новое имя")
check("rename: занятое имя (регистр)",
      STORE.rename_user(u_t, "ВТОРОЙ") == "Такой логин уже занят")
check("rename: то же имя — ошибка",
      STORE.rename_user(u_t, "Тестер") == "Это уже ваше текущее имя")

old_id = u_t.id
STORE.set_current_user(u_t)  # логиним именно Тестера для проверки сессии
err = STORE.rename_user(u_t, "Тестер Шесть")
check("rename: успех", err is None)
check("rename: имя сменилось", u_t.username == "Тестер Шесть")
check("rename: сессия жива (по id)",
      STORE.current_user is not None and STORE.current_user.id == old_id)
check("rename: STORE.raters обновлён",
      "Тестер Шесть" in STORE.raters and "Тестер" not in STORE.raters)
check("rename: состав альбома А обновлён",
      album_a.ratings.rater_names == ["Тестер Шесть"])
check("rename: оценки не потерялись",
      album_a.ratings.values == [[8.0], [8.0]])
check("rename: статистика на месте",
      STORE.user_stats(u_t).rated_count == 5)
check("rename: смена только регистра допустима",
      STORE.rename_user(u_t, "тестер шесть") is None)

# Переживает перезапуск хранилища
store2 = MusicStore()
u2 = store2.find_user("тестер шесть")
check("rename: персистентность", u2 is not None)
a2 = next(a for a in store2.albums if a.title == "Альбом А")
check("rename: в базе состав обновлён", a2.ratings.rater_names == ["тестер шесть"])
check("rename: в базе оценки целы", a2.ratings.values == [[8.0], [8.0]])
user, err = store2.authenticate("ТЕСТЕР ШЕСТЬ", "pass1")
check("rename: вход под новым именем", user is not None and err is None)

# ============================================================
# ФАЗА 3. Смена пароля без текущего
# ============================================================
print("== ФАЗА 3: change_password(user, new) ==")

u_t2 = store2.find_user("тестер шесть")
check("пароль: пустой отклонён",
      store2.change_password(u_t2, "") == "Новый пароль не может быть пустым")
check("пароль: смена без текущего — успех",
      store2.change_password(u_t2, "brand new") is None)
check("пароль: старый больше не подходит",
      store2.authenticate("тестер шесть", "pass1")[0] is None)
check("пароль: новый работает",
      store2.authenticate("тестер шесть", "brand new")[0] is not None)
check("пароль: тот же пароль — ошибка",
      store2.change_password(u_t2, "brand new")
      == "Новый пароль совпадает с текущим")

# ============================================================
# ФАЗА 4. Окно профиля (UI)
# ============================================================
print("== ФАЗА 4: окно профиля ==")

STORE.logout()
win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWait(250)

# Оповещения — тосты (Task 31): помощники чтения последнего тоста
def last_toast():
    active = win.toasts.active
    return active[0] if active else None

def toasts_clear():
    win.toasts.clear()
    QTest.qWait(50)

win.open_profile()
ov = win._profile_overlay
check("оверлей создан", ov is not None)
wait_overlay(ov)
check("открыт: страница входа",
      ov.pages.currentIndex() == 0 and ov.isVisible())

# Регистрация через UI
ov.lbl_login_link.linkActivated.emit("register")
QTest.qWait(50)
check("ссылка → регистрация", ov.pages.currentIndex() == 1)
ov.in_reg_login.setText("Юзер Юзеров")
ov.in_reg_password.setText("qwerty")
ov.in_reg_password2.setText("qwerty")
ov.btn_register.click()
QTest.qWait(50)
check("регистрация → профиль", ov.pages.currentIndex() == 2)
check("сессия: Юзер Юзеров", STORE.current_user.username == "Юзер Юзеров")

# 1) Ряд вкладок: названия и ✕-кнопка в самом конце
names = [b.text() for b in ov.tab_buttons]
check("вкладки: Главная/Данные/Настройки/Статистика",
      names == ["Главная", "Данные", "Настройки", "Статистика"])
check("вкладки: «Об аккаунте» исчезла", "Об аккаунте" not in names)
cb = ov.btn_close_menu
st = ov.tab_buttons[3]  # последняя вкладка — «Статистика»
check("✕: размер 28×28",
      cb.width() == 28 and cb.height() == 28)
check("✕: в конце ряда (правее «Статистики»)",
      cb.x() > st.x() + st.width())
check("✕: на уровне вкладок", abs(cb.y() - st.y()) <= 6)
check("✕: тултип", cb.toolTip() == "Вернуться в меню")

# 3) «Главная»: без оценок строки «Оценок пока нет» нет вовсе
check("Главная: имя", ov.lbl_name.text() == "Юзер Юзеров")
check("Главная: строки даты нет (скрыта)", not ov.lbl_last_rated.isVisible())
check("Главная: нет текста про отсутствие оценок",
      "Оценок" not in ov.lbl_last_rated.text())
check("Главная: «В приложении с …» есть",
      ov.lbl_member.text().startswith("В приложении с"))

# 1) ✕ возвращает в меню
cb.click()
QTest.qWait(50)
check("✕: окно закрылось", not ov.isVisible())
check("✕: главное окно снова видно", win.isVisible())

# 2) Повторное открытие — сессия жива, вкладка «Данные»
win.open_profile()
wait_overlay(ov)
check("повторное открытие: профиль (был залогинен)",
      ov.pages.currentIndex() == 2)
check("стек: 3 страницы (страницы пароля нет)", ov.pages.count() == 3)
check("атрибут btn_change_password удалён",
      not hasattr(ov, "btn_change_password"))
check("атрибуты страницы пароля удалены",
      not hasattr(ov, "in_old_password")
      and not hasattr(ov, "lbl_password_error"))

ov.tab_buttons[1].click()
QTest.qWait(30)
check("вкладка «Данные» открыта", ov.tab_content.currentIndex() == 1)

# 4) Поля пароля + галочка СПРАВА от подтверждения
check("поля пароля: echo Password",
      ov.in_new_password.echoMode() == QLineEdit.EchoMode.Password
      and ov.in_new_password2.echoMode() == QLineEdit.EchoMode.Password)
check("плейсхолдеры полей пароля",
      ov.in_new_password.placeholderText() == "Новый пароль"
      and ov.in_new_password2.placeholderText() == "Подтвердите пароль")
bp = ov.btn_apply_password
f2 = ov.in_new_password2
check("галочка пароля: 28×28", bp.width() == 28 and bp.height() == 28)
check("галочка пароля: СПРАВА от подтверждения",
      bp.x() > f2.x() + f2.width() - 2 and abs(bp.y() - f2.y()) <= 8)

# 5) Поле имени + галочка
check("поле имени заполнено текущим именем",
      ov.in_name.text() == "Юзер Юзеров")
bn = ov.btn_apply_name
fn = ov.in_name
check("галочка имени: 28×28", bn.width() == 28 and bn.height() == 28)
check("галочка имени: СПРАВА от поля",
      bn.x() > fn.x() + fn.width() - 2 and abs(bn.y() - fn.y()) <= 8)

# 6) «Удалить аккаунт» компактная
bd = ov.btn_delete_account
check("удалить: objectName dangerSmallButton",
      bd.objectName() == "dangerSmallButton")
check("удалить: компактная (не на всю ширину)",
      bd.width() < ov.tab_content.width() // 2)
check("удалить: невысокая", bd.height() <= 34)
check("удалить: слева", bd.x() <= 24)

# 2) «Выйти из аккаунта» — внутри вкладки «Настройки»
bl = ov.btn_logout
check("выйти: текст", bl.text() == "Выйти из аккаунта")
check("выйти: во вкладке (родитель — вкладка)",
      bl.parent() is not None and bl.parent().parent() is ov.tab_content)
center = (ov.tab_content.width() - bl.width()) / 2
check("выйти: по центру вкладки", abs(bl.x() - center) <= 8)

# 4) Смена пароля через UI (оповещения — всплывающие тосты, Task 31)
toasts_clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("пароль: пустые поля → ошибка (тост)",
      t is not None and t.text == "Введите новый пароль"
      and t.kind == "error")
QTest.keyClicks(ov.in_new_password, "abc")
QTest.keyClicks(ov.in_new_password2, "xyz")
toasts_clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("пароль: не совпадают → ошибка (тост)",
      t is not None and t.text == "Пароли не совпадают"
      and t.kind == "error")

ov.in_new_password.clear()
ov.in_new_password2.clear()
QTest.keyClicks(ov.in_new_password, "n12345")
QTest.keyClicks(ov.in_new_password2, "n12345")
toasts_clear()
bp.click()
QTest.qWait(30)
t = last_toast()
check("пароль: успех — тост", t is not None
      and t.text == "Пароль изменён" and t.kind == "success")
check("пароль: поля очищены", ov.in_new_password.text() == ""
      and ov.in_new_password2.text() == "")
check("пароль: новый работает в хранилище",
      STORE.authenticate("Юзер Юзеров", "n12345")[0] is not None)

# 5) Переименование через UI
toasts_clear()
ov.in_name.setText("Юзер Изменён")
bn.click()
QTest.qWait(30)
t = last_toast()
check("имя: тост «Имя изменено»", t is not None
      and t.text == "Имя изменено" and t.kind == "success")
check("имя: лейбл на «Главной» обновился",
      ov.lbl_name.text() == "Юзер Изменён")
check("имя: поле перезаполнено", ov.in_name.text() == "Юзер Изменён")
check("имя: STORE.raters обновлён",
      "Юзер Изменён" in STORE.raters and "Юзер Юзеров" not in STORE.raters)
check("имя: сессия жива", STORE.current_user.username == "Юзер Изменён")

ov.in_name.setText("Тестер Шесть")
toasts_clear()
bn.click()
QTest.qWait(30)
t = last_toast()
check("имя: дубль → ошибка (тост)",
      t is not None and t.text == "Такой логин уже занят"
      and t.kind == "error")
ov.in_name.clear()
toasts_clear()
bn.click()
QTest.qWait(30)
t = last_toast()
check("имя: пустое → ошибка (тост)",
      t is not None and t.text == "Введите новое имя")

# 7) Статистика: пустая — прочерки
ov.tab_buttons[3].click()
QTest.qWait(30)
check("статистика: count 0",
      ov.lbl_stat_count.text() == "Оценено альбомов: 0")
check("статистика: любимый альбом — прочерк",
      ov.lbl_stat_album.text() == "Любимый альбом: —")
check("статистика: любимый исполнитель — прочерк",
      ov.lbl_stat_artist.text() == "Любимый исполнитель: —")
check("статистика: любимая оценка — прочерк",
      ov.lbl_stat_rating.text() == "Любимая оценка: —")
check("статистика: нелюбимый альбом — прочерк",
      ov.lbl_stat_worst_album.text() == "Самый нелюбимый альбом: —")
check("статистика: нелюбимый исполнитель — прочерк",
      ov.lbl_stat_worst_artist.text() == "Самый нелюбимый исполнитель: —")

# Оценки «Юзеру Изменён» → статистика и дата на «Главной»
STORE.rate_album(album_a, ["тестер шесть", "Юзер Изменён"],
                 [[8.0, 9.0], [7.0, None]])
ov._refresh_profile()
QTest.qWait(30)
s = STORE.user_stats(STORE.current_user)
check("статистика: count 1", s.rated_count == 1)
check("статистика: любимая оценка 9.0", s.favorite_rating == 9.0)
check("статистика: лейбл любимой оценки",
      ov.lbl_stat_rating.text() == "Любимая оценка: 9.0")
check("статистика: лейбл нелюбимого альбома",
      ov.lbl_stat_worst_album.text()
      == "Самый нелюбимый альбом: «Альбом А» — 9.0")
check("статистика: лейбл нелюбимого исполнителя",
      ov.lbl_stat_worst_artist.text()
      == "Самый нелюбимый исполнитель: Икс — 9.0")

ov.tab_buttons[0].click()
QTest.qWait(30)
check("Главная: дата последней оценки ПОЯВИЛАСЬ",
      ov.lbl_last_rated.isVisible()
      and ov.lbl_last_rated.text().startswith("Последняя оценка: "))

# Esc-каскад: подтверждение → окно
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(30)
check("Esc закрыл окно профиля", not ov.isVisible())

# ============================================================
# ФАЗА 5. Удаление аккаунта + пересчёт средних
# ============================================================
print("== ФАЗА 5: удаление аккаунта ==")

win.open_profile()
wait_overlay(ov)
check("повторное открытие: сессия жива", ov.pages.currentIndex() == 2)
ov.tab_buttons[1].click()
QTest.qWait(30)
ov.btn_delete_account.click()
QTest.qWait(250)
cf = ov._confirm
title_lbl = next(l for l in cf.findChildren(QLabel)
                 if l.objectName() == "dangerTitle")
check("подтверждение открылось", cf is not None and cf.isVisible())
check("подтверждение: заголовок", title_lbl.text() == "Удалить аккаунт?")
cf.btn_stay.click()
QTest.qWait(50)
check("«Отмена» — остались в аккаунте", STORE.current_user is not None
      and "Юзер Изменён" in STORE.raters)
ov.btn_delete_account.click()
QTest.qWait(250)
cf = ov._confirm
cf.btn_exit.click()
QTest.qWait(80)
check("«Удалить»: окно профиля закрылось", not ov.isVisible())
check("«Удалить»: сессия сброшена", STORE.current_user is None)
check("«Удалить»: аккаунт исчез из участников",
      "Юзер Изменён" not in STORE.raters)
check("«Удалить»: матрица альбома пересчитана",
      album_a.ratings.rater_names == ["тестер шесть"]
      and album_a.ratings.values == [[8.0], [7.0]])
check("«Удалить»: средняя альбома 7.5", album_a.rating == 7.5)

win.open_profile()
wait_overlay(ov)
check("после удаления: окно входа", ov.pages.currentIndex() == 0)
ov.close_overlay()
QTest.qWait(30)

# Esc в подтверждении сначала закрывает подтверждение
STORE.authenticate("Второй", "pass2")
win.open_profile()
wait_overlay(ov)
ov.tab_buttons[1].click()
QTest.qWait(30)
ov.btn_delete_account.click()
QTest.qWait(250)
check("подтверждение открылось перед Esc", ov._confirm.isVisible())
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(50)
check("Esc при подтверждении: подтверждение закрыто, профиль жив",
      (not ov._confirm.isVisible()) and ov.isVisible())
QTest.keyClick(win, Qt.Key.Key_Escape)
QTest.qWait(30)
check("Esc ещё раз: окно закрылось", not ov.isVisible())
STORE.logout()

# ============================================================
# ФАЗА 6. Регрессия: мастер оценивания и страница альбома
# ============================================================
print("== ФАЗА 6: регрессия мастера и страницы альбома ==")

# Плитки участников = актуальные аккаунты (после переименований/удалений)
win.open_rate_album(album_b)
ro = win._rate_overlay
wait_overlay(ro)
chips = list(ro.rater_buttons.keys())
check("плитки = [Второй, тестер шесть]",
      sorted(chips) == ["Второй", "тестер шесть"])
check("заглушек-участников нет",
      not any(c in chips for c in ("Кирилл", "Володя", "Георгий")))

# Валидатор и секретная 11 (регрессия Task 19)
chips_widgets = [ro.rater_buttons[name] for name in ("Второй", "тестер шесть")]
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
check("финал: участники = [Второй, тестер шесть]",
      sorted(u.username for u in store3.users)
      == ["Второй", "тестер шесть"])
a3 = next(a for a in store3.albums if a.title == "Альбом А")
check("финал: матрица А в базе",
      a3.ratings.rater_names == ["тестер шесть"]
      and a3.ratings.values == [[8.0], [7.0]])
check("финал: статистика по новому имени работает",
      store3.user_stats(store3.find_user("тестер шесть")).rated_count == 5)

# ============================================================
print()
print(f"ИТОГО: {PASS} OK, {len(FAIL)} FAIL")
if FAIL:
    print("Провалены:")
    for name in FAIL:
        print(f"  - {name}")
sys.exit(1 if FAIL else 0)
