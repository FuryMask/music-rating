"""verify_task39 — анимации и стиль (Task 39).

Проверяет новую «моторику» приложения и целостность стиля:
  1. ПЕРЕХОДЫ СТРАНИЦ (widgets/page_stack.py): переключение страницы
     мгновенное (currentWidget уже новая), но поверх стека гаснет
     снимок прежней страницы; вперёд снимок уезжает влево, назад —
     вправо; после PAGE_MS снимок скрыт и освобождён; при
     MUSICRATING_REDUCED_MOTION снимка нет вовсе.
  2. ХОВЕР / НАЖАТИЕ / ВОЛНА (widgets/hoverable.py): карточка при
     наведении растёт (+10 %), обводка обложки включается, название
     белеет; кнопка при нажатии сжимается, отпускание возвращает
     размер; от клика идёт волна (без QGraphicsEffect — только
     отрисовка); нажатие БЕЗ предварительного наведения не уводит
     кнопку в угол (база берётся из текущей геометрии).
  3. ПРОКРУТКА (widgets/motion.SmoothScrollArea): колесо сглаживается
     по умолчанию; MUSICRATING_SMOOTH_SCROLL=0 отключает сглаживание.
     Тачпад (pixelDelta) двигается 1:1.
  4. УМНОЕ КОЛЕСО ЛЕНТЫ (widgets/section.CardRow): вертикальное
     колесо над карточками прокручивает страницу, Shift+колесо и
     горизонтальный жест — саму ленту.
  5. ПОЯВЛЕНИЕ: панель поиска проявляется; строки страницы альбома
     «всплывают» каскадом; главная — каскадом карточек; эффекты
     снимаются после анимации (никаких «залипших» прозрачностей).
  6. СТИЛЬ (theme.py): акцентная палитра, прозрачные QLabel,
     скруглённая карточка диалога, тонкая полоса ленты, шкала оценок
     не изменилась.

ВНИМАНИЕ: тест стирает data/ и создаёт пустую базу — запускать
только на копии проекта (как остальные verify_task*).
"""

import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

_CANDIDATES = [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[1],
]
APP = next(c for c in _CANDIDATES if (c / "app" / "theme.py").exists())
sys.path.insert(0, str(APP))
if os.environ.get("MUSICRATING_CHECK_ROOT") != str(APP):
    raise SystemExit("Run this check through checks/run.py.")

# ВНИМАНИЕ: тесты СТИРАЮТ data/ — не запускать на живой библиотеке!
DATA = APP / "data"
if DATA.exists():
    shutil.rmtree(DATA)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QEnterEvent, QFont, QPainterPath, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

app = QApplication([])
app.setApplicationName("Music Rating")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))

import app.theme as theme

theme.apply_theme(app)

# Заглушка фоновой дозагрузки фото (без сети)
import app.services.backfill as bf


class _StubBackfiller:
    def __init__(self, *a, **k) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Q(QObject):
            changed = Signal()

        self._q = _Q()

    @property
    def changed(self):
        return self._q.changed

    def start(self) -> None:
        pass


bf.ArtBackfiller = _StubBackfiller

from app.models import AlbumDraft, ArtistDraft, TrackDraft
from app.services.yandex_music import _parse_album
from app.services.yandex_playback import MediaSnapshot, match_album_tracks
from app.store import STORE
from checks.fixtures.library import populate_library

populate_library(STORE)
from app.ui.dialogs.track_dialog import FADE_MS, RISE_MS, TrackDialogOverlay
from app.ui.main_window import MainWindow
from app.services.cloud_library import CloudSession
from app.ui.pages.rate_album import RateAlbumOverlay
from app.ui.widgets import motion
from app.ui.widgets.album_card import AlbumCard
from app.ui.widgets.combo_box import DarkComboBox
from app.ui.widgets.cover_view import HOVER_ZOOM
from app.ui.widgets.hoverable import HOVER_SCALE, PRESS_SCALE, RIPPLE_MS, HoverButton
from app.ui.widgets.page_stack import AnimatedStackedWidget, SHIFT_PX, page_fade_enabled
from app.ui.widgets.scroll_bar import SlimScrollBar
from app.ui.widgets.section import CardRow

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
        print(f"  FAIL: {name}")


def enter(widget) -> None:
    centre = QPointF(widget.rect().center())
    globe = QPointF(widget.mapToGlobal(widget.rect().center()))
    QApplication.sendEvent(widget, QEnterEvent(centre, globe, globe))


def leave(widget) -> None:
    QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))


def wait_until(condition, timeout_ms: int = 2000) -> bool:
    """Дождаться условия (анимации на медленной машине длиннее таймера)."""
    waited = 0
    while waited <= timeout_ms:
        if condition():
            return True
        QTest.qWait(25)
        waited += 25
    return bool(condition())


