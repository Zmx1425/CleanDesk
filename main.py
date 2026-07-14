import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from service import CleanDeskService
from startup import STARTUP_ARGUMENT
from ui import MainWindow
from version import APP_NAME


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def main(arguments: list[str] | None = None) -> int:
    launch_arguments = list(sys.argv if arguments is None else arguments)
    startup_mode = STARTUP_ARGUMENT in launch_arguments[1:]
    qt_arguments = [argument for argument in launch_arguments if argument != STARTUP_ARGUMENT]
    os.chdir(Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent)

    app = QApplication(qt_arguments)
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
    if startup_mode:
        window.initialize_hidden_startup()
    else:
        window.show()

    exit_code = app.exec()
    service.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
