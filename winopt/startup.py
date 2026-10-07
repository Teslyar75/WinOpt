"""Автозагрузка: Run-ключи, папка Startup, задачи планировщика."""

from __future__ import annotations

from winopt.winutil import run_powershell

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$items = @()

function Add-Item($kind, $name, $command, $location) {
    $script:items += [pscustomobject]@{
        Kind = $kind
        Name = $name
        Command = $command
        Location = $location
    }
}

try {
    Get-CimInstance Win32_StartupCommand | ForEach-Object {
        Add-Item 'startup_command' $_.Name $_.Command $_.Location
    }
} catch {}

$runKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
)
foreach ($key in $runKeys) {
    if (Test-Path $key) {
        Get-ItemProperty $key | ForEach-Object {
            $_.PSObject.Properties | Where-Object {
                $_.Name -notmatch '^PS' -and $_.Name -ne '(default)'
            } | ForEach-Object {
                Add-Item 'registry' $_.Name ([string]$_.Value) $key
            }
        }
    }
}

$startupDirs = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"
)
foreach ($dir in $startupDirs) {
    if (Test-Path -LiteralPath $dir) {
        Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {
            Add-Item 'startup_folder' $_.Name $_.FullName $dir
        }
    }
}

try {
    Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object {
        $task = $_
        $hasLogonOrBoot = $false
        foreach ($trigger in @($task.Triggers)) {
            $cls = ''
            try { $cls = $trigger.CimClass.CimClassName } catch {}
            if ($cls -match 'Logon|Boot|Startup') { $hasLogonOrBoot = $true }
        }
        if ($hasLogonOrBoot) {
            $action = ''
            try { $action = ($task.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ' } catch {}
            $fullName = ($task.TaskPath.TrimEnd('\') + '\' + $task.TaskName)
            Add-Item 'scheduled_task' $fullName $action.Trim() $task.TaskPath
        }
    }
} catch {}

$json = if ($items.Count -eq 0) { '[]' } else { @($items) | ConvertTo-Json -Compress -Depth 4 }
[System.IO.File]::WriteAllText($env:WINOPT_OUT, $json, [System.Text.UTF8Encoding]::new($false))
"""


_SID_SUFFIX = re.compile(r"[-_ ]?S-1-5-21(?:-\d+)+$", re.IGNORECASE)


def pretty_name(name: str) -> str:
    """Короткое имя для показа: без пути планировщика и SID пользователя в конце."""
    text = name.rsplit("\\", 1)[-1] if name.startswith("\\") else name
    return _SID_SUFFIX.sub("", text).strip() or name


@dataclass(frozen=True)
class StartupItem:
    kind: str
    name: str
    command: str
    location: str


def collect_startup() -> list[StartupItem]:
    with tempfile.TemporaryDirectory(prefix="winopt_") as tmp:
        out_file = Path(tmp) / "startup.json"
        completed = run_powershell(_PS_SCRIPT, { "WINOPT_OUT": str(out_file)}, timeout=120)
        payload = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
    if not payload:
        err = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(err or "Не удалось прочитать автозапуск")

    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]

    items: list[StartupItem] = []
    seen: set[tuple[str, str]] = set()
    for raw in data:
        item = StartupItem(
            kind=str(raw.get("Kind") or ""),
            name=str(raw.get("Name") or ""),
            command=str(raw.get("Command") or "").strip(),
            location=str(raw.get("Location") or ""),
        )
        if item.name.casefold() == "desktop.ini":
            continue
        if item.kind == "scheduled_task" and _is_microsoft_task(item):
            continue
        identity = (item.name.casefold(), item.command.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        items.append(item)
    return items


def _is_microsoft_task(item: StartupItem) -> bool:
    blob = f"{item.name} {item.location}".casefold()
    return "\\microsoft\\windows\\" in blob or blob.startswith("\\microsoft\\")
