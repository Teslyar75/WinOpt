"""Безопасное отключение и восстановление пунктов автозагрузки."""

from __future__ import annotations

from winopt.winutil import run_powershell

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from winopt.history import log_action
from winopt.startup import StartupItem, collect_startup

PROTECTED_NAMES = {
    "securityhealth",
    "securityhealthsystray",
    "windows defender notification icon",
    "userinit",
    "explorer",
    "ctfmon",
}

PROTECTED_MARKERS = (
    "\\windows\\system32\\securityhealth",
    "\\windows\\system32\\userinit.exe",
    "\\windows\\explorer.exe",
)

KIND_LABELS = {
    "registry": "реестр",
    "startup_folder": "папка автозагрузки",
    "scheduled_task": "планировщик заданий",
    "startup_command": "автозагрузка",
}


def backup_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinOpt"
    files = root / "startup_files"
    files.mkdir(parents=True, exist_ok=True)
    return root


def backup_index_path() -> Path:
    return backup_dir() / "disabled.json"


def load_disabled() -> list[dict]:
    path = backup_index_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items", [])
    return list(data)


def save_disabled(items: list[dict]) -> None:
    backup_index_path().write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_actionable_startup() -> list[StartupItem]:
    items: list[StartupItem] = []
    seen: set[tuple[str, str]] = set()
    for item in collect_startup():
        if item.kind not in {"registry", "startup_folder", "scheduled_task"}:
            continue
        key = (item.kind, item.name.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def is_protected(item: StartupItem) -> bool:
    name = item.name.casefold()
    blob = f"{item.name} {item.command} {item.location}".casefold().replace("/", "\\")
    if name in PROTECTED_NAMES:
        return True
    return any(marker in blob for marker in PROTECTED_MARKERS)


def is_caution(item: StartupItem) -> bool:
    blob = f"{item.command} {item.location}".casefold().replace("/", "\\")
    return "\\windows\\system32\\" in blob or "\\windows\\syswow64\\" in blob or "\\driverstore\\" in blob


def disable_item(item: StartupItem) -> dict:
    if is_protected(item):
        raise PermissionError(
            f"«{item.name}» защищён: это компонент Windows, его нельзя отключать здесь."
        )

    record = {
        "kind": item.kind,
        "name": item.name,
        "command": item.command,
        "location": item.location,
        "disabled_at": datetime.now(timezone.utc).isoformat(),
        "moved_file": "",
    }

    if item.kind == "registry":
        _registry_remove(item.location, item.name)
    elif item.kind == "startup_folder":
        record["moved_file"] = _move_startup_file(item.command or item.name)
    elif item.kind == "scheduled_task":
        _scheduled_task_set(item, enabled=False)
    else:
        raise ValueError(f"Этот тип записи отключать нельзя: {item.kind}")

    disabled = load_disabled()
    disabled.append(record)
    save_disabled(disabled)
    log_action("Автозагрузка", f"Отключено «{item.name}»", KIND_LABELS.get(item.kind, item.kind))
    return record


def restore_record(record: dict) -> None:
    kind = record.get("kind")
    if kind == "registry":
        _registry_restore(record["location"], record["name"], record.get("command") or "")
    elif kind == "startup_folder":
        _restore_startup_file(record)
    elif kind == "scheduled_task":
        item = StartupItem(
            kind="scheduled_task",
            name=record["name"],
            command=record.get("command") or "",
            location=record.get("location") or "\\",
        )
        _scheduled_task_set(item, enabled=True)
    else:
        raise ValueError(f"Неизвестный тип записи: {kind}")

    remaining = [
        item
        for item in load_disabled()
        if not (
            item.get("kind") == record.get("kind")
            and item.get("name") == record.get("name")
            and item.get("disabled_at") == record.get("disabled_at")
        )
    ]
    save_disabled(remaining)
    log_action("Автозагрузка", f"Возвращено «{record.get('name')}»", KIND_LABELS.get(kind, str(kind)))


def _run_ps(script: str, env_extra: dict[str, str]) -> str:
    completed = run_powershell(script, env_extra, timeout=60)
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "ошибка PowerShell").strip()
        raise RuntimeError(err)
    return (completed.stdout or "").strip()


