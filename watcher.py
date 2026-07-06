import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class CreatedFileHandler(FileSystemEventHandler):
    def __init__(self, watcher: "FolderWatcher") -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event) -> None:
        if not event.is_directory:
            self.watcher.file_detected.emit(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self.watcher.file_detected.emit(event.dest_path)


class FolderWatcher(QObject):
    file_detected = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__()
        self.logger = logger
        self.observer: Observer | None = None

    def start(self, folder: str) -> None:
        self.stop()
        path = Path(folder)
        if not path.exists() or not path.is_dir():
            raise RuntimeError("The monitored folder does not exist.")

        self.observer = Observer()
        self.observer.schedule(CreatedFileHandler(self), str(path), recursive=False)
        self.observer.start()
        self.logger.info("Folder watcher active: %s", path)

    def stop(self) -> None:
        if not self.observer:
            return
        observer = self.observer
        self.observer = None
        observer.stop()
        observer.join(timeout=3)
        self.logger.info("Folder watcher stopped")
