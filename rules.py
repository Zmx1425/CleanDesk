from pathlib import Path
from uuid import uuid4


DEFAULT_RULES = [
    {
        "id": "name_invoice",
        "name": "Invoice files",
        "type": "name_contains",
        "keywords": ["发票", "invoice"],
        "target": "发票",
        "enabled": True,
        "priority": 10,
    },
    {
        "id": "name_course",
        "name": "Course files",
        "type": "name_contains",
        "keywords": ["课程"],
        "target": "课程资料",
        "enabled": True,
        "priority": 20,
    },
    {
        "id": "images",
        "name": "Images",
        "type": "extension",
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".svg"],
        "target": "图片",
        "enabled": True,
        "priority": 100,
    },
    {
        "id": "pdf",
        "name": "PDF",
        "type": "extension",
        "extensions": [".pdf"],
        "target": "PDF文档",
        "enabled": True,
        "priority": 110,
    },
    {
        "id": "videos",
        "name": "Videos",
        "type": "extension",
        "extensions": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"],
        "target": "视频",
        "enabled": True,
        "priority": 120,
    },
    {
        "id": "music",
        "name": "Audio",
        "type": "extension",
        "extensions": [".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".wma"],
        "target": "音频",
        "enabled": True,
        "priority": 130,
    },
]


def sort_rules(rules: list[dict]) -> list[dict]:
    return list(rules)


def assign_rule_priorities(rules: list[dict]) -> list[dict]:
    ordered_rules = []
    for index, rule in enumerate(rules):
        prepared = dict(rule)
        prepared["priority"] = (index + 1) * 10
        ordered_rules.append(prepared)
    return ordered_rules


def normalize_rules(rules: list[dict]) -> list[dict]:
    normalized = []
    for rule in rules:
        prepared = dict(rule)
        prepared["id"] = prepared.get("id") or uuid4().hex
        prepared["name"] = str(prepared.get("name") or "Untitled Rule")
        prepared["type"] = str(prepared.get("type") or "")
        prepared["action"] = "ignore" if prepared.get("action") == "ignore" else "move"
        prepared["target"] = "" if prepared["action"] == "ignore" else str(prepared.get("target") or "Unsorted")
        prepared["enabled"] = bool(prepared.get("enabled", True))
        prepared["priority"] = int(prepared.get("priority", 100))
        if prepared["type"] == "extension":
            prepared["extensions"] = [normalize_extension(value) for value in prepared.get("extensions", []) if value]
        if prepared["type"] == "name_contains":
            prepared["keywords"] = [str(value) for value in prepared.get("keywords", []) if str(value).strip()]
            if prepared.get("id") == "name_invoice" or prepared.get("name") == "Invoice files":
                for keyword in ["发票", "invoice"]:
                    if keyword not in prepared["keywords"]:
                        prepared["keywords"].append(keyword)
            if prepared.get("id") == "name_course" or prepared.get("name") == "Course files":
                if "课程" not in prepared["keywords"]:
                    prepared["keywords"].append("课程")
        normalized.append(prepared)
    return normalized


def normalize_extension(value: str) -> str:
    extension = str(value).strip().lower()
    if not extension:
        return extension
    if not extension.startswith("."):
        extension = f".{extension}"
    return extension


def find_matching_rule(path: Path, rules: list[dict]) -> dict | None:
    ordered_rules = [rule for rule in rules if rule.get("action", "move") == "ignore"]
    ordered_rules.extend(rule for rule in rules if rule.get("action", "move") != "ignore")
    for rule in ordered_rules:
        if not rule.get("enabled", True):
            continue
        if _matches(path, rule):
            return rule
    return None


def display_rule_name(rule: dict | None) -> str:
    if not rule:
        return "默认规则"
    name = str(rule.get("name", "")).strip()
    known_names = {
        "Invoice files": "发票文件",
        "Course files": "课程资料",
        "Images": "图片",
        "PDF": "PDF 文档",
        "Audio": "音频",
        "Videos": "视频",
    }
    if name in known_names:
        return known_names[name]
    if name and name != "Untitled Rule":
        return name
    if rule.get("type") == "extension":
        extensions = [str(value).strip().lstrip(".") for value in rule.get("extensions", []) if str(value).strip()]
        if extensions == ["pdf"]:
            return "PDF 文档"
        if extensions:
            return f"{extensions[0].upper()} 文件"
    if rule.get("type") == "name_contains":
        keywords = [str(value).strip() for value in rule.get("keywords", []) if str(value).strip()]
        if keywords:
            return f"{keywords[0]}文件"
    return "默认规则"


def _matches(path: Path, rule: dict) -> bool:
    rule_type = rule.get("type")
    if rule_type == "extension":
        extensions = {normalize_extension(value) for value in rule.get("extensions", [])}
        return path.suffix.lower() in extensions
    if rule_type == "name_contains":
        lowered_name = path.name.lower()
        return any(str(keyword).lower() in lowered_name for keyword in rule.get("keywords", []))
    return False
