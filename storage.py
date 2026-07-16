import json
from pathlib import Path
from uuid import uuid4

from rules import DEFAULT_RULES, assign_rule_priorities, normalize_rules, sort_rules
from utils import folder_compare_key, folder_display_name, normalize_folder_path


DEFAULT_SETTINGS = {
    "auto_start_organizing": False,
    "scan_existing_on_start": True,
    "manual_duplicate_policy": "ask",
    "auto_duplicate_policy": "keep_both",
    "recent_activity_limit": 50,
    "close_behavior": "exit",
    "launch_at_login": False,
    "notifications_enabled": True,
    "theme": "light",
}


def normalize_settings(settings: object) -> dict:
    raw = dict(settings) if isinstance(settings, dict) else {}
    normalized = dict(raw)
    for key in ("auto_start_organizing", "scan_existing_on_start", "launch_at_login", "notifications_enabled"):
        value = raw.get(key, DEFAULT_SETTINGS[key])
        normalized[key] = value if isinstance(value, bool) else DEFAULT_SETTINGS[key]

    manual_policy = raw.get("manual_duplicate_policy", DEFAULT_SETTINGS["manual_duplicate_policy"])
    normalized["manual_duplicate_policy"] = manual_policy if manual_policy in {"ask", "keep_both", "skip"} else "ask"

    auto_policy = raw.get("auto_duplicate_policy", DEFAULT_SETTINGS["auto_duplicate_policy"])
    normalized["auto_duplicate_policy"] = auto_policy if auto_policy in {"keep_both", "skip"} else "keep_both"

    activity_limit = raw.get("recent_activity_limit", DEFAULT_SETTINGS["recent_activity_limit"])
    normalized["recent_activity_limit"] = activity_limit if type(activity_limit) is int and activity_limit in {50, 100, 200} else 50

    close_behavior = raw.get("close_behavior", DEFAULT_SETTINGS["close_behavior"])
    normalized["close_behavior"] = close_behavior if close_behavior in {"exit", "minimize_to_tray"} else "exit"

    theme = raw.get("theme", DEFAULT_SETTINGS["theme"])
    normalized["theme"] = theme if isinstance(theme, str) and theme in {"light", "dark"} else "light"
    return normalized


class ConfigStorage:
    def __init__(self, config_path: str | Path = "config.json") -> None:
        self.config_path = Path(config_path)

    def load(self) -> dict:
        if not self.config_path.exists():
            return self._default_config()

        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return self._default_config()

        config = self._default_config()
        config.update(data)
        config["rules"] = assign_rule_priorities(sort_rules(normalize_rules(config.get("rules", []))))
        config["settings"] = normalize_settings(config.get("settings"))
        self._normalize_folder_config(config)
        return config

    def save(self, config: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)

    def _default_config(self) -> dict:
        config = {
            "monitored_folders": [],
            "active_folder_id": "",
            "monitored_folder": "",
            "welcome_shown": False,
            "rules": assign_rule_priorities(sort_rules(normalize_rules(DEFAULT_RULES))),
            "settings": dict(DEFAULT_SETTINGS),
        }
        self._normalize_folder_config(config)
        return config

    def _normalize_folder_config(self, config: dict) -> None:
        folders = []
        seen_paths = set()

        raw_folders = config.get("monitored_folders")
        if isinstance(raw_folders, list):
            for raw_folder in raw_folders:
                if not isinstance(raw_folder, dict):
                    continue
                path = normalize_folder_path(raw_folder.get("path", ""))
                if not path:
                    continue
                compare_key = folder_compare_key(path)
                if compare_key in seen_paths:
                    continue
                seen_paths.add(compare_key)
                folder = dict(raw_folder)
                folder["id"] = str(folder.get("id") or uuid4().hex)
                folder["path"] = path
                folder["display_name"] = str(folder.get("display_name") or folder_display_name(path))
                folders.append(folder)

        if not folders:
            legacy_folder = normalize_folder_path(config.get("monitored_folder", ""))
            if legacy_folder:
                folders.append(
                    {
                        "id": uuid4().hex,
                        "path": legacy_folder,
                        "display_name": folder_display_name(legacy_folder),
                    }
                )

        active_folder_id = str(config.get("active_folder_id") or "")
        if active_folder_id not in {folder["id"] for folder in folders}:
            active_folder_id = folders[0]["id"] if folders else ""

        active_folder = next((folder for folder in folders if folder["id"] == active_folder_id), None)
        config["monitored_folders"] = folders
        config["active_folder_id"] = active_folder_id
        config["monitored_folder"] = active_folder["path"] if active_folder else ""
