import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class CreatedFileHandler(FileSystemEventHandler):
    def __init__(self, watcher: "FolderWatcher", folder: dict) -> None:
        super().__init__()
        self.watcher = watcher
        self.folder = dict(folder)

    def on_created(self, event) -> None:
        if not event.is_directory:
            self.watcher.file_detected.emit(self._payload(event.src_path))

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self.watcher.file_detected.emit(self._payload(event.dest_path))

    def _payload(self, file_path: str) -> dict:
        return {
            "file_path": file_path,
            "folder_id": str(self.folder.get("id", "")),
            "source_root": str(self.folder.get("path", "")),
            "display_name": str(self.folder.get("display_name", "") or Path(str(self.folder.get("path", ""))).name),
        }


class FolderWatcher(QObject):
    file_detected = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__()
        self.logger = logger
        self.observer: Observer | None = None

    def start(self, folders: str | list[dict]) -> None:
        self.stop()
        prepared_folders = self._prepare_folders(folders)
        if not prepared_folders:
            raise RuntimeError("No valid monitored folder is available.")

        self.observer = Observer()
        for folder in prepared_folders:
            path = Path(str(folder.get("path", "")))
            self.observer.schedule(CreatedFileHandler(self, folder), str(path), recursive=False)
        self.observer.start()
        self.logger.info("Folder watcher active for %s folder(s)", len(prepared_folders))

    def stop(self) -> None:
        if not self.observer:
            return
        observer = self.observer
        self.observer = None
        observer.stop()
        observer.join(timeout=3)
        self.logger.info("Folder watcher stopped")

    def _prepare_folders(self, folders: str | list[dict]) -> list[dict]:
        if isinstance(folders, (str, Path)):
            path = Path(folders)
            folders = [
                {
                    "id": "",
                    "path": str(path),
                    "display_name": path.name,
                }
            ]

        prepared_folders = []
        for folder in folders:
            path = Path(str(folder.get("path", "")))
            if not path.exists() or not path.is_dir():
                raise RuntimeError(f"The monitored folder does not exist: {path}")
            prepared = dict(folder)
            prepared["path"] = str(path)
            prepared_folders.append(prepared)
        return prepared_folders
