import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from service import CleanDeskService
from ui import MainWindow
from version import APP_NAME


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def main() -> int:
    os.chdir(Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    icon_path = resource_path("assets/cleandesk.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    service = CleanDeskService()
    window = MainWindow(service)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    exit_code = app.exec()
    service.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