def _normalize_run_key(location: str) -> str:
    loc = location.strip()
    if loc.lower().startswith("hkcu:"):
        return loc
    if loc.lower().startswith("hklm:"):
        return loc
    if loc.upper().startswith("HKCU\\"):
        return "HKCU:\\" + loc[5:].lstrip("\\")
    if loc.upper().startswith("HKLM\\"):
        return "HKLM:\\" + loc[5:].lstrip("\\")
    if loc.upper().startswith("HKU\\"):
        # Для текущего пользователя HKU\SID\SOFTWARE\... = HKCU\SOFTWARE\...
        parts = loc.split("\\")
        try:
            software_at = next(i for i, p in enumerate(parts) if p.casefold() == "software")
            return "HKCU:\\" + "\\".join(parts[software_at:])
        except StopIteration:
            return loc
    return loc


def _registry_remove(location: str, name: str) -> None:
    key = _normalize_run_key(location)
    script = r"""
$key = $env:WINOPT_KEY
$name = $env:WINOPT_NAME
if (-not (Test-Path -LiteralPath $key)) { throw "Ключ реестра не найден: $key" }
Remove-ItemProperty -LiteralPath $key -Name $name -ErrorAction Stop
"""
    _run_ps(script, {"WINOPT_KEY": key, "WINOPT_NAME": name})


def _registry_restore(location: str, name: str, command: str) -> None:
    key = _normalize_run_key(location)
    script = r"""
$key = $env:WINOPT_KEY
$name = $env:WINOPT_NAME
$value = $env:WINOPT_VALUE
if (-not (Test-Path -LiteralPath $key)) {
    New-Item -Path $key -Force | Out-Null
}
New-ItemProperty -LiteralPath $key -Name $name -Value $value -PropertyType String -Force -ErrorAction Stop | Out-Null
"""
    _run_ps(script, {"WINOPT_KEY": key, "WINOPT_NAME": name, "WINOPT_VALUE": command})


def _move_startup_file(path_str: str) -> str:
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError(f"Файл автозагрузки не найден: {path_str}")
    dest_dir = backup_dir() / "startup_files"
    dest = dest_dir / src.name
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = dest_dir / f"{src.stem}-{stamp}{src.suffix}"
    shutil.move(str(src), str(dest))
    return str(dest)


def _restore_startup_file(record: dict) -> None:
    moved = Path(record.get("moved_file") or "")
    original = Path(record.get("command") or "")
    if not moved.exists():
        raise FileNotFoundError(f"Резервная копия не найдена: {moved}")
    original.parent.mkdir(parents=True, exist_ok=True)
    if original.exists():
        raise FileExistsError(f"Файл уже снова на месте: {original}")
    shutil.move(str(moved), str(original))


def _scheduled_task_set(item: StartupItem, enabled: bool) -> None:
    task_path, task_name = _split_task(item)
    cmdlet = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
    script = rf"""
$task = Get-ScheduledTask -TaskName $env:WINOPT_TASK_NAME -TaskPath $env:WINOPT_TASK_PATH -ErrorAction Stop
{cmdlet} -InputObject $task -ErrorAction Stop | Out-Null
"""
    _run_ps(script, {"WINOPT_TASK_NAME": task_name, "WINOPT_TASK_PATH": task_path})


def _split_task(item: StartupItem) -> tuple[str, str]:
    raw = item.name.replace("/", "\\").strip()
    if "\\" in raw:
        parent, name = raw.rsplit("\\", 1)
        path = parent if parent.endswith("\\") else parent + "\\"
        if not path.startswith("\\"):
            path = "\\" + path
        return path, name
    location = item.location.replace("/", "\\")
    if location and not location.endswith("\\"):
        location += "\\"
    if not location.startswith("\\"):
        location = "\\" + location
    return location or "\\", raw
