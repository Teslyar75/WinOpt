"""Ярлык на рабочем столе."""

from __future__ import annotations

from winopt.winutil import run_powershell

import os
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def icon_path() -> Path:
    return project_root() / "assets" / "winopt.ico"


def pythonw_path() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def desktop_dir() -> Path:
    # Реальный рабочий стол Windows (в т.ч. OneDrive «Рабочий стол»), а не C:\Users\...\Desktop
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
        known = Path(buf.value)
        if known.exists():
            return known
    except Exception:
        pass
    override = os.environ.get("USERPROFILE")
    if override:
        desktop = Path(override) / "Desktop"
        if desktop.exists():
            return desktop
    return Path.home() / "Desktop"


def shortcut_path() -> Path:
    return desktop_dir() / "Оптимизация Windows.lnk"


def install_desktop_shortcut() -> Path:
    target = pythonw_path()
    workdir = project_root()
    icon = icon_path()
    dest = shortcut_path()
    dest.parent.mkdir(parents=True, exist_ok=True)

    script = r"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($env:WINOPT_LNK)
$sc.TargetPath = $env:WINOPT_TARGET
$sc.Arguments = '-m winopt'
$sc.WorkingDirectory = $env:WINOPT_WD
$sc.WindowStyle = 1
$sc.Description = 'Диагностика Windows и безопасное отключение автозагрузки'
if (Test-Path -LiteralPath $env:WINOPT_ICON) {
    $sc.IconLocation = $env:WINOPT_ICON
}
$sc.Save()
"""
    completed = run_powershell(script, {
            "WINOPT_LNK": str(dest),
            "WINOPT_TARGET": str(target),
            "WINOPT_WD": str(workdir),
            "WINOPT_ICON": str(icon),
        }, timeout=30)
    if completed.returncode != 0 or not dest.exists():
        err = (completed.stderr or completed.stdout or "не удалось создать ярлык").strip()
        raise RuntimeError(err)
    return dest
