"""Статус и быстрая проверка Защитника Windows."""

from __future__ import annotations

from winopt.winutil import run_powershell

import json
from dataclasses import dataclass

_STATUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$s = Get-MpComputerStatus
[pscustomobject]@{
    AntivirusEnabled = [bool]$s.AntivirusEnabled
    RealTimeProtectionEnabled = [bool]$s.RealTimeProtectionEnabled
    AMServiceEnabled = [bool]$s.AMServiceEnabled
    QuickScanAge = [int]$s.QuickScanAge
    FullScanAge = [int]$s.FullScanAge
    ComputerState = [string]$s.ComputerState
} | ConvertTo-Json -Compress
"""

_SCAN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Start-MpScan -ScanType QuickScan
'started'
"""


@dataclass(frozen=True)
class DefenderStatus:
    antivirus_enabled: bool
    realtime_enabled: bool
    service_enabled: bool
    quick_scan_age_hours: int
    full_scan_age_hours: int
    computer_state: str

    @property
    def ok(self) -> bool:
        return self.antivirus_enabled and self.realtime_enabled and self.service_enabled

    @property
    def summary(self) -> str:
        if self.ok:
            return "Защитник Windows включён"
        parts = []
        if not self.service_enabled:
            parts.append("служба выключена")
        if not self.antivirus_enabled:
            parts.append("антивирус выключен")
        if not self.realtime_enabled:
            parts.append("защита в реальном времени выключена")
        return "Защитник Windows: " + ", ".join(parts)


def get_defender_status() -> DefenderStatus:
    completed = run_powershell(_STATUS_SCRIPT, None, timeout=30)
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "не удалось прочитать статус").strip()
        raise RuntimeError(err)
    data = json.loads(completed.stdout.strip())
    return DefenderStatus(
        antivirus_enabled=bool(data.get("AntivirusEnabled")),
        realtime_enabled=bool(data.get("RealTimeProtectionEnabled")),
        service_enabled=bool(data.get("AMServiceEnabled")),
        quick_scan_age_hours=int(data.get("QuickScanAge") or 0),
        full_scan_age_hours=int(data.get("FullScanAge") or 0),
        computer_state=str(data.get("ComputerState") or ""),
    )


def start_quick_scan() -> None:
    """Запустить быструю проверку Защитником в фоне.

    Раньше программа ждала окончания Start-MpScan 30 секунд и падала по таймауту,
    хотя проверка идёт несколько минут. Теперь проверка запускается отдельным
    фоновым процессом, а результат виден в «Безопасность Windows».
    """
    import subprocess

    from winopt.winutil import CREATE_NO_WINDOW

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _SCAN_SCRIPT,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def open_windows_security() -> None:
    import os

    os.startfile("windowsdefender:")  # type: ignore[attr-defined]


def format_defender(status: DefenderStatus) -> str:
    lines = [
        status.summary,
        f"Состояние: {status.computer_state or '—'}",
        f"Последняя быстрая проверка: {_age_text(status.quick_scan_age_hours)}",
        f"Последняя полная проверка: {_age_text(status.full_scan_age_hours)}",
    ]
    return "\n".join(lines)


def _age_text(hours: int) -> str:
    if hours <= 0:
        return "недавно или данных нет"
    if hours < 24:
        return f"{hours} ч. назад"
    days = hours // 24
    return f"{days} дн. назад"
