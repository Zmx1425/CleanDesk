from collections.abc import Callable
from typing import Any

from theme.dark import DARK_THEME
from theme.light import LIGHT_THEME


THEMES = {
    "light": LIGHT_THEME,
    "dark": DARK_THEME,
}


def normalize_theme_name(theme_name: object) -> str:
    value = str(theme_name or "").strip().lower()
    return value if value in THEMES else "light"


class ThemeManager:
    def __init__(
        self,
        theme_name: str = "light",
        save_callback: Callable[[dict[str, Any]], object] | None = None,
    ) -> None:
        self._theme_name = normalize_theme_name(theme_name)
        self._save_callback = save_callback

    @property
    def current_theme(self) -> str:
        return self._theme_name

    @property
    def palette(self) -> dict[str, Any]:
        return dict(THEMES[self._theme_name])

    def get_current_theme(self) -> dict[str, Any]:
        return self.palette

    def set_current_theme(self, theme_name: str, persist: bool = False) -> str:
        self._theme_name = normalize_theme_name(theme_name)
        if persist:
            self.save_current_theme()
        return self._theme_name

    def save_current_theme(self) -> None:
        if self._save_callback is not None:
            self._save_callback({"theme": self._theme_name})

    def build_style_sheet(self, light_style_sheet: str) -> str:
        if self._theme_name == "light":
            return light_style_sheet

        themed_style_sheet = light_style_sheet
        dark_palette = THEMES[self._theme_name]
        protected_tokens = {}
        for key, light_value in LIGHT_THEME.items():
            dark_value = dark_palette.get(key)
            if not isinstance(light_value, str) or not isinstance(dark_value, str):
                continue
            marker = f"__CLEANDESK_THEME_{key.upper()}__"
            annotated_value = f"{light_value}; /* theme:{key} */"
            if annotated_value in themed_style_sheet:
                themed_style_sheet = themed_style_sheet.replace(annotated_value, f"{marker};")
                protected_tokens[marker] = dark_value

        replacements: dict[str, tuple[str, str]] = {}
        for key, light_value in LIGHT_THEME.items():
            dark_value = dark_palette.get(key)
            if isinstance(light_value, str) and isinstance(dark_value, str):
                replacements.setdefault(
                    light_value,
                    (f"__CLEANDESK_THEME_COLOR_{len(replacements)}__", dark_value),
                )

        for light_value, (marker, _) in replacements.items():
            themed_style_sheet = themed_style_sheet.replace(light_value, marker)
        for marker, dark_value in replacements.values():
            themed_style_sheet = themed_style_sheet.replace(marker, dark_value)
        for marker, dark_value in protected_tokens.items():
            themed_style_sheet = themed_style_sheet.replace(marker, dark_value)
        return themed_style_sheet

    def apply_theme(self, widget: Any, light_style_sheet: str) -> None:
        widget.setStyleSheet(self.build_style_sheet(light_style_sheet))
