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
from utils import configure_logging, is_hidden_or_temp_file, timestamp
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
    batch_job_finished = Signal(str)
    conflict_requested = Signal(dict)
    conflict_hint_requested = Signal(str)

    def __init__(self, engine: FileOrganizerEngine, logger: logging.Logger) -> None:
        super().__init__()
        self.engine = engine
        self.logger = logger
        self.jobs: queue.Queue[tuple[str, str, list[dict], str, str]] = queue.Queue()
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
        self.jobs.put((normalized_path, base_folder, [dict(rule) for rule in rules], batch_id, mode))
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
                file_path, base_folder, rules, batch_id, mode = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._process_with_retry(file_path, base_folder, rules, batch_id, mode)
            finally:
                if batch_id:
                    self.batch_job_finished.emit(batch_id)
                self.jobs.task_done()

    def _process_with_retry(self, file_path: str, base_folder: str, rules: list[dict], batch_id: str, mode: str) -> None:
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
            if is_hidden_or_temp_file(path):
                self.logger.info("Queued file skipped because it is temporary or hidden: %s", path.name)
                return
            matched_rule = find_matching_rule(path, rules)
            if not matched_rule:
                self.engine.process_file(str(path), base_folder, rules)
                return
            status = self._process_and_emit_move(path, base_folder, rules, batch_id, matched_rule, mode)
            if status in {"moved", "conflict_skipped", "canceled", "no_match"}:
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
    ) -> str:
        original_path = path.resolve()
        resolver = None
        if mode == "manual":
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
                }
            )
            return status
        if status != "moved":
            return status

        target_path = Path(str(result.get("destination", ""))).resolve()
        target_relative = str(result.get("target_display") or target_path.name)
        conflict = bool(result.get("conflict"))
        final_name = str(result.get("final_name") or target_path.name)
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
        self.monitored_folder = self.config.get("monitored_folder") or str(Path.home() / "Downloads")
        self.is_running = False
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
        self.worker.batch_job_finished.connect(self._finish_batch_job)
        self.worker.conflict_requested.connect(self.conflict_requested)
        self.worker.conflict_hint_requested.connect(self.conflict_hint_requested)
        self.worker.start()
        self.watcher = FolderWatcher(self.logger)
        self.watcher.file_detected.connect(self.process_file)
        self.watcher.error_occurred.connect(self.error_occurred)

        self._persist_config()
        self.logger.info("CleanDesk ready")

    def set_monitored_folder(self, folder: str) -> None:
        folder_path = Path(folder).expanduser()
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error_occurred.emit(f"Unable to use this folder: {exc}")
            self.logger.exception("Failed to set monitored folder")
            return

        was_running = self.is_running
        if was_running:
            self.stop()

        self.monitored_folder = str(folder_path)
        self.config["monitored_folder"] = self.monitored_folder
        self._persist_config()
        self.folder_changed.emit(self.monitored_folder)
        self.logger.info("Monitored folder changed to %s", self.monitored_folder)

        if was_running:
            self.start()

    @Slot()
    def start(self) -> None:
        if self.is_running:
            return
        if not self._ensure_folder_ready():
            return
        self.logger.info("正在启动监听")
        batch_id = self._create_pending_batch()
        queued = self._queue_existing_files(batch_id)
        if queued:
            self.logger.info("启动前扫描：发现 %s 个已有文件", queued)
        else:
            self.pending_undo_batches.pop(batch_id, None)
            self.logger.info("启动前扫描：未发现待处理文件")
        try:
            self.watcher.start(self.monitored_folder)
        except RuntimeError as exc:
            self.error_occurred.emit(str(exc))
            self.logger.exception("Unable to start watcher")
            return
        self.is_running = True
        self.status_changed.emit(True)
        self.logger.info("已开始监听")

    @Slot()
    def stop(self) -> None:
        if not self.is_running:
            return
        self.watcher.stop()
        self.is_running = False
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

    @Slot(str)
    def process_file(self, file_path: str) -> None:
        if not file_path:
            return
        if self._should_ignore_file_event(file_path):
            return
        batch_id = self._create_pending_batch()
        self._set_pending_batch_total(batch_id, 1)
        if self.worker.enqueue(file_path, self.monitored_folder, self.rules, batch_id):
            return
        else:
            self.pending_undo_batches.pop(batch_id, None)

    @Slot(str, str)
    def resolve_name_conflict(self, request_id: str, action: str) -> None:
        self.worker.resolve_conflict(request_id, action)

    def _queue_existing_files(self, batch_id: str, mode: str = "manual") -> int:
        queued = 0
        files = [
            item
            for item in Path(self.monitored_folder).iterdir()
            if item.is_file() and not self._should_ignore_file_event(str(item))
        ]
        self._set_pending_batch_total(batch_id, len(files))
        for item in files:
            if self.worker.enqueue(str(item), self.monitored_folder, self.rules, batch_id, mode, force=True):
                queued += 1
            else:
                self._finish_batch_job(batch_id)
        return queued

    def add_rule(self, rule: dict[str, Any]) -> None:
        prepared_rule = dict(rule)
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
        folder = Path(self.monitored_folder)
        if not folder.exists():
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.error_occurred.emit(f"Unable to create monitored folder: {exc}")
                self.logger.exception("Failed to create monitored folder")
                return False
        if not os.access(folder, os.R_OK | os.W_OK):
            self.error_occurred.emit("The selected folder is not readable and writable.")
            self.logger.error("Folder permission check failed: %s", folder)
            return False
        return True

    def _persist_config(self) -> None:
        self.config["monitored_folder"] = self.monitored_folder
        self.config["rules"] = assign_rule_priorities(self.rules)
        self.storage.save(self.config)

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
