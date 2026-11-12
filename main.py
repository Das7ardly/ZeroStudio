"""ZeroStudio entry point."""
import os
import sys

from PySide6.QtWidgets import QApplication

from zerostudio import APP_NAME
from zerostudio.engine import Engine
from zerostudio.settings import Settings
from zerostudio.ui import theme
from zerostudio.ui.main_window import MainWindow, selftest


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    theme.apply(app)
    from zerostudio.ui.brand import app_icon
    app.setWindowIcon(app_icon())
    settings = Settings.load()
    engine = Engine(settings.mkvtoolnix_dir)
    win = MainWindow(settings, engine)
    win.show()
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    st_dir = os.environ.get("ZEROSTUDIO_SELFTEST")
    if st_dir:
        extra = [f for f in os.environ.get("ZEROSTUDIO_SELFTEST_FILES", "").split(os.pathsep) if f]
        selftest(win, st_dir, extra or files)
    elif files:
        win.open_files(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
