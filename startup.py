import os
import sys
from pathlib import Path
from typing import Protocol


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CleanDesk"


class StartupError(RuntimeError):
    pass


class RegistryBackend(Protocol):
    def read_value(self, name: str) -> str | None: ...

    def write_value(self, name: str, value: str) -> None: ...

    def delete_value(self, name: str) -> None: ...


class WindowsRegistryBackend:
    def _winreg(self):
        if sys.platform != "win32":
            raise StartupError("当前系统不支持 Windows 开机启动设置。")
        import winreg

        return winreg

    def read_value(self, name: str) -> str | None:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StartupError("无法读取 Windows 开机启动设置。") from exc

    def write_value(self, name: str, value: str) -> None:
        winreg = self._winreg()
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except OSError as exc:
            raise StartupError("无法启用 Windows 开机启动，请检查当前用户权限后重试。") from exc

    def delete_value(self, name: str) -> None:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StartupError("无法关闭 Windows 开机启动，请检查当前用户权限后重试。") from exc


def _quoted(path: Path) -> str:
    return f'"{path}"'


def build_launch_command(
    *,
    executable: str | Path | None = None,
    script_path: str | Path | None = None,
    frozen: bool | None = None,
) -> str:
    executable_path = Path(executable or sys.executable).resolve()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return _quoted(executable_path)

    main_script = Path(script_path or (Path(__file__).resolve().parent / "main.py")).resolve()
    return f"{_quoted(executable_path)} {_quoted(main_script)}"


def is_launch_at_login_enabled(
    backend: RegistryBackend | None = None,
    *,
    expected_command: str | None = None,
) -> bool:
    registry = backend or WindowsRegistryBackend()
    try:
        stored_command = registry.read_value(VALUE_NAME)
    except StartupError:
        return False
    if not stored_command:
        return False

    current_command = expected_command or build_launch_command()
    return os.path.normcase(stored_command.strip()).casefold() == os.path.normcase(current_command).casefold()


def set_launch_at_login_enabled(
    enabled: bool,
    backend: RegistryBackend | None = None,
    *,
    command: str | None = None,
) -> None:
    registry = backend or WindowsRegistryBackend()
    if enabled:
        registry.write_value(VALUE_NAME, command or build_launch_command())
    else:
        registry.delete_value(VALUE_NAME)
