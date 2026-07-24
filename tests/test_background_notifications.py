import logging
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

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
    def result(folder_id: str, folder_name: str, source: str = "watcher") -> dict:
        return {
            "source": source,
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
    def __init__(self, visible: bool, minimized: bool) -> None:
        self.visible = visible
        self.minimized = minimized

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
        self.assertTrue(MainWindow._is_main_window_background(hidden))
        self.assertTrue(MainWindow._is_main_window_background(minimized))


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
        CleanDeskService._record_moved_file(self.service, {**self.move, "mode": "auto"})

        self.assertEqual(
            self.service.watcher_file_moved.values,
            [
                {
                    "source": "watcher",
                    "folder_id": "folder-a",
                    "folder_name": "Demo",
                    "source_root": r"C:\Demo",
                }
            ],
        )
        self.assertEqual(len(self.service.activity_emitted.values), 1)


if __name__ == "__main__":
    unittest.main()
