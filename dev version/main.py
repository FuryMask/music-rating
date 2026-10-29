"""Точка входа Music Rating."""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.theme import apply_theme
from app.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Music Rating")
    app.setStyle("Fusion")  # нейтральная база, чтобы QSS выглядел одинаково везде
    app.setFont(QFont("Segoe UI", 10))
    apply_theme(app)

    window = MainWindow()
    window.showMaximized()  # развёрнутое окно (не полноэкранный режим)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
