import logging
import os
import tempfile
import time
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from event_sources import (
    START_SCAN_NOTIFICATION_SOURCE,
    START_SCAN_PROCESSING_MODE,
    WATCHER_NOTIFICATION_SOURCE,
    WATCHER_PROCESSING_MODE,
)
from notifications import NOTIFICATION_SHOWN, NotificationManager
from service import CleanDeskService
from ui import MainWindow


class CapturingNotificationManager(NotificationManager):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.messages: list[tuple[str, bool]] = []

    def notify(
        self,
        message: str,
        *,
        allow_foreground: bool = False,
        bypass_enabled: bool = False,
        diagnostic_context: str = "",
    ) -> str:
        self.messages.append((message, allow_foreground))
        return NOTIFICATION_SHOWN


class BackgroundNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.settings = {"notifications_enabled": True}
        self.background = True
        self.tray_icon = QSystemTrayIcon()
        self.manager = CapturingNotificationManager(
            self.tray_icon,
            lambda: dict(self.settings),
            lambda: not self.background,
            logging.getLogger("test.notifications"),
            background_provider=lambda: self.background,
        )

    def tearDown(self) -> None:
        self.manager.shutdown()
        self.tray_icon.deleteLater()

    @staticmethod
    def result(
        folder_id: str,
        folder_name: str,
        source: str = WATCHER_NOTIFICATION_SOURCE,
        mode: str = WATCHER_PROCESSING_MODE,
    ) -> dict:
        return {
            "source": source,
            "mode": mode,
            "folder_id": folder_id,
            "folder_name": folder_name,
            "source_root": rf"C:\Demo\{folder_name}",
        }

    def test_manual_and_foreground_results_are_not_aggregated(self) -> None:
        self.manager.aggregate_background_organized(self.result("a", "Downloads", source="manual"))
        self.background = False
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))

        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [])

    def test_single_folder_results_are_aggregated_once(self) -> None:
        for _ in range(5):
            self.manager.aggregate_background_organized(self.result("a", "Downloads"))

        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [("“Downloads”已整理 5 个文件。", True)])

    def test_multiple_folders_use_unique_folder_count(self) -> None:
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))
        self.manager.aggregate_background_organized(self.result("b", "CleanDesk_Demo"))

        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [("已在 2 个文件夹中整理 3 个文件。", True)])

    def test_disabled_results_are_not_cached(self) -> None:
        self.settings["notifications_enabled"] = False
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))
        self.settings["notifications_enabled"] = True

        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [])

    def test_disabling_notifications_clears_pending_results(self) -> None:
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))
        self.manager.handle_settings_changed({"notifications_enabled": False})
        self.manager.handle_settings_changed({"notifications_enabled": True})

        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [])

    def test_shutdown_discards_pending_results(self) -> None:
        self.manager.aggregate_background_organized(self.result("a", "Downloads"))

        self.manager.shutdown()
        self.manager.flush_background_organized()

        self.assertEqual(self.manager.messages, [])
        self.assertFalse(self.manager.organize_timer.isActive())

    def test_aggregation_window_is_eight_seconds(self) -> None:
        self.assertEqual(self.manager.organize_timer.interval(), 8000)

    def test_aggregation_timer_lives_in_gui_thread(self) -> None:
        self.assertIs(self.manager.thread(), self.app.thread())
        self.assertIs(self.manager.organize_timer.thread(), self.app.thread())


class WindowStateStub:
    def __init__(self, visible: bool, minimized: bool, tray_mode: bool = False) -> None:
        self.visible = visible
        self.minimized = minimized
        self._tray_mode_active = tray_mode
        self.service = type(
            "ServiceStub",
            (),
            {"logger": logging.getLogger("test.window-state")},
        )()

    def isVisible(self) -> bool:
        return self.visible

    def isMinimized(self) -> bool:
        return self.minimized


