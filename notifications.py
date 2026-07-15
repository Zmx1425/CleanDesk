import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from version import APP_NAME


class NotificationManager(QObject):
    def __init__(
        self,
        tray_icon: QSystemTrayIcon,
        settings_provider: Callable[[], dict],
        foreground_provider: Callable[[], bool],
        logger: logging.Logger,
        duplicate_window_ms: int = 7000,
    ) -> None:
        super().__init__(tray_icon)
        self.tray_icon = tray_icon
        self.settings_provider = settings_provider
        self.foreground_provider = foreground_provider
        self.logger = logger
        self.duplicate_filenames: list[str] = []
        self.duplicate_timer = QTimer(self)
        self.duplicate_timer.setSingleShot(True)
        self.duplicate_timer.setInterval(duplicate_window_ms)
        self.duplicate_timer.timeout.connect(self.flush_duplicate_skips)
        self.shutting_down = False

    def is_enabled(self) -> bool:
        try:
            return bool(self.settings_provider().get("notifications_enabled", True))
        except Exception:
            self.logger.exception("Unable to read notification setting")
            return True

    def notify(self, message: str, *, allow_foreground: bool = False) -> bool:
        if self.shutting_down or not self.is_enabled():
            return False
        try:
            if not allow_foreground and self.foreground_provider():
                return False
            if not QSystemTrayIcon.isSystemTrayAvailable() or not self.tray_icon.isVisible():
                self.logger.info("Notification skipped because the system tray is unavailable")
                return False
            self.tray_icon.showMessage(
                APP_NAME,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            return True
        except Exception:
            self.logger.exception("Unable to show system tray notification")
            return False

    def aggregate_duplicate_skip(self, filename: str) -> None:
        if self.shutting_down or not self.is_enabled():
            return
        cleaned_name = str(filename or "").strip()
        if cleaned_name:
            self.duplicate_filenames.append(cleaned_name)
        if self.duplicate_filenames and not self.duplicate_timer.isActive():
            self.duplicate_timer.start()

    def flush_duplicate_skips(self) -> None:
        filenames = list(self.duplicate_filenames)
        self.duplicate_filenames.clear()
        self.duplicate_timer.stop()
        if not filenames:
            return
        if len(filenames) == 1:
            message = f"“{filenames[0]}”因名称重复未整理。"
        else:
            message = f"{len(filenames)} 个文件因名称重复未整理。"
        self.notify(message)

    def shutdown(self) -> None:
        self.shutting_down = True
        self.duplicate_timer.stop()
        self.duplicate_filenames.clear()
