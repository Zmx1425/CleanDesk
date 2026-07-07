import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> logging.Logger:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cleandesk")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        file_handler = RotatingFileHandler(
            logs_dir / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(file_handler)

    return logger


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_hidden_or_temp_file(path: Path) -> bool:
    name = path.name
    temp_suffixes = (".tmp", ".part", ".crdownload", ".download")
    return name.startswith(".") or name.startswith("~") or name.endswith(temp_suffixes)


def safe_folder_part(folder: str) -> Path:
    parts = []
    for part in Path(folder).parts:
        cleaned = re.sub(r'[<>:"|?*]', "_", part).strip()
        if cleaned and cleaned not in {".", ".."}:
            parts.append(cleaned)
    return Path(*parts) if parts else Path("Unsorted")


def resolve_target_folder(monitored_folder: str | Path, configured_target: str | Path) -> Path:
    base = Path(monitored_folder).expanduser().resolve()
    raw_target = str(configured_target or "Unsorted").strip() or "Unsorted"
    target = Path(raw_target).expanduser()
    if target.is_absolute():
        return target.resolve()
    return (base / safe_folder_part(raw_target)).resolve()


def normalize_folder_path(path: str | Path) -> str:
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    try:
        return str(Path(raw_path).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return os.path.abspath(os.path.normpath(os.path.expanduser(raw_path)))


def folder_compare_key(path: str | Path) -> str:
    normalized_path = normalize_folder_path(path)
    if not normalized_path:
        return ""
    return os.path.normcase(os.path.abspath(os.path.normpath(normalized_path)))


def folder_display_name(path: str | Path) -> str:
    normalized_path = normalize_folder_path(path)
    name = Path(normalized_path).name if normalized_path else ""
    return name or "文件夹"


def is_same_or_nested_folder(candidate: str | Path, existing: str | Path) -> bool:
    candidate_key = folder_compare_key(candidate)
    existing_key = folder_compare_key(existing)
    if not candidate_key or not existing_key:
        return False
    if candidate_key == existing_key:
        return True
    try:
        common = os.path.commonpath([candidate_key, existing_key])
    except (ValueError, OSError):
        return False
    return common in {candidate_key, existing_key}
