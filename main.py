import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from service import CleanDeskService
from single_instance import SHOW_MESSAGE, SingleInstanceError, SingleInstanceManager
from startup import STARTUP_ARGUMENT
from ui import MainWindow
from version import APP_NAME


WINDOWS_APP_USER_MODEL_ID = "CleanDesk.Zmx.CleanDesk"


def set_windows_app_user_model_id() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
        return result == 0
    except Exception:
        logging.getLogger(__name__).exception("Unable to set Windows AppUserModelID")
        return False


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def main(arguments: list[str] | None = None) -> int:
    launch_arguments = list(sys.argv if arguments is None else arguments)
    startup_mode = STARTUP_ARGUMENT in launch_arguments[1:]
    qt_arguments = [argument for argument in launch_arguments if argument != STARTUP_ARGUMENT]
    os.chdir(Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent)
    set_windows_app_user_model_id()

    app = QApplication(qt_arguments)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    icon_path = resource_path("assets/cleandesk.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    instance_manager = SingleInstanceManager()
    try:
        is_primary_instance = instance_manager.acquire("startup" if startup_mode else SHOW_MESSAGE)
    except SingleInstanceError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    if not is_primary_instance:
        return 0

    service = CleanDeskService()
    window = MainWindow(service)
    instance_manager.show_requested.connect(window._restore_from_tray)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    if startup_mode:
        window.initialize_hidden_startup()
    else:
        window.show()

    exit_code = app.exec()
    instance_manager.close()
    service.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
