import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from version import APP_NAME


NOTIFICATION_SHOWN = "shown"
NOTIFICATION_DISABLED = "disabled"
NOTIFICATION_TRAY_UNAVAILABLE = "tray_unavailable"
NOTIFICATION_UNSUPPORTED = "unsupported"
NOTIFICATION_SUPPRESSED = "suppressed"
NOTIFICATION_FAILED = "failed"


class NotificationManager(QObject):
    def __init__(
        self,
        tray_icon: QSystemTrayIcon,
        settings_provider: Callable[[], dict],
        foreground_provider: Callable[[], bool],
        logger: logging.Logger,
        background_provider: Callable[[], bool] | None = None,
        duplicate_window_ms: int = 7000,
        organize_window_ms: int = 8000,
    ) -> None:
        super().__init__(tray_icon)
        self.tray_icon = tray_icon
        self.settings_provider = settings_provider
        self.foreground_provider = foreground_provider
        self.background_provider = background_provider or (lambda: not foreground_provider())
        self.logger = logger
        self.duplicate_filenames: list[str] = []
        self.duplicate_timer = QTimer(self)
        self.duplicate_timer.setSingleShot(True)
        self.duplicate_timer.setInterval(duplicate_window_ms)
        self.duplicate_timer.timeout.connect(self.flush_duplicate_skips)
        self.organized_file_count = 0
        self.organized_folders: dict[str, str] = {}
        self.organize_timer = QTimer(self)
        self.organize_timer.setSingleShot(True)
        self.organize_timer.setInterval(organize_window_ms)
        self.organize_timer.timeout.connect(self.flush_background_organized)
        self.shutting_down = False

    def is_enabled(self) -> bool:
        try:
            return bool(self.settings_provider().get("notifications_enabled", True))
        except Exception:
            self.logger.exception("Unable to read notification setting")
            return True

    def notify(
        self,
        message: str,
        *,
        allow_foreground: bool = False,
        bypass_enabled: bool = False,
    ) -> str:
        if self.shutting_down:
            return NOTIFICATION_FAILED
        if not bypass_enabled and not self.is_enabled():
            self.logger.info("Notification skipped because notifications are disabled")
            return NOTIFICATION_DISABLED
        try:
            if self.tray_icon is None:
                self.logger.warning("Notification skipped because the tray icon is missing")
                return NOTIFICATION_TRAY_UNAVAILABLE
            if not allow_foreground and self.foreground_provider():
                self.logger.info("Notification suppressed while the main window is in the foreground")
                return NOTIFICATION_SUPPRESSED
            tray_available = QSystemTrayIcon.isSystemTrayAvailable()
            tray_visible = self.tray_icon.isVisible()
            supports_messages = QSystemTrayIcon.supportsMessages()
            self.logger.info(
                "Notification diagnostics: enabled=%s, tray_available=%s, tray_visible=%s, supports_messages=%s",
                self.is_enabled(),
                tray_available,
                tray_visible,
                supports_messages,
            )
            if not tray_available or not tray_visible:
                self.logger.warning("Notification skipped because the system tray is unavailable")
                return NOTIFICATION_TRAY_UNAVAILABLE
            if not supports_messages:
                self.logger.warning("Notification skipped because tray messages are unsupported")
                return NOTIFICATION_UNSUPPORTED
            self.tray_icon.showMessage(
                APP_NAME,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            self.logger.info("Notification requested from QSystemTrayIcon: %s", message)
            return NOTIFICATION_SHOWN
        except Exception:
            self.logger.exception("Unable to show system tray notification")
            return NOTIFICATION_FAILED

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
            message = f"“{filenames[0]}”因名称重复，已跳过整理。"
        else:
            message = f"{len(filenames)} 个文件因名称重复，已跳过整理。"
        self.notify(message)

    def aggregate_background_organized(self, result: dict) -> None:
        if self.shutting_down or not self.is_enabled():
            return
        if str(result.get("source", "")) != "watcher":
            return
        try:
            if not self.background_provider():
                return
        except Exception:
            self.logger.exception("Unable to determine whether the main window is in the background")
            return

        folder_name = str(result.get("folder_name", "")).strip()
        source_root = str(result.get("source_root", "")).strip()
        if not folder_name and source_root:
            folder_name = Path(source_root).name
        folder_name = folder_name or "监控文件夹"

        folder_id = str(result.get("folder_id", "")).strip()
        folder_key = folder_id or source_root.casefold() or folder_name.casefold()
        self.organized_folders[folder_key] = folder_name
        self.organized_file_count += 1
        if not self.organize_timer.isActive():
            self.organize_timer.start()

    def flush_background_organized(self) -> None:
        file_count = self.organized_file_count
        folders = dict(self.organized_folders)
        self._clear_background_organized()
        if not file_count or not folders:
            return
        if len(folders) == 1:
            folder_name = next(iter(folders.values()))
            message = f"“{folder_name}”已整理 {file_count} 个文件。"
        else:
            message = f"已在 {len(folders)} 个文件夹中整理 {file_count} 个文件。"
        # Results collected while hidden remain useful if the window is restored
        # before the aggregation window closes.
        self.notify(message, allow_foreground=True)

    def handle_settings_changed(self, settings: dict) -> None:
        if not bool(settings.get("notifications_enabled", True)):
            self._clear_background_organized()

    def _clear_background_organized(self) -> None:
        self.organize_timer.stop()
        self.organized_file_count = 0
        self.organized_folders.clear()

    def shutdown(self) -> None:
        self.shutting_down = True
        self.duplicate_timer.stop()
        self.duplicate_filenames.clear()
        self._clear_background_organized()
