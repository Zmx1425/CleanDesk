import json
from pathlib import Path

from rules import DEFAULT_RULES, assign_rule_priorities, normalize_rules, sort_rules


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
        return config

    def save(self, config: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)

    def _default_config(self) -> dict:
        return {
            "monitored_folder": str(Path.home() / "Downloads"),
            "welcome_shown": False,
            "rules": assign_rule_priorities(sort_rules(normalize_rules(DEFAULT_RULES))),
        }