def wheel(widget, dx: int = 0, dy: int = -120, mods=Qt.KeyboardModifier.NoModifier) -> bool:
    centre = widget.rect().center()
    event = QWheelEvent(
        QPointF(centre),
        QPointF(widget.mapToGlobal(centre)),
        QPoint(0, 0),
        QPoint(dx, dy),
        Qt.MouseButton.NoButton,
        mods,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event.isAccepted()


win = MainWindow()
win.resize(1100, 650)
win.show()
QTest.qWait(700)

# ============================================================
print("== ФАЗА 1: переключение страниц (мгновенное по умолчанию) ==")
# ============================================================
check("стек страниц — AnimatedStackedWidget",
      isinstance(win.pages, AnimatedStackedWidget))
check("затухание страниц по умолчанию выключено",
      not page_fade_enabled())
check("снимок перехода создан и скрыт",
      win.pages._snapshot is not None
      and not win.pages._snapshot.isVisible())

album = STORE.add_album(AlbumDraft(
    title="Переход", year="2024", genre="Рок",
    artists=[ArtistDraft(name="Тестовый", existing=False)],
    tracks=[TrackDraft(title="Первый"), TrackDraft(title="Второй")],
))
win.home_page.refresh()
QTest.qWait(50)

win.open_album(album)
check("страница переключилась сразу (без задержки)",
      win.pages.currentWidget() is win.album_page)
check("снимка нет: переключение без grab прежней страницы",
      not win.pages._snapshot.isVisible()
      and win.pages._snapshot._pix is None)

# Опциональное затухание (MUSICRATING_PAGE_FADE=1)
os.environ["MUSICRATING_PAGE_FADE"] = "1"
win.close_album()
check("fade: показан снимок прежней страницы",
      win.pages._snapshot.isVisible())
check("fade: снимок содержит пиксели",
      win.pages._snapshot._pix is not None
      and not win.pages._snapshot._pix.isNull())
check("fade: снимок гаснет",
      wait_until(lambda: win.pages._snapshot._alpha < 1.0, 1000))
check("fade: назад — снимок уезжает вправо",
      win.pages._snapshot._shift >= 0.0)
check("fade: анимация завершена",
      wait_until(lambda: not win.pages._snapshot.isVisible()))
check("fade: снимок освобождён",
      win.pages._snapshot._pix is None)

win.open_album(album)
check("fade: вперёд — снимок уезжает влево",
      wait_until(lambda: win.pages._snapshot._alpha < 1.0
                 and win.pages._snapshot._shift <= 0.0, 1200))
wait_until(lambda: not win.pages._snapshot.isVisible())

# Та же страница — перехода нет
win.pages.setCurrentWidget(win.pages.currentWidget())
check("переключение в ту же страницу без снимка",
      not win.pages._snapshot.isVisible())

# reduced motion: перехода нет даже с включённым fade
os.environ["MUSICRATING_REDUCED_MOTION"] = "1"
win.close_album()
check("reduced-motion: снимка нет", not win.pages._snapshot.isVisible())
check("reduced-motion: страница всё равно переключилась",
      win.pages.currentWidget() is win.home_page)
del os.environ["MUSICRATING_REDUCED_MOTION"]
del os.environ["MUSICRATING_PAGE_FADE"]
win._show_home()
QTest.qWait(motion.PAGE_MS + 150)

# ============================================================
print("== ФАЗА 2: ховер, нажатие и волна ==")
# ============================================================
win._show_home()


def all_home_cards():
    result = []
    for section in (win.home_page.section_recent,
                    win.home_page.section_rated,
                    win.home_page.section_unrated,
                    win.home_page.section_artists):
        result.extend(section.cards())
    return result


QTest.qWait(60)


def _entrance_state():
    anims = [getattr(card, "_drop_anim", None) for card in all_home_cards()]
    started = all(anim is not None for anim in anims)
    running = any(
        anim is not None
        and anim.state() == motion.QAbstractAnimation.State.Running
        for anim in anims
    )
    return started, running


# Дождаться конца каскада появления: пока он идёт, ховер отложен
wait_until(lambda: _entrance_state()[0], 2500)
wait_until(lambda: not _entrance_state()[1], 4000)
cards = win.home_page.section_rated.cards()
check("на главной есть карточки", bool(cards))
card = cards[0]
base_geometry = card.geometry()
enter(card)
check("карточка выросла при наведении (~10 %)",
      wait_until(lambda: abs(card.width()
                             - base_geometry.width() * HOVER_SCALE) <= 3
                 and card.width() > base_geometry.width()))
check("обводка обложки включена",
      wait_until(lambda: card.cover._outline >= 0.99))
check("картинка обложки приближена (зум по наведению)",
      card.cover._outline > 0 and HOVER_ZOOM > 0)
check("название карточки стало белым",
      "#ffffff" in card.title.styleSheet().lower())
check("оценка в «пилюле» ярче при наведении",
      card._hover_progress >= 0.99)
leave(card)
check("после ухода карточка вернулась к базовому размеру",
      wait_until(lambda: card.geometry() == base_geometry))
check("после ухода обводка погасла", card.cover._outline <= 0.01)

# Кнопка: «пружина» + волна
button = HoverButton("Кнопка", win.centralWidget())
button.setGeometry(600, 120, 130, 38)
button.show()
button.raise_()
QTest.qWait(80)
button_base = button.geometry()
enter(button)
check("кнопка выросла при наведении",
      wait_until(lambda: button._visual_scale > 0.995)
      and button.geometry() == button_base)
QTest.mousePress(button, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, QPoint(20, 19))
QTest.qWait(40)
check("от клика пошла волна", button._ripple_t > 0.0)
check("при нажатии кнопка сжимается",
      wait_until(lambda: abs(button._visual_scale - PRESS_SCALE) < 0.005, 800)
      and button.geometry() == button_base)
check("волна рисуется без QGraphicsEffect",
      button.graphicsEffect() is None)
QTest.mouseRelease(button, Qt.MouseButton.LeftButton,
                   Qt.KeyboardModifier.NoModifier, QPoint(20, 19))
check("после отпускания кнопка вернулась к размеру ховера",
      wait_until(lambda: button._visual_scale > 0.995))
check("волна погасла и освобождена",
      wait_until(lambda: button._ripple_t == 0.0
                 and button._ripple_anim is None, RIPPLE_MS + 800))
leave(button)
check("без наведения кнопка в исходном размере",
      wait_until(lambda: abs(button._visual_scale - 1 / HOVER_SCALE) < 0.005)
      and button.geometry() == button_base)
button.hide()

# Нажатие без наведения: кнопка не улетает в угол
plain = HoverButton("Без ховера", win.centralWidget())
plain.setGeometry(600, 200, 130, 38)
plain.show()
plain.raise_()
QTest.qWait(80)
plain_pos = plain.pos()
QTest.mousePress(plain, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, QPoint(20, 19))
QTest.qWait(80)
check("нажатие без ховера не двигает кнопку к углу",
      abs(plain.x() - plain_pos.x()) <= 3
      and abs(plain.y() - plain_pos.y()) <= 3)
check("нажатие без ховера не растягивает кнопку",
      plain.width() <= plain_pos.x() * 0 + 131)
QTest.mouseRelease(plain, Qt.MouseButton.LeftButton,
                   Qt.KeyboardModifier.NoModifier, QPoint(20, 19))
QTest.qWait(250)
plain.hide()

# --- 2.1. Защита от «залипшего» увеличения (Task 40) ---
print("== ФАЗА 2.1: повторный вход и ушедший курсор ==")
probe_holder = QWidget(win.centralWidget())
probe_holder.setGeometry(385, 285, 220, 290)
probe_holder.show()
probe_holder.raise_()
probe = AlbumCard(album, probe_holder)
probe.setGeometry(15, 15, 160, 228)
probe.show()
probe.raise_()
QTest.qWait(120)
probe_base = probe.geometry()

QTest.mouseMove(probe, probe.rect().center())
check("настоящая мышь: карточка увеличилась",
      wait_until(lambda: probe.width()
                 == round(probe_base.width() * HOVER_SCALE)))
grown_once = probe.geometry()

# Повторный Enter (как после «потерянного» Leave): размер не должен
# вырасти ещё раз — база фиксируется только при входе из покоя
globe = QPointF(probe.mapToGlobal(probe.rect().center()))
QApplication.sendEvent(probe, QEnterEvent(
    QPointF(probe.rect().center()), globe, globe))
check("повторный вход не увеличивает карточку ещё раз",
      wait_until(lambda: probe.geometry() == grown_once, 700))

# Курсор «уехал» вместе с прокруткой: элемент сдвинулся, Leave не пришёл
probe_holder.move(720, 540)
check("курсор ушёл без Leave — карточка вернулась к базе",
      wait_until(lambda: not probe._hovered
                 and probe.geometry() == probe_base, 2000))

# После этого обычное наведение снова работает
QTest.mouseMove(win.top_bar.search_input,
                win.top_bar.search_input.rect().center())
QTest.qWait(250)
probe_holder.move(385, 285)
QTest.qWait(120)
QTest.mouseMove(probe, probe.rect().center())
check("после «залипания» наведение снова работает",
      wait_until(lambda: probe._hovered
                 and probe.width()
                 == round(probe_base.width() * HOVER_SCALE)))
QTest.mouseMove(win.top_bar.search_input,
                win.top_bar.search_input.rect().center())
check("обычный уход мышью возвращает размер",
      wait_until(lambda: probe.geometry() == probe_base))
probe_holder.hide()
probe_holder.deleteLater()

# --- 2.2. Карточка, которую ещё не разложил layout (640×480) ---
print("== ФАЗА 2.2: ховер до раскладки ==")
late = AlbumCard(album, win.centralWidget())
late.setGeometry(500, 560, 640, 480)   # как свежий QWidget до layout
late.show()
late.raise_()
QTest.qWait(30)
check("до раскладки карточка ещё «дефолтная» (640×480)",
      late.width() >= 600 and not late._rest_size_ready())
enter(late)
QTest.qWait(50)
check("ховер отложен: база не 640×480",
      late._hover_pending or late._base_geometry.width() < 600)
# layout задаёт настоящий размер (как Section для карточки в ленте)
late.setGeometry(500, 560, 160, 228)
check("после раскладки ховер включается от реального размера",
      wait_until(lambda: late._base_geometry.width() == 160
                 and late._base_geometry.height() == 228
                 and late.width() == 176, 1500))
check("ховер не раздувает карточку до абсурда",
      late.width() <= 220 and late.height() <= 320)
leave(late)
check("после ухода карточка возвращается к своему размеру",
      wait_until(lambda: late.geometry().width() == 160
                 and late.geometry().height() == 228))
late.hide()
late.deleteLater()

# Кнопка с фиксированным размером не «дёргается» при наведении
fixed_btn = HoverButton("", win.centralWidget(), outline_radius=10)
fixed_btn.setFixedSize(40, 40)
fixed_btn.setGeometry(60, 620, 40, 40)
fixed_btn.show()
fixed_btn.raise_()
QTest.qWait(60)
fixed_pos = fixed_btn.pos()
enter(fixed_btn)
QTest.qWait(450)
check("иконка с фиксированным размером не смещается при ховере",
      fixed_btn.pos() == fixed_pos and fixed_btn.size().width() == 40
      and wait_until(lambda: fixed_btn._visual_scale > 0.995))
leave(fixed_btn)
QTest.qWait(30)
fixed_btn.hide()
check("скрытие прерывает возврат и сбрасывает масштаб",
      abs(fixed_btn._visual_scale - 1 / HOVER_SCALE) < 0.005
      and fixed_btn.pos() == fixed_pos)
fixed_btn.deleteLater()

# ============================================================
print("== ФАЗА 3: плавное колесо и лента ==")
# ============================================================
win._show_home()
QTest.qWait(400)
page = win.home_page
bar = page.verticalScrollBar()
bar.setValue(0)
QTest.qWait(50)
if bar.maximum() > 0:
    check("плавная прокрутка по умолчанию включена",
          motion.smooth_scroll_enabled())
    target = min(bar.maximum(), motion.SmoothScrollArea.WHEEL_STEP)
    positions = []
    record_position = positions.append
    bar.valueChanged.connect(record_position)
    wheel(page.viewport(), 0, -120)
    started = page._anim.state() == motion.QAbstractAnimation.State.Running
    arrived = wait_until(lambda: bar.value() == target)
    bar.valueChanged.disconnect(record_position)
    check("колесо плавно прокручивает страницу",
          started and any(0 < position < target for position in positions))
    check("плавная прокрутка доезжает до цели", arrived)

    os.environ["MUSICRATING_SMOOTH_SCROLL"] = "0"
    bar.setValue(0)
    wheel(page.viewport(), 0, -120)
    check("при отключении сглаживания колесо крутит сразу",
          bar.value() > 0 and page._anim.state() != motion.QAbstractAnimation.State.Running)
    del os.environ["MUSICRATING_SMOOTH_SCROLL"]
    bar.setValue(0)
    QTest.qWait(30)

    row = page.section_rated._row
    check("лента карточек — CardRow с умным колесом",
          isinstance(row, CardRow))
    page_before = bar.value()
    row_bar = row.horizontalScrollBar()
    row_before = row_bar.value()
    accepted = wheel(row.viewport(), 0, -120,
                     Qt.KeyboardModifier.ShiftModifier)
    QTest.qWait(40)
    check("Shift+колесо листает ленту по горизонтали",
          accepted and row_bar.value() > row_before)
    check("Shift+колесо не двигает страницу",
          bar.value() == page_before)

    page_before = bar.value()
    wheel(row.viewport(), 0, -120)
    QTest.qWait(40)
    check("вертикальное колесо над лентой крутит страницу",
          bar.value() != page_before)

    # Тачпад прерывает сглаживание и начинает от текущей позиции.
    before_pixel = bar.value()
    centre = page.viewport().rect().center()
    pixel = QWheelEvent(
        QPointF(centre), QPointF(page.viewport().mapToGlobal(centre)),
        QPoint(0, -40), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(page.viewport(), pixel)
    QTest.qWait(30)
    check("тачпад: пиксельная дельта прокручивает 1:1",
          bar.value() == min(before_pixel + 40, bar.maximum())
          and page._anim.state() != motion.QAbstractAnimation.State.Running)

    os.environ["MUSICRATING_REDUCED_MOTION"] = "1"
    bar.setValue(0)
    wheel(page.viewport(), 0, -120)
    QTest.qWait(20)
    check("reduced-motion: колесо работает сразу",
          bar.value() > 0)
    del os.environ["MUSICRATING_REDUCED_MOTION"]
    bar.setValue(0)
    QTest.qWait(30)

# ============================================================
print("== ФАЗА 4: появление панели, строк и карточек ==")
# ============================================================
win.top_bar.search_input.setText("пер")
QTest.qWait(30)
panel = win.search_panel
check("панель поиска видима", panel.isVisible())
check("панель проявляется (эффект непрозрачности)",
      isinstance(panel.graphicsEffect(), QGraphicsOpacityEffect))
check("после проявления эффект снят",
      wait_until(lambda: panel.graphicsEffect() is None, 1200))
win.top_bar.search_input.clear()
QTest.qWait(80)

win.open_album(album)
QTest.qWait(40)
rows = [
    win.album_page.tracks_v.itemAt(i).widget()
    for i in range(win.album_page.tracks_v.count())
]
rows = [row for row in rows if row is not None]
check("строки альбома «всплывают» каскадом",
      any(row.graphicsEffect() is not None for row in rows))
check("после появления строк эффекты сняты",
      wait_until(lambda: all(row.graphicsEffect() is None
                             for row in rows), 2000))

QTest.mouseMove(win.top_bar.search_input, win.top_bar.search_input.rect().center())
win._show_home()
QTest.qWait(60)
check("главная: карточки появляются каскадом",
      bool(all_home_cards())
      and any(card.graphicsEffect() is not None
              for card in all_home_cards()))
wait_until(lambda: _entrance_state()[0], 2500)
check("главная: после появления эффекты сняты",
      wait_until(lambda: not _entrance_state()[1]
                 and all(card.graphicsEffect() is None
                         for card in all_home_cards()), 4000))
first_card = win.home_page.section_rated.cards()[0]
rest_size = first_card.sizeHint()
for _attempt in range(2):
    enter(first_card)
    wait_until(lambda: first_card.width() > rest_size.width())
    leave(first_card)
    win.open_album(album)
    win._show_home()
    QTest.qWait(60)
    wait_until(lambda: not any(card._entrance_running() for card in all_home_cards()), 3000)
check("после повторных переходов карточки не стартуют увеличенными",
      all(card.size() == card.sizeHint() for card in all_home_cards()))

# ============================================================
print("== ФАЗА 5: стиль и палитра ==")
# ============================================================
qss = theme.QSS
check("акцент стеклянной темы — холодный голубой", theme.ACCENT == "#b9d6ff")
check("матовый холст визуально темнее навигации", theme.BG_MAIN == "#101725")
check("QSS: QLabel прозрачны (нет «плашек» под текстом)",
      "QLabel {" in qss)
dialog_style = qss.split("#dialogCard {", 1)[1].split("}", 1)[0]
check("QSS: скруглённая карточка диалога с материалом",
      "border-radius: 23px" in dialog_style and "qlineargradient" in dialog_style)
check("QSS: тонкая полоса ленты карточек",
      "#sectionRow QScrollBar:horizontal" in qss)
check("QSS: состояния hover/pressed у главной кнопки",
      "#primaryButton:hover" in qss and "#primaryButton:pressed" in qss)
check("QSS: подсказки оформлены",
      "QToolTip" in qss and "border-radius: 7px" in qss)
check("шкала оценок не изменилась",
      theme.rating_color(3.9) == theme.RATING_RED
      and theme.rating_color(5.0) == theme.RATING_YELLOW
      and theme.rating_color(8.0) == theme.RATING_GREEN
      and theme.rating_color(9.5) == theme.RATING_BLUE
      and theme.rating_color(None) == theme.TEXT_MUTED)

# Карточка рисует «пилюлю» только у оценённого альбома: текст оценки
# сдвинут внутрь плашки (7px), у неоценённого — обычный отступ.
rated = next((a for a in STORE.albums if a.rating is not None), None)
unrated = next((a for a in STORE.albums if a.rating is None), None)
check("в тестовой базе есть оценённый и неоценённый альбомы",
      rated is not None and unrated is not None)
if rated is not None and unrated is not None:
    rated_card = AlbumCard(rated)
    unrated_card = AlbumCard(unrated)
    check("оценённый альбом: оценка сдвинута внутрь «пилюли»",
          rated_card.rating.contentsMargins().left() > 0)
    check("неоценённый альбом: «—» без «пилюли»",
          unrated_card.rating.contentsMargins().left() == 0)
    check("карточка отрисовывается без ошибок",
          not rated_card.grab().isNull())
    rated_card.deleteLater()
    unrated_card.deleteLater()

print("== ФАЗА 6: стеклянная навигация ==")
win._show_home()
nav = win.sidebar._destinations
for key in ("albums", "artists", "recent"):
    QTest.mouseClick(nav[key], Qt.MouseButton.LeftButton)
    check(f"сайдбар открывает {key} и отмечает активный пункт",
          win.pages.currentWidget() is win.list_page and win.list_page.mode == key
          and [item for item, button in nav.items() if button.isChecked()] == [key])
QTest.mouseClick(nav["home"], Qt.MouseButton.LeftButton)
check("пункт «Обзор» возвращает на главную", win.pages.currentWidget() is win.home_page
      and nav["home"].isChecked() and not win._nav_stack)
QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
check("Ctrl+F переводит фокус в поиск", win.top_bar.search_input.hasFocus())
check("баннер удалён", win.home_page.findChild(QPushButton, "bannerAction") is None)
actions = [win.sidebar.btn_profile,
           win.sidebar.btn_cloud_upload, win.sidebar.btn_add]
check("четыре кнопки действий разнесены одинаково",
      len({right.x() - left.geometry().right() for left, right in zip(actions, actions[1:])}) == 1)
QTest.mouseClick(win.sidebar.btn_add, Qt.MouseButton.LeftButton)
check("добавление из сайдбара открывает существующий мастер",
      win._choice_overlay is not None and win._choice_overlay.isVisible())
win._choice_overlay.hide()
profile_id = "fixture-account"
win._cloud_upload._save_session(CloudSession(profile_id, "fixture", display_name="Проверка профиля"))
win._cloud_upload._set_members({profile_id: "Проверка профиля"})
win._cloud_upload.poll = lambda: None
win.open_profile()
profile = win._profile_overlay
QTest.qWait(450)
profile_buttons = [*profile.tab_buttons, profile.btn_close_menu]
for profile_button in profile_buttons:
    geometry = profile_button.geometry()
    enter(profile_button)
    check(f"ховер в профиле: {profile_button.text() or 'закрытие'}",
          wait_until(lambda: profile_button._visual_scale > 0.995)
          and profile_button.geometry() == geometry)
    leave(profile_button)
    check("кнопка профиля возвращается без сдвига",
          wait_until(lambda: abs(profile_button._visual_scale - 1 / HOVER_SCALE) < 0.005)
          and profile_button.geometry() == geometry)
profile.hide()

# ============================================================
print("== ФАЗА 7: границы холста и повторное открытие исполнителя ==")
outline = QPainterPath()
outline.addRoundedRect(QRectF(win.pages.rect()), 23, 23)
check("прямоугольник страницы целиком внутри скруглённого холста",
      outline.contains(QRectF(win.home_page.geometry())))

track = TrackDialogOverlay(win)
track.open()
QTest.qWait(RISE_MS + 50)
for cycle in range(2):
    QTest.mouseClick(track.btn_new_artist, Qt.MouseButton.LeftButton)
    check(f"исполнитель: открытие {cycle + 1} стартует с анимацией",
          track.artist_card in track._groups and track._artist_fx.opacity() < 1)
    check("исполнитель: карточка полностью проявляется",
          wait_until(lambda: track._artist_fx.opacity() == 1.0))
    QTest.mouseClick(track.btn_artist_cancel, Qt.MouseButton.LeftButton)
    check(f"исполнитель: закрытие {cycle + 1} стартует с анимацией",
          track.artist_card.isVisible() and track.artist_card in track._groups)
    check("исполнитель: карточка скрывается после затухания",
          wait_until(lambda: not track.artist_card.isVisible()))

track.btn_new_artist.click()
QTest.qWait(RISE_MS + 50)
track.btn_artist_cancel.click()
QTest.qWait(FADE_MS // 3)
track.btn_new_artist.click()
check("быстрое открытие отменяет предыдущее закрытие",
      wait_until(lambda: track._artist_fx.opacity() == 1.0)
      and track.artist_card.isVisible())
track.close()

# ============================================================
print("== ФАЗА 8: палитра и границы списка ==")
win._show_home()
for name in (*theme.THEMES, "Standart"):
    theme.apply_theme(app, name)
    QTest.qWait(40)
    frame = win.grab()
    image = frame.toImage()
    expected = theme.themed_color(theme.BG_MAIN).name()
    matches = []
    for widget, inset in ((win.pages, QPoint(6, 120)),
                          (win.home_page.viewport(), QPoint(3, 40))):
        position = widget.mapTo(win, inset) * frame.devicePixelRatio()
        matches.append(image.pixelColor(position).name() == expected)
    check(f"{name}: палитра холста и страницы меняется синхронно", all(matches))
    button_rule = app.styleSheet().split("#rateNowButton {", 1)[1].split("}", 1)[0]
    check(f"{name}: «Оценить?» использует акцент темы",
          f"background-color: {theme.themed_color(theme.ACCENT).name()};" in button_rule)

combo = DarkComboBox(win)
combo.setGeometry(300, 96, 170, 38)
combo.setMaxVisibleItems(6)
combo.addItems([f"Вариант {index}" for index in range(20)])
combo.show()
combo.showPopup()
QTest.qWait(80)
popup = combo.view().window()
scrollbar = combo.view().verticalScrollBar()
popup_frame = popup.grab().toImage()
check("видимая область списка обрезана по углам",
      popup.isVisible() and not popup.mask().contains(popup.rect().topLeft())
      and popup.mask().contains(popup.rect().center())
      and popup_frame.pixelColor(0, 0).alpha() == 0)
bar_origin = scrollbar.mapTo(popup, QPoint())
check("тонкий скроллбар внутри рамки выпадающего списка",
      isinstance(scrollbar, SlimScrollBar) and scrollbar.isVisible()
      and scrollbar.width() <= 6
      and popup.mask().contains(scrollbar.rect().translated(bar_origin)))
combo.hidePopup()
combo.deleteLater()

# ============================================================
print("== ФАЗА 9: оценивание с прослушиванием ==")
profile.tab_buttons[2].click()
profile.show()
QTest.qWait(40)
theme_select = profile.theme_select
check("настройки темы и базы выровнены влево",
      profile.btn_export_db.x() == profile.btn_import_db.x()
      and profile.btn_export_db.x() < theme_select.x()
      and profile.btn_export_db.x() < profile.btn_export_db.parentWidget().width() / 4)
profile.hide()

playlist = deepcopy(album)
playlist.source_id = ""
playlist.tracks = [
    TrackDraft("Первый трек", [ArtistDraft("Исполнитель")]),
    TrackDraft("Второй трек", [ArtistDraft("Исполнитель")]),
]
catalog = _parse_album({"result": {"id": 701, "title": playlist.title, "volumes": [[
    {"id": 101, "title": "Первый трек", "durationMs": 120_000,
     "artists": [{"name": "Исполнитель"}]},
    {"id": 102, "title": "Второй трек", "durationMs": 120_000,
     "artists": [{"name": "Исполнитель"}]},
]]}}, "701")
queue = match_album_tracks(playlist, catalog)
check("треки сопоставлены по названиям и исполнителям, а не по позиции",
      [track.uri for track in match_album_tracks(
          playlist, type(catalog)(tracks=catalog.tracks[::-1], album_id=catalog.album_id)
      )] == [track.uri for track in queue])
wizard = RateAlbumOverlay(win)
wizard.set_cloud_members(win._cloud_upload.members())
wizard.open_for(playlist)
check("кнопка прослушивания скрыта на первом шаге", not wizard.btn_listen.isVisible())
wizard.rater_buttons[profile_id].click()
wizard.go_to_step(1)
check("кнопка прослушивания появляется на шаге оценок", wizard.btn_listen.isVisible())
wizard.btn_listen.click()
wizard._playback_choice.yandex_button.click()
player = wizard._player
check("название первого трека появляется с нулевой непрозрачности",
      player._text_animation.state() == motion.QAbstractAnimation.State.Running
      and player._text_reveal._progress == 0.0)
check("название проявилось полностью", wait_until(lambda: player._text_reveal._progress == 1.0))
check("статус сверху, а широкая шкала внизу над кнопками",
      player.status.mapTo(player, QPoint()).y() + player.status.height() < player.cover.mapTo(player, QPoint()).y()
      and player.progress.parentWidget().y() > player.cover.mapTo(player, QPoint()).y() + player.cover.height()
      and player.progress.width() > player.cover.width()
      and player.progress.parentWidget().geometry().bottom() < player.pause_button.mapTo(player, QPoint()).y())
check("альбому без источника можно указать ссылку",
      player.isVisible() and player.album_link.isVisible() and not wizard.steps.isVisible())
check("поля скрыты до конца трека", not player.rating_area.isVisible())

def media(position, second=False, playing=True, can_seek=True):
    return MediaSnapshot(
        queue[second].title, "Исполнитель", position, 120_000, playing, can_seek,
    )

calls = []
seek_calls = []
player._queue = queue
player._set_link_visible(False)

def record_media_call(action, *_, seek_ms=None):
    calls.append(action)
    if seek_ms is not None:
        seek_calls.append(seek_ms)
    return True

player._call = record_media_call
with patch("app.ui.pages.listen_and_rate.launch_yandex_desktop") as launch:
    player._request_track()
    player._open_client()
    check("в клиент передана ссылка на альбом нужного трека",
          launch.call_args.args[0] == queue[0].uri.partition("/track/")[0])
check("другой трек не получает команду Play",
      not queue[0].matches(media(1000, second=True)))
player._observe(media(4000, playing=False))
check("если нужный трек загружен в клиент, просим воспроизвести", calls[-1] == "start")
player._observe(media(111_000))
check("плеер показывает прошедшее и полное время",
      player.elapsed_time.text() == "1:51" and player.total_time.text() == "2:00"
      and player.progress.value() == 111_000)
player._observe(media(111_000, can_seek=False))
check("перемотка отключена без поддержки медиасессии", not player.progress.isEnabled())
player._observe(media(111_000))
slider_y = player.progress.height() // 2
QTest.mousePress(player.progress, Qt.MouseButton.LeftButton, pos=QPoint(32, slider_y))
QTest.mouseMove(player.progress, QPoint(160, slider_y))
check("движение ползунка показывает время без команды до отпускания",
      not seek_calls and player.elapsed_time.text() == "1:00")
QTest.mouseRelease(player.progress, Qt.MouseButton.LeftButton, pos=QPoint(160, slider_y))
check("отпускание ползунка отправляет одну команду", seek_calls == [60_000])
player._on_media_result(player._generation, "seek", None, False, "")
QTest.mouseClick(player.progress, Qt.MouseButton.LeftButton,
                 pos=QPoint(player.progress.width() - 1, player.progress.height() // 2))
check("клик в конец шкалы ограничивается точкой автопаузы",
      seek_calls == [60_000, 117_000] and player.progress.value() == 117_000)
player._on_media_result(player._generation, "seek", None, False, "")
check("отказ перемотки возвращает реальную позицию, не закрывая плеер",
      player.progress.value() == 111_000 and player._phase == "playing")
check("за 9 секунд оценки скрыты", not player.rating_area.isVisible())
player._observe(media(113_000))
check("за 7 секунд появились оценки", player.rating_area.isVisible())
wizard._player_cells[0].setText("8.5")
check("оценка из плеера попала в таблицу",
      wizard._values[0][0] == 8.5 and wizard._cells[0][0].text() == "8.5")
previous_window_state = win.windowState()
playback_generation = player._generation
win.showMinimized()
QTest.qWait(40)
check("сворачивание не закрывает плеер и не останавливает медиасессию",
      win.isMinimized() and wizard._surface.currentWidget() is player
      and player._phase == "playing" and player._generation == playback_generation
      and "cleanup" not in calls)
win.setWindowState(previous_window_state)
QTest.qWait(40)
check("после восстановления тот же трек, время и оценка",
      player.isVisible() and player._index == 0 and player.elapsed_time.text() == "1:53"
      and wizard._player_cells[0].text() == "8.5")
player._toggle_play()
check("кнопка паузы управляет медиасессией", calls[-1] == "pause")
player._observe(media(117_000))
check("за 3 секунды запрошена автопауза", calls[-1] == "gate")
player._on_media_result(player._generation, "gate", None, True, "")
player._observe(media(117_000, playing=False))
player._busy = True
player.progress.setValue(60_000)
check("перемотка ожидает завершения текущего запроса",
      player._queued_seek == 60_000 and not player.next_button.isEnabled())
player._on_media_result(player._generation, "poll", media(117_000, playing=False), True, "")
player._on_media_result(player._generation, "seek", None, True, "")
player._observe(media(117_000, playing=False))
check("устаревшая позиция не сбрасывает запрошенную перемотку",
      player.progress.value() == 60_000 and player._phase == "gate")
player._observe(media(60_000, playing=False))
check("перемотка назад снимает автопаузу, скрывает поля и сохраняет оценку",
      player._phase == "playing" and player.pause_button.isEnabled()
      and not player.rating_area.isVisible() and wizard._player_cells[0].text() == "8.5")
player._observe(media(117_000, playing=False))
win.showMinimized()
QTest.qWait(40)
win.setWindowState(previous_window_state)
QTest.qWait(40)
check("сворачивание сохраняет паузу для оценивания и активную стрелку",
      player.isVisible() and player._phase == "gate" and player.next_button.isEnabled()
      and wizard._player_cells[0].text() == "8.5")
record_call = player._call
player._call = lambda *_: False
player.next_button.click()
check("стрелка запоминает нажатие во время чтения медиасессии",
      player._pending_action == "tail" and not player.next_button.isEnabled())
player._call = record_call
player._on_media_result(player._generation, "poll", media(117_000, playing=False), True, "")
check("стрелка запрашивает воспроизведение финала", calls[-1] == "tail")
player._on_media_result(player._generation, "tail", None, True, "")
player._observe(media(118_000))
check("финальные секунды сохраняют оценки на экране без новой паузы",
      player._index == 0 and calls[-1] == "tail" and player.rating_area.isVisible()
      and not player.rating_area.isEnabled())
player._observe(media(50, second=True))
check("при смене трека обновились данные, поля снова скрыты",
      player._index == 1 and player.title_label.text() == queue[1].title
      and not player.rating_area.isVisible())
check("при смене трека текст проявляется заново, время не переносится",
      player._text_animation.state() == motion.QAbstractAnimation.State.Running
      and player._text_reveal._progress == 0.0
      and player.elapsed_time.text() == "0:00" and player.total_time.text() == "2:00")
player._observe(media(117_000, second=True, playing=False))
wizard._player_cells[0].setText("9")
player._on_media_result(player._generation, "tail", None, True, "")
player._observe(media(120_000, second=True, playing=False))
check("после финального трека открываются итоги",
      not player.isVisible() and wizard.steps.currentIndex() == 2
      and wizard._values == [[8.5], [9]])
wizard.go_to_step(1)
with patch.dict(os.environ, {"MUSICRATING_REDUCED_MOTION": "1"}):
    wizard.btn_listen.click()
    wizard._playback_choice.yandex_button.click()
    check("режим уменьшенного движения показывает текст сразу",
          player._text_animation.state() == motion.QAbstractAnimation.State.Stopped
          and player._text_reveal._progress == 1.0)
win.activateWindow()
QTest.qWait(40)
QTest.keyClick(player.album_link, Qt.Key.Key_Escape)
check("Esc возвращает в таблицу без потери оценок",
      wizard.steps.isVisible() and not player.isVisible() and wizard._values == [[8.5], [9]])
wizard.btn_listen.click()
wizard._playback_choice.yandex_button.click()
wizard.hide()
check("явное закрытие мастера по-прежнему завершает прослушивание",
      wizard._surface.currentWidget() is wizard._form and player._phase == "idle")

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
