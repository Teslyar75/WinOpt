"""Службы Windows: сторонние службы с автозапуском.

Изменено по сравнению с версией 0.5:
  * службы драйверов/оборудования (AMD, Realtek, HP, Intel, Synaptics…)
    и антивирусов теперь ЗАЩИЩЕНЫ — раньше кнопка «Выбрать рекомендуемые»
    отмечала их все подряд, что могло сломать звук, тачпад, Wi-Fi;
  * рекомендуются только обновляторы; прочие службы — «на ваше усмотрение»;
  * каждое изменение запоминается и его можно откатить кнопкой «Вернуть».
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from winopt.history import log_action
from winopt.winutil import data_dir, run_powershell

_PS_LIST = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$items = Get-CimInstance Win32_Service | ForEach-Object {
    [pscustomobject]@{
        Name = [string]$_.Name
        DisplayName = [string]$_.DisplayName
        State = [string]$_.State
        StartMode = [string]$_.StartMode
        PathName = [string]$_.PathName
        Description = [string]$_.Description
    }
}
@($items) | ConvertTo-Json -Compress -Depth 3
"""

_PS_SET_START = r"""
$ErrorActionPreference = 'Stop'
Set-Service -Name $env:WINOPT_SVC -StartupType $env:WINOPT_MODE
'ok'
"""

PROTECTED_SERVICES = {
    "wscsvc", "windefend", "mpssvc", "bfe", "dcomlaunch", "rpcss", "eventlog",
    "plugplay", "power", "samss", "lsm", "nsi", "netprofm", "wlms", "wuauserv",
    "cbdhsvc", "camsvc", "gpsvc", "audiosrv", "audioendpointbuilder", "wlansvc",
    "bthserv", "themes", "spooler",
}

MICROSOFT_MARKERS = (
    "\\windows\\system32\\",
    "\\windows\\syswow64\\",
    "systemroot\\system32",
    "windows defender",
    "\\microsoft\\",
    "microsoft ",
)

HARDWARE_MARKERS = (
    "amd", "radeon", "ryzen", "realtek", "intel", "nvidia", "hp ", "hpsvc", "hewlett",
    "\\hp\\", "synaptics", "elan", "dolby", "conexant", "waves", "qualcomm", "mediatek",
    "broadcom", "dell", "lenovo", "asus", "acer", "bluetooth", "audio", "wlan", "wi-fi",
    "wifi", "touchpad", "driver", "firmware", "nahimic", "killer", "rtk", "omen",
    "thunderbolt", "fingerprint", "goodix", "validity",
)

SECURITY_MARKERS = (
    "kaspersky", "eset", "avast", "avg", "bitdefender", "malwarebytes", "norton",
    "mcafee", "drweb", "dr.web", "sophos", "trend micro", "panda", "comodo", "vpn",
)

UPDATER_MARKERS = ("update", "updater", "maintenance", "autoupdate", "elevation service", "armsvc", "adobearm")

CATEGORY_LABELS = {
    "updater": "обновлятор — можно «Вручную»",
    "hardware": "оборудование/драйвер — не трогать",
    "security": "защита/VPN — не трогать",
    "other": "сторонняя — на ваше усмотрение",
}


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    display_name: str
    state: str
    start_mode: str
    path: str
    description: str
    category: str  # updater | hardware | security | other | microsoft

    @property
    def recommend_manual(self) -> bool:
        return self.category == "updater"

    @property
    def changeable(self) -> bool:
        return self.category in {"updater", "other"}

    @property
    def note(self) -> str:
        return CATEGORY_LABELS.get(self.category, "системная")


