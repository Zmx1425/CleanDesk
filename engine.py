import logging
import shutil
import time
from pathlib import Path
from typing import Callable

from rules import find_matching_rule
from utils import is_hidden_or_temp_file, resolve_target_folder


class FileOrganizerEngine:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def scan_folder(self, folder: str, rules: list[dict]) -> int:
        base = Path(folder)
        if not base.exists():
            self.logger.warning("Scan skipped, folder does not exist: %s", base)
            return 0

        processed = 0
        for item in base.iterdir():
            if item.is_file() and self.process_file(str(item), str(base), rules):
                processed += 1
        return processed

    def process_file(self, file_path: str, base_folder: str, rules: list[dict]) -> bool:
        return self.process_file_result(file_path, base_folder, rules).get("status") == "moved"

    def process_file_result(
        self,
        file_path: str,
        base_folder: str,
        rules: list[dict],
        conflict_resolver: Callable[[dict], str] | None = None,
    ) -> dict:
        source = Path(file_path)
        base = Path(base_folder)
        result = {
            "status": "skipped",
            "moved": False,
            "source_name": source.name,
            "destination": "",
            "requested_destination": "",
            "conflict": False,
            "action": "",
        }

        if not source.exists() or not source.is_file():
            return result
        if source.parent != base:
            return result
        rule = find_matching_rule(source, rules)
        if rule and rule.get("action", "move") == "ignore":
            self.logger.info("Ignored by rule %s: %s", rule.get("name", ""), source.name)
            result.update({"status": "ignored", "rule": rule})
            return result
        if is_hidden_or_temp_file(source):
            self.logger.info("Skipped temporary or hidden file: %s", source.name)
            return result

        self._wait_until_stable(source)
        if not rule:
            self.logger.info("No rule matched: %s", source.name)
            result["status"] = "no_match"
            return result

        target_folder = resolve_target_folder(base, rule.get("target", "Unsorted"))
        target_folder.mkdir(parents=True, exist_ok=True)
        requested_destination = target_folder / source.name
        destination = requested_destination

        if requested_destination.exists():
            result["conflict"] = True
            result["requested_destination"] = str(requested_destination)
            action = "keep"
            if conflict_resolver:
                action = conflict_resolver(
                    {
                        "filename": source.name,
                        "source_path": str(source),
                        "target_path": str(requested_destination),
                        "target_folder": str(target_folder),
                    }
                )
            result["action"] = action
            if action == "cancel":
                self.logger.info("Move canceled due to name conflict: %s", source.name)
                result["status"] = "canceled"
                return result
            if action == "skip":
                self.logger.info("Move skipped due to name conflict: %s", source.name)
                result["status"] = "conflict_skipped"
                return result
            if action == "replace":
                try:
                    requested_destination.unlink()
                except OSError:
                    self.logger.exception("Failed to replace existing file: %s", requested_destination)
                    result["status"] = "failed"
                    return result
            else:
                destination = self._unique_destination(requested_destination)

        try:
            shutil.move(str(source), str(destination))
        except OSError:
            self.logger.exception("Failed to move file: %s", source)
            result["status"] = "failed"
            return result

        try:
            displayed_destination = destination.relative_to(base)
        except ValueError:
            displayed_destination = destination
        self.logger.info("Moved %s -> %s", source.name, displayed_destination)
        result.update(
            {
                "status": "moved",
                "moved": True,
                "destination": str(destination),
                "requested_destination": str(requested_destination),
                "target_display": str(displayed_destination),
                "final_name": destination.name,
            }
        )
        return result

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

    def _wait_until_stable(self, path: Path, attempts: int = 6, delay: float = 0.35) -> None:
        last_size = -1
        for _ in range(attempts):
            try:
                current_size = path.stat().st_size
            except OSError:
                return
            if current_size == last_size:
                return
            last_size = current_size
            time.sleep(delay)
