import os
import sys


def main():
    from . import crashlog
    crashlog.install()
    if sys.platform == "win32":
        import ctypes
        try:  # own taskbar icon/group instead of python.exe
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spectra.Inspector")
        except Exception:  # noqa: BLE001
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow
    from .gui.widgets import apply_dark_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Spectra Inspector")
    apply_dark_theme(app)
    w = MainWindow()
    crashlog.sink = lambda text: w.ui.post(lambda: w.log(text))
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