def list_services(include_microsoft: bool = False) -> list[ServiceInfo]:
    completed = run_powershell(_PS_LIST, None, timeout=60)
    payload = (completed.stdout or "").strip()
    if not payload:
        err = (completed.stderr or "не удалось прочитать службы").strip()
        raise RuntimeError(err)
    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]

    result: list[ServiceInfo] = []
    for raw in data:
        name = str(raw.get("Name") or "")
        display = str(raw.get("DisplayName") or name)
        path = str(raw.get("PathName") or "")
        start_mode = str(raw.get("StartMode") or "")
        category = _categorize(name, display, path)
        if category == "microsoft" and not include_microsoft:
            continue
        if start_mode.casefold() not in {"auto", "automatic"} and not include_microsoft:
            continue
        result.append(
            ServiceInfo(
                name=name,
                display_name=display,
                state=str(raw.get("State") or ""),
                start_mode=start_mode,
                path=path,
                description=str(raw.get("Description") or ""),
                category=category,
            )
        )
    order = {"updater": 0, "other": 1, "security": 2, "hardware": 3, "microsoft": 4}
    result.sort(key=lambda s: (order.get(s.category, 9), s.display_name.casefold()))
    return result


def _categorize(name: str, display: str, path: str) -> str:
    if name.casefold() in PROTECTED_SERVICES:
        return "microsoft"
    blob = f" {name} {display} {path} ".casefold().replace("/", "\\")
    if any(marker in blob for marker in MICROSOFT_MARKERS):
        return "microsoft"
    if any(marker in blob for marker in SECURITY_MARKERS):
        return "security"
    if any(marker in blob for marker in UPDATER_MARKERS):
        return "updater"
    if any(marker in blob for marker in HARDWARE_MARKERS):
        return "hardware"
    return "other"


def _changes_path():
    return data_dir() / "services_changed.json"


def load_changed() -> list[dict]:
    path = _changes_path()
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _save_changed(items: list[dict]) -> None:
    _changes_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_start(service_name: str, mode: str) -> None:
    completed = run_powershell(_PS_SET_START, {"WINOPT_SVC": service_name, "WINOPT_MODE": mode}, timeout=30)
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        low = err.casefold()
        if "access" in low or "privilege" in low or "доступ" in low:
            raise PermissionError("Нужны права администратора (кнопка «Запустить от администратора» слева внизу).")
        raise RuntimeError(err or f"Не удалось изменить службу {service_name}")


def set_service_manual(service: ServiceInfo | str) -> None:
    if isinstance(service, str):
        name, display, previous = service, service, "Automatic"
        if service.casefold() in PROTECTED_SERVICES:
            raise PermissionError(f"Служба «{service}» защищена и не может быть изменена.")
    else:
        if not service.changeable:
            raise PermissionError(f"Служба «{service.display_name}» защищена: {service.note}.")
        name, display = service.name, service.display_name
        previous = "Automatic" if service.start_mode.casefold().startswith("auto") else service.start_mode
    _set_start(name, "Manual")
    changed = [c for c in load_changed() if c.get("name") != name]
    changed.append(
        {"name": name, "display_name": display, "previous": previous, "changed_at": datetime.now().isoformat(timespec="seconds")}
    )
    _save_changed(changed)
    log_action("Службы", f"«{display}» → Вручную", f"было: {previous}")


def revert_service(record: dict) -> None:
    name = record["name"]
    previous = record.get("previous") or "Automatic"
    _set_start(name, previous)
    _save_changed([c for c in load_changed() if c.get("name") != name])
    log_action("Службы", f"«{record.get('display_name', name)}» возвращена", f"режим: {previous}")


def format_services(items: list[ServiceInfo], recommended_only: bool = False) -> str:
    rows = [s for s in items if s.recommend_manual] if recommended_only else items
    lines = ["=== Службы Windows (сторонние, автозапуск) ===", ""]
    if not rows:
        lines.append("Подходящих служб не найдено.")
        return "\n".join(lines)
    for svc in rows[:60]:
        lines.append(f"{svc.display_name} ({svc.name})")
        lines.append(f"  запуск: {svc.start_mode}; состояние: {svc.state}; {svc.note}")
    return "\n".join(lines)
