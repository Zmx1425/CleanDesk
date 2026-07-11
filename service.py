import logging
import os
import queue
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot

from engine import FileOrganizerEngine
from rules import assign_rule_priorities, display_rule_name, find_matching_rule, normalize_rules, sort_rules
from storage import ConfigStorage
from utils import (
    configure_logging,
    folder_compare_key,
    folder_display_name,
    is_hidden_or_temp_file,
    is_same_or_nested_folder,
    normalize_folder_path,
    timestamp,
)
from watcher import FolderWatcher


MIN_SUGGESTION_COUNT = 3
MAX_SUGGESTIONS = 5
SUGGESTION_GROUPS = [
    {"name": "种子文件", "target": "种子文件", "extensions": [".torrent"]},
    {"name": "安装包", "target": "安装包", "extensions": [".exe", ".msi"]},
    {"name": "压缩包", "target": "压缩包", "extensions": [".zip", ".rar", ".7z", ".tar", ".gz"]},
    {"name": "镜像文件", "target": "镜像文件", "extensions": [".iso"]},
    {"name": "安卓安装包", "target": "安卓安装包", "extensions": [".apk"]},
    {"name": "文档", "target": "文档", "extensions": [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"]},
]


class QtLogHandler(logging.Handler):
    def __init__(self, signal: Signal):
        super().__init__()
        self.signal = signal
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.signal.emit(self.format(record))


class FileProcessingWorker(QThread):
    file_moved = Signal(dict)
    file_skipped = Signal(dict)
    file_ignored = Signal(dict)
    batch_job_finished = Signal(str)
    conflict_requested = Signal(dict)
    conflict_hint_requested = Signal(str)

    def __init__(self, engine: FileOrganizerEngine, logger: logging.Logger) -> None:
        super().__init__()
        self.engine = engine
        self.logger = logger
        self.jobs: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_requested = threading.Event()
        self.recent_paths: dict[str, float] = {}
        self.recent_lock = threading.Lock()
        self.dedupe_seconds = 1.5
        self.canceled_batches: set[str] = set()
        self.conflict_responses: dict[str, dict[str, Any]] = {}
        self.conflict_lock = threading.Lock()

    def enqueue(
        self,
        file_path: str,
        base_folder: str,
        rules: list[dict],
        batch_id: str = "",
        mode: str = "auto",
        force: bool = False,
        folder_id: str = "",
        folder_name: str = "",
    ) -> bool:
        normalized_path = str(Path(file_path))
        now = time.monotonic()
        if not force:
            with self.recent_lock:
                self._clear_old_paths(now)
                last_seen = self.recent_paths.get(normalized_path)
                if last_seen and now - last_seen < self.dedupe_seconds:
                    self.logger.info("Duplicate file event ignored: %s", Path(normalized_path).name)
                    return False
                self.recent_paths[normalized_path] = now
        self.jobs.put(
            {
                "file_path": normalized_path,
                "base_folder": base_folder,
                "source_root": base_folder,
                "folder_id": folder_id,
                "folder_name": folder_name,
                "rules": [dict(rule) for rule in rules],
                "batch_id": batch_id,
                "mode": mode,
            }
        )
        return True

    def resolve_conflict(self, request_id: str, action: str) -> None:
        with self.conflict_lock:
            request = self.conflict_responses.get(request_id)
            if not request:
                return
            request["action"] = action
            request["event"].set()

    def stop(self) -> None:
        self.stop_requested.set()
        self.wait(3000)

    def run(self) -> None:
        while not self.stop_requested.is_set():
            try:
                job = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._process_with_retry(job)
            finally:
                batch_id = str(job.get("batch_id", ""))
                if batch_id:
                    self.batch_job_finished.emit(batch_id)
                self.jobs.task_done()

    def _process_with_retry(self, job: dict[str, Any]) -> None:
        file_path = str(job.get("file_path", ""))
        base_folder = str(job.get("base_folder", ""))
        rules = [dict(rule) for rule in job.get("rules", [])]
        batch_id = str(job.get("batch_id", ""))
        mode = str(job.get("mode", "auto"))
        if batch_id and batch_id in self.canceled_batches:
            return
        path = Path(file_path)
        delays = [0.4, 0.8, 1.2, 2.0]

        for attempt, delay in enumerate([0.0, *delays], start=1):
            if self.stop_requested.is_set():
                return
            if delay:
                time.sleep(delay)

            if not path.exists():
                return
            if not path.is_file() or path.parent != Path(base_folder):
                return
            matched_rule = find_matching_rule(path, rules)
            if matched_rule and matched_rule.get("action", "move") == "ignore":
                self.file_ignored.emit(
                    {
                        "filename": path.name,
                        "original_path": str(path.resolve()),
                        "rule_name": display_rule_name(matched_rule),
                        "folder_id": str(job.get("folder_id", "")),
                        "folder_name": str(job.get("folder_name", "")),
                        "source_root": str(job.get("source_root", base_folder)),
                    }
                )
                return
            if is_hidden_or_temp_file(path):
                self.logger.info("Queued file skipped because it is temporary or hidden: %s", path.name)
                return
            if not matched_rule:
                self.engine.process_file(str(path), base_folder, rules)
                return
            status = self._process_and_emit_move(path, base_folder, rules, batch_id, matched_rule, mode, job)
            if status in {"moved", "conflict_skipped", "canceled", "no_match", "ignored"}:
                return
            if attempt < len(delays) + 1:
                self.logger.info("File still unavailable, retrying: %s", path.name)

    def _process_and_emit_move(
        self,
        path: Path,
        base_folder: str,
        rules: list[dict],
        batch_id: str,
        matched_rule: dict,
        mode: str,
        job: dict[str, Any],
    ) -> str:
        original_path = path.resolve()
        resolver = None
        if mode in {"manual", "start_scan"}:
            resolver = lambda conflict: self._request_conflict_choice(conflict, batch_id)
        result = self.engine.process_file_result(str(path), base_folder, rules, resolver)
        status = str(result.get("status", "failed"))

        if status == "canceled" and batch_id:
            self.canceled_batches.add(batch_id)
        if status == "conflict_skipped":
            self.file_skipped.emit(
                {
                    "batch_id": batch_id,
                    "filename": path.name,
                    "reason": "因为目标位置存在同名文件，已跳过。",
                    "folder_id": str(job.get("folder_id", "")),
                    "folder_name": str(job.get("folder_name", "")),
                    "source_root": str(job.get("source_root", base_folder)),
                }
            )
            return status
        if status != "moved":
            return status

        target_path = Path(str(result.get("destination", ""))).resolve()
        target_relative = str(result.get("target_display") or target_path.name)
        conflict = bool(result.get("conflict"))
        final_name = str(result.get("final_name") or target_path.name)
        self._remember_recent_path(str(target_path))
        if mode == "auto" and conflict:
            self.conflict_hint_requested.emit(f"检测到同名文件，已保留为 {final_name}")
        self.file_moved.emit(
            {
                "batch_id": batch_id,
                "filename": path.name,
                "original_path": str(original_path),
                "target_path": str(target_path),
                "target_folder": str(target_path.parent),
                "target_relative": target_relative,
                "rule_name": display_rule_name(matched_rule),
                "conflict": conflict,
                "final_name": final_name,
                "mode": mode,
                "folder_id": str(job.get("folder_id", "")),
                "folder_name": str(job.get("folder_name", "")),
                "source_root": str(job.get("source_root", base_folder)),
            }
        )
        return status

    def _request_conflict_choice(self, conflict: dict, batch_id: str) -> str:
        request_id = uuid4().hex
        event = threading.Event()
        with self.conflict_lock:
            self.conflict_responses[request_id] = {"event": event, "action": "keep"}
        payload = dict(conflict)
        payload["request_id"] = request_id
        self.conflict_requested.emit(payload)
        event.wait()
        with self.conflict_lock:
            response = self.conflict_responses.pop(request_id, None)
        action = str((response or {}).get("action", "keep"))
        if action == "cancel" and batch_id:
            self.canceled_batches.add(batch_id)
        return action

    def _clear_old_paths(self, now: float) -> None:
        expired = [
            path
            for path, last_seen in self.recent_paths.items()
            if now - last_seen >= self.dedupe_seconds
        ]
        for path in expired:
            self.recent_paths.pop(path, None)

    def _remember_recent_path(self, file_path: str) -> None:
        with self.recent_lock:
            now = time.monotonic()
            self._clear_old_paths(now)
            self.recent_paths[str(Path(file_path))] = now


class CleanDeskService(QObject):
    folder_changed = Signal(str)
    status_changed = Signal(bool)
    rules_changed = Signal(list)
    log_emitted = Signal(str)
    activity_emitted = Signal(dict)
    undo_state_changed = Signal(bool)
    undo_completed = Signal(dict)
    conflict_requested = Signal(dict)
    conflict_hint_requested = Signal(str)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.storage = ConfigStorage()
        self.config = self.storage.load()
        self.rules = assign_rule_priorities(sort_rules(normalize_rules(self.config.get("rules", []))))
        self.monitored_folders = [dict(folder) for folder in self.config.get("monitored_folders", [])]
        self.active_folder_id = str(self.config.get("active_folder_id") or "")
        self.monitored_folder = self.get_active_folder_path()
        self.is_running = False
        self.running_folder_count = 0
        self.recent_logs: deque[str] = deque(maxlen=300)
        self.undo_stack: list[dict[str, Any]] = []
        self.pending_undo_batches: dict[str, dict[str, Any]] = {}
        self.is_undoing = False
        self.ignore_until: dict[str, float] = {}
        self.conflict_choice_handler = None
        self.logger = configure_logging()
        self.qt_log_handler = QtLogHandler(self.log_emitted)
        self.logger.addHandler(self.qt_log_handler)
        self.log_emitted.connect(self._remember_log_line)

        self.engine = FileOrganizerEngine(self.logger)
        self.worker = FileProcessingWorker(self.engine, self.logger)
        self.worker.file_moved.connect(self._record_moved_file)
        self.worker.file_skipped.connect(self._record_skipped_file)
        self.worker.file_ignored.connect(self._record_ignored_file)
        self.worker.batch_job_finished.connect(self._finish_batch_job)
        self.worker.conflict_requested.connect(self.conflict_requested)
        self.worker.conflict_hint_requested.connect(self.conflict_hint_requested)
        self.worker.start()
        self.watcher = FolderWatcher(self.logger)
        self.watcher.file_detected.connect(self.process_file)
        self.watcher.error_occurred.connect(self.error_occurred)

        self._persist_config()
        self.logger.info("CleanDesk ready")

    def get_monitored_folders(self) -> list[dict[str, Any]]:
        return [dict(folder) for folder in self.monitored_folders]

    def get_active_folder(self) -> dict[str, Any] | None:
        return next((dict(folder) for folder in self.monitored_folders if folder.get("id") == self.active_folder_id), None)

    def get_active_folder_path(self) -> str:
        active_folder = next((folder for folder in self.monitored_folders if folder.get("id") == self.active_folder_id), None)
        return str(active_folder.get("path", "")) if active_folder else ""

    def get_running_folder_count(self) -> int:
        return self.running_folder_count

    def set_active_folder(self, folder_id: str) -> dict[str, Any]:
        folder = next((folder for folder in self.monitored_folders if folder.get("id") == folder_id), None)
        if not folder:
            raise ValueError("未找到要选择的监控文件夹。")
        self.active_folder_id = str(folder["id"])
        self.monitored_folder = str(folder["path"])
        self._persist_config()
        self.folder_changed.emit(self.monitored_folder)
        self.logger.info("Active monitored folder changed to %s", self.monitored_folder)
        return dict(folder)

    def add_monitored_folder(self, path: str) -> dict[str, Any]:
        if self.is_running:
            raise ValueError("请先停止自动整理后再管理监控文件夹。")
        normalized_path = self._validate_monitored_folder_path(path)
        folder = {
            "id": uuid4().hex,
            "path": normalized_path,
            "display_name": folder_display_name(normalized_path),
        }
        self.monitored_folders.append(folder)
        if not self.active_folder_id:
            self.active_folder_id = folder["id"]
            self.monitored_folder = folder["path"]
            self.folder_changed.emit(self.monitored_folder)
        self._persist_config()
        self.logger.info("Monitored folder added: %s", normalized_path)
        return dict(folder)

    def remove_monitored_folder(self, folder_id: str) -> None:
        if self.is_running:
            raise ValueError("请先停止自动整理后再管理监控文件夹。")
        original_count = len(self.monitored_folders)
        self.monitored_folders = [folder for folder in self.monitored_folders if folder.get("id") != folder_id]
        if len(self.monitored_folders) == original_count:
            raise ValueError("未找到要移除的监控文件夹。")
        if self.active_folder_id == folder_id:
            self.active_folder_id = str(self.monitored_folders[0]["id"]) if self.monitored_folders else ""
            self.monitored_folder = self.get_active_folder_path()
            self.folder_changed.emit(self.monitored_folder)
        self._persist_config()
        self.logger.info("Monitored folder removed: %s", folder_id)

    def set_monitored_folder(self, folder: str) -> None:
        if self.is_running:
            self.error_occurred.emit("请先停止自动整理后再管理监控文件夹。")
            return
        try:
            normalized_path = self._validate_monitored_folder_path(folder, exclude_folder_id=self.active_folder_id or None)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            self.logger.exception("Failed to set monitored folder")
            return

        if self.active_folder_id:
            for monitored_folder in self.monitored_folders:
                if monitored_folder.get("id") == self.active_folder_id:
                    monitored_folder["path"] = normalized_path
                    monitored_folder["display_name"] = folder_display_name(normalized_path)
                    break
        else:
            created_folder = {
                "id": uuid4().hex,
                "path": normalized_path,
                "display_name": folder_display_name(normalized_path),
            }
            self.monitored_folders.append(created_folder)
            self.active_folder_id = created_folder["id"]

        self.monitored_folder = normalized_path
        self._persist_config()
        self.folder_changed.emit(self.monitored_folder)
        self.logger.info("Monitored folder changed to %s", self.monitored_folder)

    @Slot()
    def start(self) -> None:
        if self.is_running:
            return
        valid_folders = self._valid_monitored_folders(emit_activity=True)
        if not valid_folders:
            self.error_occurred.emit("没有可用的监控文件夹。")
            self.logger.error("Start skipped, no valid monitored folders")
            return
        self.logger.info("正在启动监听")
        batch_id = self._create_pending_batch()
        queued = self._queue_existing_files_for_folders(batch_id, valid_folders, mode="start_scan")
        if queued:
            self.logger.info("启动前扫描：发现 %s 个已有文件", queued)
        else:
            self.pending_undo_batches.pop(batch_id, None)
            self.logger.info("启动前扫描：未发现待处理文件")
        try:
            self.watcher.start(valid_folders)
        except RuntimeError as exc:
            self.pending_undo_batches.pop(batch_id, None)
            self.error_occurred.emit(str(exc))
            self.logger.exception("Unable to start watcher")
            return
        self.is_running = True
        self.running_folder_count = len(valid_folders)
        self.status_changed.emit(True)
        self.logger.info("已开始监听")

    @Slot()
    def stop(self) -> None:
        if not self.is_running:
            return
        self.watcher.stop()
        self.is_running = False
        self.running_folder_count = 0
        self.status_changed.emit(False)
        self.logger.info("已停止监听")

    @Slot()
    def scan_now(self) -> None:
        if not self._ensure_folder_ready():
            return
        self.logger.info("Manual scan started")
        batch_id = self._create_pending_batch()
        queued = self._queue_existing_files(batch_id)
        if not queued:
            self.pending_undo_batches.pop(batch_id, None)
        self.logger.info("Manual scan queued, %s file(s) found", queued)

    @Slot(object)
    def process_file(self, event: object) -> None:
        payload = self._event_payload(event)
        file_path = str(payload.get("file_path", ""))
        source_root = str(payload.get("source_root", ""))
        folder_id = str(payload.get("folder_id", ""))
        folder_name = str(payload.get("display_name", ""))
        if not file_path or not source_root:
            return
        if folder_id and folder_id not in {str(folder.get("id", "")) for folder in self.monitored_folders}:
            self.logger.info("Watcher event ignored for removed folder: %s", file_path)
            return
        if self._should_ignore_file_event(file_path):
            return
        batch_id = self._create_pending_batch()
        self._set_pending_batch_total(batch_id, 1)
        if self.worker.enqueue(
            file_path,
            source_root,
            self.rules,
            batch_id,
            mode="auto",
            folder_id=folder_id,
            folder_name=folder_name,
        ):
            return
        else:
            self.pending_undo_batches.pop(batch_id, None)

    @Slot(str, str)
    def resolve_name_conflict(self, request_id: str, action: str) -> None:
        self.worker.resolve_conflict(request_id, action)

    def _queue_existing_files(self, batch_id: str, mode: str = "manual") -> int:
        active_folder = self.get_active_folder()
        if not active_folder:
            self._set_pending_batch_total(batch_id, 0)
            return 0
        return self._queue_existing_files_for_folders(batch_id, [active_folder], mode=mode)

    def _queue_existing_files_for_folders(self, batch_id: str, folders: list[dict], mode: str = "manual") -> int:
        queued = 0
        jobs: list[tuple[Path, dict]] = []
        for folder in folders:
            base_folder = str(folder.get("path", ""))
            if not base_folder:
                continue
            for item in Path(base_folder).iterdir():
                if item.is_file() and not self._should_ignore_file_event(str(item)):
                    jobs.append((item, folder))

        self._set_pending_batch_total(batch_id, len(jobs))
        for item, folder in jobs:
            base_folder = str(folder.get("path", ""))
            if self.worker.enqueue(
                str(item),
                base_folder,
                self.rules,
                batch_id,
                mode,
                force=True,
                folder_id=str(folder.get("id", "")),
                folder_name=str(folder.get("display_name", "")),
            ):
                queued += 1
            else:
                self._finish_batch_job(batch_id)
        return queued

    def add_rule(self, rule: dict[str, Any]) -> None:
        prepared_rule = dict(rule)
        prepared_rule["action"] = "move"
        prepared_rule["id"] = prepared_rule.get("id") or uuid4().hex
        prepared_rule["enabled"] = bool(prepared_rule.get("enabled", True))
        prepared_rule["target"] = str(prepared_rule.get("target", "Unsorted")).strip() or "Unsorted"
        self.rules = assign_rule_priorities(sort_rules(normalize_rules([prepared_rule, *self.rules])))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Rule added: %s", prepared_rule.get("name", prepared_rule["id"]))

    def add_suggested_rules(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        created_rules = []
        covered_extensions = self._covered_extensions()
        for suggestion in suggestions:
            extensions = [
                self._normalize_extension(str(extension))
                for extension in suggestion.get("extensions", [])
                if self._normalize_extension(str(extension)) not in covered_extensions
            ]
            if not extensions:
                continue
            rule = {
                "id": uuid4().hex,
                "name": str(suggestion.get("name") or self._suggestion_name_for_extensions(extensions)),
                "type": "extension",
                "extensions": extensions,
                "target": str(suggestion.get("target") or suggestion.get("name") or "整理文件"),
                "enabled": True,
                "action": "move",
                "priority": (len(self.rules) + len(created_rules) + 1) * 10,
            }
            created_rules.append(rule)
            covered_extensions.update(extensions)

        if not created_rules:
            return []

        self.rules = assign_rule_priorities(sort_rules(normalize_rules([*self.rules, *created_rules])))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        for rule in created_rules:
            self.activity_emitted.emit(
                {
                    "time": timestamp()[11:16],
                    "status": "started",
                    "title": f"已添加智能建议：{display_rule_name(rule)}",
                    "detail": f"文件类型：{'、'.join(rule.get('extensions', []))}\n移动到：{rule.get('target', '')}",
                }
            )
            self.logger.info("Suggested rule added: %s %s", rule.get("name"), rule.get("extensions"))
        return created_rules

    def analyze_smart_suggestions(self) -> dict[str, Any]:
        folder = Path(self.monitored_folder)
        summary = {
            "total_files": 0,
            "covered_files": 0,
            "suggestions": [],
            "valid_folder": folder.exists() and folder.is_dir(),
        }
        if not summary["valid_folder"]:
            return summary

        covered_extensions = self._covered_extensions()
        extension_counts: dict[str, int] = {}
        covered_files = 0
        total_files = 0
        for item in folder.iterdir():
            if not item.is_file() or is_hidden_or_temp_file(item):
                continue
            extension = self._normalize_extension(item.suffix)
            if not extension:
                continue
            total_files += 1
            if extension in covered_extensions:
                covered_files += 1
                continue
            extension_counts[extension] = extension_counts.get(extension, 0) + 1

        suggestions = self._build_suggestions(extension_counts, covered_extensions)
        summary.update(
            {
                "total_files": total_files,
                "covered_files": covered_files,
                "suggestions": suggestions,
            }
        )
        self.activity_emitted.emit(
            {
                "time": timestamp()[11:16],
                "status": "started",
                "title": "已完成智能分析",
                "detail": f"发现 {len(suggestions)} 组整理建议",
            }
        )
        self.logger.info(
            "Smart suggestions analyzed: files=%s covered=%s suggestions=%s",
            total_files,
            covered_files,
            len(suggestions),
        )
        return summary

    def update_rule(self, rule_id: str, updates: dict[str, Any]) -> None:
        updated_rules = []
        changed = False
        for rule in self.rules:
            if rule.get("id") == rule_id:
                prepared_rule = dict(rule)
                prepared_rule.update(updates)
                prepared_rule["action"] = rule.get("action", "move")
                prepared_rule["id"] = rule_id
                prepared_rule["enabled"] = bool(prepared_rule.get("enabled", True))
                prepared_rule["target"] = str(prepared_rule.get("target", "Unsorted")).strip() or "Unsorted"
                updated_rules.append(prepared_rule)
                changed = True
            else:
                updated_rules.append(rule)
        if not changed:
            self.logger.warning("Rule update skipped, rule not found: %s", rule_id)
            return
        self.rules = assign_rule_priorities(sort_rules(normalize_rules(updated_rules)))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Rule updated: %s", rule_id)

    def delete_rule(self, rule_id: str) -> None:
        remaining_rules = [rule for rule in self.rules if rule.get("id") != rule_id]
        if len(remaining_rules) == len(self.rules):
            self.logger.warning("Rule delete skipped, rule not found: %s", rule_id)
            return
        self.rules = assign_rule_priorities(sort_rules(normalize_rules(remaining_rules)))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Rule deleted: %s", rule_id)

    def move_rule(self, rule_id: str, direction: int) -> None:
        if direction not in {-1, 1}:
            return
        index = next((idx for idx, rule in enumerate(self.rules) if rule.get("id") == rule_id), -1)
        target_index = index + direction
        if index < 0 or target_index < 0 or target_index >= len(self.rules):
            return
        reordered = list(self.rules)
        reordered[index], reordered[target_index] = reordered[target_index], reordered[index]
        self.rules = assign_rule_priorities(normalize_rules(reordered))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Rule moved: %s -> %s", rule_id, target_index)

    def reorder_rules(self, rule_ids: list[str]) -> None:
        ignore_rules = [rule for rule in self.rules if rule.get("action", "move") == "ignore"]
        move_rules = [rule for rule in self.rules if rule.get("action", "move") != "ignore"]
        rules_by_id = {str(rule.get("id", "")): rule for rule in move_rules}
        reordered = []
        seen_ids = set()
        for rule_id in rule_ids:
            rule = rules_by_id.get(str(rule_id))
            if not rule or str(rule_id) in seen_ids:
                continue
            reordered.append(rule)
            seen_ids.add(str(rule_id))

        if len(reordered) != len(move_rules):
            self.logger.warning("Rule reorder skipped because the rule id list is incomplete")
            return

        self.rules = assign_rule_priorities(normalize_rules([*ignore_rules, *reordered]))
        self.config["rules"] = self.rules
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Rules reordered by drag and drop")

    def add_ignore_rule(self, rule: dict[str, Any]) -> None:
        prepared = dict(rule)
        prepared.update({"id": prepared.get("id") or uuid4().hex, "action": "ignore", "target": "", "enabled": True})
        ignore_rules = [item for item in self.rules if item.get("action", "move") == "ignore"]
        move_rules = [item for item in self.rules if item.get("action", "move") != "ignore"]
        self.rules = assign_rule_priorities(normalize_rules([*ignore_rules, prepared, *move_rules]))
        self._persist_config()
        self.rules_changed.emit(self.rules)
        self.logger.info("Ignore rule added: %s", prepared.get("name", prepared["id"]))

    def update_ignore_rule(self, rule_id: str, updates: dict[str, Any]) -> None:
        prepared = dict(updates)
        prepared.update({"action": "ignore", "target": ""})
        self.update_rule(rule_id, prepared)

    def delete_ignore_rule(self, rule_id: str) -> None:
        self.delete_rule(rule_id)

    @Slot()
    def undo_last_batch(self) -> None:
        if not self.undo_stack:
            self.undo_state_changed.emit(False)
            self.activity_emitted.emit(
                {
                    "time": "刚刚",
                    "status": "skipped",
                    "title": "暂无可撤销内容",
                    "detail": "没有找到最近整理记录",
                }
            )
            return

        was_running = self.is_running
        self.is_undoing = True
        try:
            batch = self.undo_stack.pop()
            success_count = 0
            failure_count = 0
            for item in batch.get("items", []):
                filename = str(item.get("filename", "文件"))
                target_path = Path(str(item.get("target_path", "")))
                original_path = Path(str(item.get("original_path", "")))
                source_folder_name = str(item.get("folder_name", ""))
                source_root = str(item.get("source_root", ""))
                self._ignore_restored_path(original_path)
                try:
                    if not target_path.exists():
                        failure_count += 1
                        self.logger.warning("Undo skipped, target missing: %s", target_path)
                        self.activity_emitted.emit(
                            {
                                "time": "刚刚",
                                "status": "error",
                                "title": f"撤销失败：{filename}",
                                "detail": "文件可能已被移动或删除",
                                "source_folder_name": source_folder_name,
                                "source_root": source_root,
                            }
                        )
                        continue

                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    destination = original_path
                    if original_path.exists():
                        action = self._choose_conflict_action(
                            {
                                "filename": filename,
                                "source_path": str(target_path),
                                "target_path": str(original_path),
                                "target_folder": str(original_path.parent),
                            }
                        )
                        if action == "cancel":
                            break
                        if action == "skip":
                            failure_count += 1
                            self.activity_emitted.emit(
                                {
                                    "time": "刚刚",
                                    "status": "error",
                                    "title": f"撤销失败：{filename}",
                                    "detail": "因为原位置存在同名文件，已跳过。",
                                    "source_folder_name": source_folder_name,
                                    "source_root": source_root,
                                }
                            )
                            continue
                        if action == "replace":
                            original_path.unlink()
                        else:
                            destination = self._unique_destination(original_path)
                    self._ignore_restored_path(destination)
                    shutil.move(str(target_path), str(destination))
                    self._ignore_restored_path(destination)
                    success_count += 1
                    self.logger.info("Undo moved %s -> %s", target_path, destination)
                    self.activity_emitted.emit(
                        {
                            "time": "刚刚",
                            "status": "success",
                            "title": f"已撤销：{filename}",
                            "detail": f"已移回 {self._display_path(destination)}",
                            "target_path": str(destination),
                            "target_folder": str(destination.parent),
                            "source_folder_name": source_folder_name,
                            "source_root": source_root,
                        }
                    )
                except Exception:
                    failure_count += 1
                    self.logger.exception("Undo failed: %s", filename)
                    self.activity_emitted.emit(
                        {
                            "time": "刚刚",
                            "status": "error",
                            "title": f"撤销失败：{filename}",
                            "detail": "恢复文件时遇到问题",
                            "source_folder_name": source_folder_name,
                            "source_root": source_root,
                        }
                    )

            self.activity_emitted.emit(
                {
                    "time": "刚刚",
                    "status": "skipped",
                    "title": "撤销完成",
                    "detail": f"成功 {success_count} 个，失败 {failure_count} 个",
                }
            )
            self.undo_state_changed.emit(bool(self.undo_stack))
            self.undo_completed.emit(
                {
                    "was_running": was_running,
                    "success_count": success_count,
                    "failure_count": failure_count,
                }
            )
        finally:
            self.is_undoing = False

    def shutdown(self) -> None:
        self.stop()
        self.worker.stop()
        self.logger.removeHandler(self.qt_log_handler)

    def _ensure_folder_ready(self) -> bool:
        if not self.monitored_folder:
            self.error_occurred.emit("请先选择监控文件夹。")
            self.logger.error("Folder check failed: no active monitored folder")
            return False

        folder = Path(self.monitored_folder)
        if not folder.exists():
            self.error_occurred.emit("当前监控文件夹不存在。")
            self.logger.error("Folder does not exist: %s", folder)
            return False
        if not folder.is_dir():
            self.error_occurred.emit("当前监控路径不是文件夹。")
            self.logger.error("Monitored path is not a folder: %s", folder)
            return False
        if not os.access(folder, os.R_OK | os.W_OK):
            self.error_occurred.emit("当前监控文件夹不可读写。")
            self.logger.error("Folder permission check failed: %s", folder)
            return False
        return True

    def _valid_monitored_folders(self, emit_activity: bool = False) -> list[dict[str, Any]]:
        valid_folders = []
        for folder in self.monitored_folders:
            prepared = dict(folder)
            path_text = str(prepared.get("path", ""))
            display_name = str(prepared.get("display_name") or folder_display_name(path_text))
            path = Path(path_text)
            if path.exists() and path.is_dir() and os.access(path, os.R_OK | os.W_OK):
                prepared["path"] = str(path)
                prepared["display_name"] = display_name
                valid_folders.append(prepared)
                continue

            self.logger.warning("Monitored folder skipped because it is unavailable: %s", path_text)
            if emit_activity:
                self.activity_emitted.emit(
                    {
                        "time": timestamp()[11:16],
                        "status": "skipped",
                        "title": f"文件夹暂时不可用：{display_name}",
                        "detail": "已跳过这个文件夹，其他可用文件夹会继续运行。",
                        "source_folder_name": display_name,
                        "source_root": path_text,
                    }
                )
        return valid_folders

    def _event_payload(self, event: object) -> dict[str, str]:
        if isinstance(event, dict):
            payload = {
                "file_path": str(event.get("file_path", "")),
                "folder_id": str(event.get("folder_id", "")),
                "source_root": str(event.get("source_root", "")),
                "display_name": str(event.get("display_name", "")),
            }
        else:
            active_folder = self.get_active_folder() or {}
            payload = {
                "file_path": str(event or ""),
                "folder_id": str(active_folder.get("id", "")),
                "source_root": str(active_folder.get("path", self.monitored_folder)),
                "display_name": str(active_folder.get("display_name", "")),
            }

        source_root = payload["source_root"]
        if not payload["display_name"]:
            payload["display_name"] = folder_display_name(source_root)
        return payload

    def _persist_config(self) -> None:
        self.monitored_folder = self.get_active_folder_path()
        self.config["monitored_folders"] = self.get_monitored_folders()
        self.config["active_folder_id"] = self.active_folder_id
        self.config["monitored_folder"] = self.monitored_folder
        self.config["rules"] = assign_rule_priorities(self.rules)
        self.storage.save(self.config)

    def _validate_monitored_folder_path(self, path: str, exclude_folder_id: str | None = None) -> str:
        normalized_path = normalize_folder_path(path)
        if not normalized_path:
            raise ValueError("请选择有效的监控文件夹。")

        folder_path = Path(normalized_path)
        if not folder_path.exists() or not folder_path.is_dir():
            raise ValueError("监控文件夹不存在或不是文件夹。")

        candidate_key = folder_compare_key(normalized_path)
        for folder in self.monitored_folders:
            if exclude_folder_id and folder.get("id") == exclude_folder_id:
                continue
            existing_path = str(folder.get("path", ""))
            if not existing_path:
                continue
            if candidate_key == folder_compare_key(existing_path):
                raise ValueError("这个文件夹已经在监控列表中。")
            if is_same_or_nested_folder(normalized_path, existing_path):
                raise ValueError("不能同时监控父文件夹和它的子文件夹。")

        return normalized_path

    def _create_pending_batch(self) -> str:
        batch_id = uuid4().hex
        self.pending_undo_batches[batch_id] = {"timestamp": timestamp(), "items": [], "remaining": 0}
        return batch_id

    def _set_pending_batch_total(self, batch_id: str, total: int) -> None:
        batch = self.pending_undo_batches.get(batch_id)
        if batch is not None:
            batch["remaining"] = total

    @Slot(dict)
    def _record_moved_file(self, move: dict) -> None:
        batch_id = str(move.get("batch_id", ""))
        item = {
            "filename": str(move.get("filename", "")),
            "original_path": str(move.get("original_path", "")),
            "target_path": str(move.get("target_path", "")),
            "folder_id": str(move.get("folder_id", "")),
            "folder_name": str(move.get("folder_name", "")),
            "source_root": str(move.get("source_root", "")),
        }
        batch = self.pending_undo_batches.get(batch_id)
        if batch is not None:
            batch["items"].append(item)

        target_relative = str(move.get("target_relative", Path(item["target_path"]).name))
        if move.get("conflict") and move.get("final_name") and move.get("final_name") != item["filename"]:
            detail = f"目标位置存在同名文件，已保存为 {move.get('final_name')}\n命中规则：{move.get('rule_name') or '默认规则'}"
        else:
            detail = f"已移动到 {target_relative}\n命中规则：{move.get('rule_name') or '默认规则'}"
        self.activity_emitted.emit(
            {
                "time": timestamp()[11:16],
                "status": "success",
                "title": f"已整理：{item['filename']}",
                "detail": detail,
                "target_path": item["target_path"],
                "target_folder": str(Path(item["target_path"]).parent),
                "rule_name": str(move.get("rule_name") or "默认规则"),
                "source_folder_name": item["folder_name"],
                "source_root": item["source_root"],
            }
        )

    @Slot(dict)
    def _record_skipped_file(self, skip: dict) -> None:
        self.activity_emitted.emit(
            {
                "time": timestamp()[11:16],
                "status": "skipped",
                "title": f"未整理：{skip.get('filename', '文件')}",
                "detail": str(skip.get("reason") or "已跳过。"),
                "source_folder_name": str(skip.get("folder_name", "")),
                "source_root": str(skip.get("source_root", "")),
            }
        )

    @Slot(dict)
    def _record_ignored_file(self, ignored: dict) -> None:
        self.activity_emitted.emit(
            {
                "time": timestamp()[11:16],
                "status": "ignored",
                "title": f"已忽略：{ignored.get('filename', '文件')}",
                "detail": f"命中规则：{ignored.get('rule_name') or '忽略规则'}\n文件已保留在原位置。",
                "target_path": str(ignored.get("original_path", "")),
                "target_folder": str(Path(str(ignored.get("original_path", ""))).parent),
                "source_folder_name": str(ignored.get("folder_name", "")),
                "source_root": str(ignored.get("source_root", "")),
            }
        )

    @Slot(str)
    def _finish_batch_job(self, batch_id: str) -> None:
        batch = self.pending_undo_batches.get(batch_id)
        if not batch:
            return
        batch["remaining"] = max(0, int(batch.get("remaining", 0)) - 1)
        if batch["remaining"] > 0:
            return

        finished = self.pending_undo_batches.pop(batch_id, None)
        self.worker.canceled_batches.discard(batch_id)
        if not finished or not finished.get("items"):
            return
        self.undo_stack.append({"timestamp": finished["timestamp"], "items": list(finished["items"])})
        self.undo_stack = self.undo_stack[-10:]
        self.undo_state_changed.emit(True)

    @Slot(str)
    def _remember_log_line(self, line: str) -> None:
        self.recent_logs.append(f"{timestamp()} | {line}" if " | " not in line else line)

    def _unique_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination
        counter = 1
        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _choose_conflict_action(self, conflict: dict) -> str:
        handler = self.conflict_choice_handler
        if callable(handler):
            try:
                return str(handler(dict(conflict)) or "keep")
            except Exception:
                self.logger.exception("Conflict choice handler failed")
        return "keep"

    def _display_path(self, path: Path) -> str:
        for folder in self.monitored_folders:
            root = str(folder.get("path", ""))
            if not root:
                continue
            try:
                return str(path.relative_to(Path(root)))
            except ValueError:
                continue
        try:
            return str(path.relative_to(Path(self.monitored_folder)))
        except ValueError:
            return str(path)

    def _normalize_event_path(self, file_path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(str(file_path)))

    def _covered_extensions(self) -> set[str]:
        covered = set()
        for rule in self.rules:
            if not rule.get("enabled", True) or rule.get("type") != "extension":
                continue
            for extension in rule.get("extensions", []):
                normalized = self._normalize_extension(str(extension))
                if normalized:
                    covered.add(normalized)
        return covered

    def _build_suggestions(self, extension_counts: dict[str, int], covered_extensions: set[str]) -> list[dict[str, Any]]:
        suggestions = []
        grouped_extensions = set()
        for group in SUGGESTION_GROUPS:
            available_extensions = [
                extension
                for extension in group["extensions"]
                if extension in extension_counts and extension not in covered_extensions
            ]
            count = sum(extension_counts[extension] for extension in available_extensions)
            if count >= MIN_SUGGESTION_COUNT:
                suggestions.append(
                    {
                        "name": group["name"],
                        "target": group["target"],
                        "extensions": available_extensions,
                        "count": count,
                    }
                )
                grouped_extensions.update(available_extensions)

        for extension, count in extension_counts.items():
            if extension in grouped_extensions or extension in covered_extensions or count < MIN_SUGGESTION_COUNT:
                continue
            name = self._suggestion_name_for_extensions([extension])
            suggestions.append(
                {
                    "name": name,
                    "target": name.replace(" ", ""),
                    "extensions": [extension],
                    "count": count,
                }
            )

        suggestions.sort(key=lambda item: (-int(item.get("count", 0)), str(item.get("name", ""))))
        return suggestions[:MAX_SUGGESTIONS]

    def _suggestion_name_for_extensions(self, extensions: list[str]) -> str:
        first = (extensions[0] if extensions else ".file").lstrip(".").upper()
        return f"{first} 文件"

    def _normalize_extension(self, extension: str) -> str:
        cleaned = extension.strip().lower()
        if not cleaned:
            return ""
        return cleaned if cleaned.startswith(".") else f".{cleaned}"

    def _cleanup_ignored_paths(self, now: float | None = None) -> None:
        current_time = now or time.time()
        expired = [path for path, until in self.ignore_until.items() if until <= current_time]
        for path in expired:
            self.ignore_until.pop(path, None)

    def _ignore_restored_path(self, file_path: str | Path, seconds: float = 3.0) -> None:
        normalized_path = self._normalize_event_path(file_path)
        self.ignore_until[normalized_path] = time.time() + seconds
        self.logger.info("ignored restored file path: %s", normalized_path)

    def _should_ignore_file_event(self, file_path: str | Path) -> bool:
        if self.is_undoing:
            self.logger.info("skipped watcher event during undo: %s", Path(file_path).name)
            return True
        now = time.time()
        self._cleanup_ignored_paths(now)
        normalized_path = self._normalize_event_path(file_path)
        ignore_until = self.ignore_until.get(normalized_path)
        if ignore_until and ignore_until > now:
            self.logger.info("ignored restored file path event: %s", normalized_path)
            return True
        return False

    def _clear_worker_queue_for_tests(self) -> None:
        self.worker.jobs.join()
