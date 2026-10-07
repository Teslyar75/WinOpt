"""Общие вспомогательные функции для работы с Windows.

Здесь собрано то, что раньше повторялось в каждом модуле:
запуск PowerShell (теперь без мигающего чёрного окна), проверка прав
администратора, открытие папок в Проводнике, папка данных программы.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# Флаг Windows: запускать дочерний процесс без консольного окна.
# Без него при запуске через pythonw.exe каждый вызов PowerShell
# на долю секунды показывал чёрное окно.
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def run_powershell(
    script: str,
    env_extra: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Выполнить скрипт PowerShell и вернуть результат (stdout/stderr в UTF-8)."""
    prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            prefix + script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env_extra or {})},
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def run_quiet(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Запустить консольную утилиту (powercfg и т.п.) без окна."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Перезапустить программу с правами администратора (появится запрос UAC)."""
    if not IS_WINDOWS:
        return False
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    target = str(pythonw if pythonw.exists() else exe)
    workdir = str(Path(__file__).resolve().parent.parent)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, "-m winopt", workdir, 1)
    return rc > 32


def open_path(path: str | Path) -> None:
    """Открыть файл/папку/ссылку стандартной программой Windows."""
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_explorer(path: str | Path) -> None:
    """Открыть Проводник и выделить файл."""
    if IS_WINDOWS:
        subprocess.Popen(["explorer.exe", "/select,", str(path)])
    else:
        open_path(Path(path).parent)


def launch(command: str | list[str]) -> None:
    """Запустить системный инструмент (cleanmgr, taskmgr…) без ожидания."""
    if IS_WINDOWS and isinstance(command, str) and command.startswith("ms-settings:"):
        os.startfile(command)  # type: ignore[attr-defined]
        return
    subprocess.Popen(command, shell=isinstance(command, str))


def data_dir() -> Path:
    """Папка данных программы: %LOCALAPPDATA%\\WinOpt."""
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinOpt"
    root.mkdir(parents=True, exist_ok=True)
    return root


def reports_dir() -> Path:
    path = data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_size(size_bytes: float) -> str:
    size = float(size_bytes or 0)
    if size < 1024:
        return f"{int(size)} Б"
    if size < 1024**2:
        return f"{size / 1024:.1f} КБ"
    if size < 1024**3:
        return f"{size / (1024**2):.1f} МБ"
    if size < 1024**4:
        return f"{size / (1024**3):.2f} ГБ"
    return f"{size / (1024**4):.2f} ТБ"


def format_rate(bytes_per_sec: float) -> str:
    return format_size(bytes_per_sec) + "/с"


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


# --- запуск внешних программ с ожиданием (деинсталляторы, повышение прав) ----------

ERROR_CANCELLED = 1223  # пользователь отказался в окне UAC


class LaunchError(RuntimeError):
    """Не удалось запустить процесс (в т.ч. отказ в окне UAC)."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


class ProcessHandle:
    """Дескриптор процесса, запущенного через ShellExecuteEx (можно ждать завершения)."""

    def __init__(self, handle: int | None, pid: int | None) -> None:
        self.handle = handle
        self.pid = pid

    def wait(self, timeout_ms: int) -> bool:
        """True — процесс завершился (или ждать нечего)."""
        if not self.handle:
            return True
        WAIT_TIMEOUT = 0x102
        return ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(self.handle), int(timeout_ms)) != WAIT_TIMEOUT

    def exit_code(self) -> int | None:
        if not self.handle:
            return None
        code = ctypes.c_ulong(0)
        if ctypes.windll.kernel32.GetExitCodeProcess(ctypes.c_void_p(self.handle), ctypes.byref(code)):
            return int(code.value)
        return None

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def shell_execute(file: str, params: str = "", elevate: bool = False, workdir: str | None = None, show: int = 1) -> ProcessHandle:
    """Запустить программу через ShellExecuteEx и вернуть дескриптор для ожидания.

    elevate=True — с запросом прав администратора (окно UAC). Программы, которым
    права нужны по манифесту, Windows и так запустит с запросом UAC.
    """
    if not IS_WINDOWS:
        raise LaunchError("Доступно только в Windows")
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NOASYNC = 0x00000100
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas" if elevate else "open"
    info.lpFile = file
    info.lpParameters = params or None
    info.lpDirectory = workdir
    info.nShow = show
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.GetLastError()
        if code == ERROR_CANCELLED:
            raise LaunchError("Запуск отменён в окне контроля учётных записей (UAC).", code)
        raise LaunchError(f"Не удалось запустить {file}: {ctypes.FormatError(code).strip()} (код {code})", code)
    handle = info.hProcess or None
    pid = ctypes.windll.kernel32.GetProcessId(handle) if handle else None
    return ProcessHandle(handle, pid or None)


def split_command(command: str) -> tuple[str, str]:
    """Разделить командную строку деинсталлятора на программу и аргументы.

    Поддерживает «"C:\\путь\\uninst.exe" /S», «MsiExec.exe /X{...}» и пути
    с пробелами без кавычек (C:\\Program Files\\X\\unins000.exe /SILENT).
    """
    command = command.strip()
    if not command:
        return "", ""
    if command.startswith('"'):
        end = command.find('"', 1)
        if end == -1:
            return command.strip('"'), ""
        return command[1:end], command[end + 1:].strip()
    parts = command.split(" ")
    # путь без кавычек: ищем самый длинный существующий префикс
    for n in range(len(parts), 0, -1):
        candidate = " ".join(parts[:n])
        if os.path.isfile(candidate) or (not candidate.lower().endswith(".exe") and os.path.isfile(candidate + ".exe")):
            return candidate, " ".join(parts[n:]).strip()
    import re

    match = re.match(r"(?i)^(.+?\.exe)(?:\s+(.*))?$", command)
    if match:
        return match.group(1), (match.group(2) or "").strip()
    return parts[0], " ".join(parts[1:]).strip()
