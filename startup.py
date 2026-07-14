import os
import sys
from pathlib import Path
from typing import Protocol


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CleanDesk"
STARTUP_ARGUMENT = "--startup"


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


def _require_file(path: Path, message: str) -> Path:
    if not path.is_file():
        raise StartupError(message)
    return path


def build_launch_command(
    *,
    executable: str | Path | None = None,
    script_path: str | Path | None = None,
    frozen: bool | None = None,
) -> str:
    executable_path = Path(executable or sys.executable).resolve()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        _require_file(executable_path, "未找到 CleanDesk 可执行文件，无法启用开机启动。")
        return f"{_quoted(executable_path)} {STARTUP_ARGUMENT}"

    main_script = Path(script_path or (Path(__file__).resolve().parent / "main.py")).resolve()
    pythonw_path = executable_path if executable_path.name.casefold() == "pythonw.exe" else executable_path.with_name("pythonw.exe")
    _require_file(pythonw_path, "未找到与当前 Python 对应的 pythonw.exe，无法启用开机启动。")
    _require_file(main_script, "未找到 CleanDesk 启动文件 main.py，无法启用开机启动。")
    return f"{_quoted(pythonw_path)} {_quoted(main_script)} {STARTUP_ARGUMENT}"


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

    try:
        current_command = expected_command or build_launch_command()
    except StartupError:
        return False
    return os.path.normcase(stored_command.strip()).casefold() == os.path.normcase(current_command).casefold()


def has_launch_at_login_entry(backend: RegistryBackend | None = None) -> bool:
    registry = backend or WindowsRegistryBackend()
    try:
        return bool(registry.read_value(VALUE_NAME))
    except StartupError:
        return False


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
