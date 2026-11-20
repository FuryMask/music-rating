"""Финальные скриншоты версии с анимациями (offscreen).

Запуск:  python checks/screenshots.py
Сохранение: checks/screenshots/
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

scratch = TemporaryDirectory(prefix="music-rating-screenshots-", ignore_cleanup_errors=True)
os.environ["MUSICRATING_DATA_DIR"] = scratch.name

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])
app.setApplicationName("Music Rating")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))

from app.theme import apply_theme
from app.store import STORE
from app.ui.main_window import MainWindow
from checks.fixtures.library import populate_library

apply_theme(app)
populate_library(STORE)
OUT = ROOT / "checks" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

win = MainWindow()
win.resize(1440, 900)
win.show()
QTest.qWait(900)


def shot(name: str) -> None:
    win.grab().save(str(OUT / f"{name}.png"))
    print("saved", name)


def hover(widget) -> None:
    centre = QPointF(widget.rect().center())
    globe = QPointF(widget.mapToGlobal(widget.rect().center()))
    QApplication.sendEvent(widget, QEnterEvent(centre, globe, globe))


shot("home")

rated = [a for a in STORE.albums if a.rating is not None]
if rated:
    win.open_album(rated[0])
    QTest.qWait(70)
    shot("transition")
    QTest.qWait(400)
    shot("album")
    QTest.keyClick(win, Qt.Key.Key_Escape)
    QTest.qWait(500)

# Ховер карточки + прокрученная лента с плиткой «Смотреть все»
win._show_home()
QTest.qWait(600)
cards = win.home_page.section_rated.cards()
row = win.home_page.section_rated._row
if row is not None:
    row.horizontalScrollBar().setValue(row.horizontalScrollBar().maximum())
    QTest.qWait(200)
    tile = cards[-1] if cards else None
    if tile is not None and tile.objectName() == "viewAllTile":
        hover(tile)
        QTest.qWait(320)
        shot("tile")
    else:
        shot("tile")

if cards and row is not None:
    row.horizontalScrollBar().setValue(0)
    QTest.qWait(250)
    hover(cards[0])
    QTest.qWait(320)
    shot("hover")

# Волна от нажатия на «+»
btn = win.sidebar.btn_add
QTest.mousePress(btn, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
QTest.qWait(80)
win.grab().copy(0, 800, 260, 100).save(str(OUT / "ripple.png"))
QTest.mouseRelease(btn, Qt.MouseButton.LeftButton,
                   Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
print("done")
win.close()
STORE._conn.close()
scratch.cleanup()