class WindowBackgroundStateTests(unittest.TestCase):
    def test_visible_normal_window_is_not_background(self) -> None:
        window = WindowStateStub(visible=True, minimized=False)
        self.assertFalse(MainWindow._is_main_window_background(window))

    def test_hidden_or_minimized_window_is_background(self) -> None:
        hidden = WindowStateStub(visible=False, minimized=False)
        minimized = WindowStateStub(visible=True, minimized=True)
        tray = WindowStateStub(visible=True, minimized=False, tray_mode=True)
        self.assertTrue(MainWindow._is_main_window_background(hidden))
        self.assertTrue(MainWindow._is_main_window_background(minimized))
        self.assertTrue(MainWindow._is_main_window_background(tray))


class SignalSink:
    def __init__(self) -> None:
        self.values: list[dict] = []

    def emit(self, value: dict) -> None:
        self.values.append(value)


class ServiceMoveSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = type("ServiceStub", (), {})()
        self.service.pending_undo_batches = {}
        self.service.activity_emitted = SignalSink()
        self.service.watcher_file_moved = SignalSink()
        self.service.start_scan_file_moved = SignalSink()
        self.service.logger = logging.getLogger("test.service-source")
        self.move = {
            "batch_id": "",
            "filename": "report.pdf",
            "original_path": r"C:\Demo\report.pdf",
            "target_path": r"C:\Demo\PDF\report.pdf",
            "folder_id": "folder-a",
            "folder_name": "Demo",
            "source_root": r"C:\Demo",
            "target_relative": r"PDF\report.pdf",
            "rule_name": "PDF",
        }

    def test_manual_move_does_not_emit_watcher_result(self) -> None:
        CleanDeskService._record_moved_file(self.service, {**self.move, "mode": "manual"})

        self.assertEqual(self.service.watcher_file_moved.values, [])
        self.assertEqual(len(self.service.activity_emitted.values), 1)

    def test_auto_move_emits_one_explicit_watcher_result(self) -> None:
        CleanDeskService._record_moved_file(
            self.service,
            {**self.move, "mode": WATCHER_PROCESSING_MODE},
        )

        self.assertEqual(
            self.service.watcher_file_moved.values,
            [
                {
                    "source": WATCHER_NOTIFICATION_SOURCE,
                    "mode": WATCHER_PROCESSING_MODE,
                    "folder_id": "folder-a",
                    "folder_name": "Demo",
                    "source_root": r"C:\Demo",
                }
            ],
        )
        self.assertEqual(len(self.service.activity_emitted.values), 1)

    def test_start_scan_move_emits_explicit_background_result(self) -> None:
        CleanDeskService._record_moved_file(
            self.service,
            {**self.move, "mode": START_SCAN_PROCESSING_MODE},
        )

        self.assertEqual(
            self.service.start_scan_file_moved.values,
            [
                {
                    "source": START_SCAN_NOTIFICATION_SOURCE,
                    "mode": START_SCAN_PROCESSING_MODE,
                    "folder_id": "folder-a",
                    "folder_name": "Demo",
                    "source_root": r"C:\Demo",
                }
            ],
        )
        self.assertEqual(self.service.watcher_file_moved.values, [])


class WatcherNotificationEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    @staticmethod
    def wait_until(predicate, timeout: float = 6.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    @staticmethod
    def process_events_for(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_real_watcher_signal_reaches_native_notification_once(self) -> None:
        previous_cwd = os.getcwd()
        service = None
        window = None
        with tempfile.TemporaryDirectory(prefix="cleandesk_notify_e2e_", ignore_cleanup_errors=True) as temp_dir:
            try:
                os.chdir(temp_dir)
                monitored = Path(temp_dir) / "Downloads"
                monitored.mkdir()

                service = CleanDeskService()
                service.config["welcome_shown"] = True
                folder = service.add_monitored_folder(str(monitored))
                service.add_rule(
                    {
                        "name": "PDF",
                        "type": "extension",
                        "extensions": [".pdf"],
                        "target": "PDF",
                        "enabled": True,
                    }
                )
                service.update_settings(
                    {
                        "scan_existing_on_start": False,
                        "notifications_enabled": True,
                    }
                )
                window = MainWindow(service)
                window.notification_manager.organize_timer.setInterval(2000)
                native_calls: list[tuple[str, str]] = []

                def capture_native(message: str, diagnostic_context: str = "") -> str:
                    native_calls.append((message, diagnostic_context))
                    return NOTIFICATION_SHOWN

                window.notification_manager.native_notification_sender = capture_native
                window.show()
                self.process_events_for(0.05)
                self.assertFalse(window._is_main_window_background())

                service.start()
                self.assertTrue(service.is_running)

                foreground_file = monitored / "foreground.pdf"
                foreground_file.write_bytes(b"")
                foreground_target = monitored / "PDF" / foreground_file.name
                self.assertTrue(self.wait_until(foreground_target.exists))
                self.process_events_for(0.2)
                self.assertEqual(native_calls, [])
                self.assertGreaterEqual(window.activity_list.count(), 1)

                service.stop()
                manual_file = monitored / "manual.pdf"
                manual_file.write_bytes(b"")
                service.scan_now()
                manual_target = monitored / "PDF" / manual_file.name
                self.assertTrue(self.wait_until(manual_target.exists))
                self.process_events_for(0.2)
                self.assertEqual(native_calls, [])
                self.assertTrue(service.undo_stack)

                service.update_settings(
                    {
                        "scan_existing_on_start": True,
                        "close_behavior": "minimize_to_tray",
                    }
                )
                window._tray_available = True
                window._tray_hint_shown = True
                window.close()
                self.process_events_for(0.05)
                self.assertTrue(window._tray_mode_active)
                self.assertTrue(window._is_main_window_background())

                start_scan_file = monitored / "start_scan.pdf"
                start_scan_file.write_bytes(b"")
                service.start()
                start_scan_target = monitored / "PDF" / start_scan_file.name
                self.assertTrue(self.wait_until(start_scan_target.exists))
                self.assertTrue(self.wait_until(lambda: len(native_calls) == 1))
                self.assertEqual(
                    native_calls,
                    [("“Downloads”已整理 1 个文件。", "BackgroundNotify")],
                )

                native_calls.clear()
                service.stop()
                service.update_settings({"scan_existing_on_start": False})
                service.start()

                background_file = monitored / "background.pdf"
                background_file.write_bytes(b"")
                background_target = monitored / "PDF" / background_file.name
                self.assertTrue(self.wait_until(background_target.exists))
                self.assertTrue(self.wait_until(lambda: len(native_calls) == 1))
                self.assertEqual(
                    native_calls,
                    [("“Downloads”已整理 1 个文件。", "BackgroundNotify")],
                )

                native_calls.clear()
                grouped_files = [monitored / f"grouped_{index}.pdf" for index in range(3)]
                for item in grouped_files:
                    item.write_bytes(b"")
                grouped_targets = [monitored / "PDF" / item.name for item in grouped_files]
                self.assertTrue(self.wait_until(lambda: all(item.exists() for item in grouped_targets)))
                self.assertTrue(self.wait_until(lambda: len(native_calls) == 1))
                self.assertEqual(
                    native_calls,
                    [("“Downloads”已整理 3 个文件。", "BackgroundNotify")],
                )

                native_calls.clear()
                service.update_settings({"notifications_enabled": False})
                disabled_file = monitored / "disabled.pdf"
                disabled_file.write_bytes(b"")
                disabled_target = monitored / "PDF" / disabled_file.name
                self.assertTrue(self.wait_until(disabled_target.exists))
                self.process_events_for(0.2)
                self.assertEqual(native_calls, [])
                self.assertEqual(window.notification_manager.organized_file_count, 0)

                service.stop()
                window.notification_manager.shutdown()
                self.assertFalse(window.notification_manager.organize_timer.isActive())

                log_text = Path("logs/app.log").read_text(encoding="utf-8")
                self.assertIn("[BackgroundNotify] watcher event detected", log_text)
                self.assertIn("[BackgroundNotify] watcher move success", log_text)
                self.assertIn("[BackgroundNotify] UI slot received", log_text)
                self.assertIn("[BackgroundNotify] timer timeout", log_text)
                self.assertIn("[BackgroundNotify] notification result=shown", log_text)
            finally:
                if window is not None:
                    window.notification_manager.shutdown()
                    window.deleteLater()
                if service is not None:
                    service.shutdown()
                    for handler in list(service.logger.handlers):
                        if isinstance(handler, RotatingFileHandler):
                            service.logger.removeHandler(handler)
                            handler.close()
                QApplication.processEvents()
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
