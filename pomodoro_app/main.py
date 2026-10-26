"""Configure and launch the desktop application."""
import os
import sys

from PySide6.QtWidgets import QApplication

from pomodoro_app.instance import SingleInstance
from pomodoro_app.window import Pomodoro, STYLE


def main():
    """Start the primary timer window or activate an existing process."""
    app = QApplication(sys.argv)
    app.setApplicationName("pomodoro")
    app.setDesktopFileName("pomodoro")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    instance = SingleInstance(f"pomodoro-{os.getuid()}")
    if not instance.is_primary:
        return 0
    window = Pomodoro()
    instance.activated.connect(window.show_from_media)
    window.show()
    return app.exec()
