"""Здоровье компьютера: состояние физических дисков (SMART) и износ батареи."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from winopt.winutil import reports_dir, run_powershell, run_quiet

_PS_DISKS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$items = Get-PhysicalDisk | ForEach-Object {
    $rc = $_ | Get-StorageReliabilityCounter
    [pscustomobject]@{
        Name = [string]$_.FriendlyName
        Media = [string]$_.MediaType
        Bus = [string]$_.BusType
        Health = [string]$_.HealthStatus
        Status = [string]($_.OperationalStatus -join ', ')
        Size = [int64]$_.Size
        Temperature = $rc.Temperature
        Wear = $rc.Wear
        PowerOnHours = $rc.PowerOnHours
        ReadErrors = $rc.ReadErrorsTotal
        WriteErrors = $rc.WriteErrorsTotal
    }
}
@($items) | ConvertTo-Json -Compress
"""


@dataclass(frozen=True)
class PhysicalDiskHealth:
    name: str
    media: str
    bus: str
    health: str
    status: str
    size_bytes: int
    temperature: int | None
    wear: int | None
    power_on_hours: int | None
    read_errors: int | None
    write_errors: int | None

    @property
    def health_ru(self) -> str:
        return {"healthy": "исправен", "warning": "предупреждение", "unhealthy": "неисправен"}.get(
            self.health.casefold(), self.health or "неизвестно"
        )

    @property
    def level(self) -> str:
        h = self.health.casefold()
        if h == "healthy" and (self.wear is None or self.wear < 80):
            return "ok"
        if h == "unhealthy":
            return "danger"
        return "warn"


def physical_disks() -> list[PhysicalDiskHealth]:
    completed = run_powershell(_PS_DISKS, None, timeout=60)
    payload = (completed.stdout or "").strip()
    if not payload:
        raise RuntimeError((completed.stderr or "Не удалось получить сведения о дисках").strip())
    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]
    result = []
    for raw in data:
        result.append(
            PhysicalDiskHealth(
                name=str(raw.get("Name") or "Диск"),
                media=_media_ru(str(raw.get("Media") or "")),
                bus=str(raw.get("Bus") or ""),
                health=str(raw.get("Health") or ""),
                status=str(raw.get("Status") or ""),
                size_bytes=int(raw.get("Size") or 0),
                temperature=_int_or_none(raw.get("Temperature")),
                wear=_int_or_none(raw.get("Wear")),
                power_on_hours=_int_or_none(raw.get("PowerOnHours")),
                read_errors=_int_or_none(raw.get("ReadErrors")),
                write_errors=_int_or_none(raw.get("WriteErrors")),
            )
        )
    return result


@dataclass(frozen=True)
class BatteryHealth:
    name: str
    manufacturer: str
    chemistry: str
    design_mwh: int
    full_mwh: int
    cycle_count: int | None

    @property
    def health_percent(self) -> float:
        if self.design_mwh <= 0:
            return 0.0
        return round(min(100.0, self.full_mwh / self.design_mwh * 100), 1)

    @property
    def wear_percent(self) -> float:
        return round(100 - self.health_percent, 1)


def battery_health() -> list[BatteryHealth]:
    """Прочитать ёмкость батареи из отчёта powercfg (права администратора не нужны)."""
    out = reports_dir() / "battery.xml"
    completed = run_quiet(["powercfg", "/batteryreport", "/xml", "/output", str(out)], timeout=60)
    if not out.exists():
        raise RuntimeError((completed.stdout or completed.stderr or "Батарея не найдена").strip())
    tree = ET.parse(out)
    result: list[BatteryHealth] = []
    for elem in tree.iter():
        if _local(elem.tag) != "Battery":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in elem}
        design = _int_or_none(fields.get("DesignCapacity")) or 0
        full = _int_or_none(fields.get("FullChargeCapacity")) or 0
        if design == 0 and full == 0:
            continue
        result.append(
            BatteryHealth(
                name=fields.get("Id", "Батарея"),
                manufacturer=fields.get("Manufacturer", ""),
                chemistry=fields.get("Chemistry", ""),
                design_mwh=design,
                full_mwh=full,
                cycle_count=_int_or_none(fields.get("CycleCount")),
            )
        )
    return result


def battery_report_html() -> Path:
    """Создать подробный HTML-отчёт Windows о батарее и вернуть путь к нему."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = reports_dir() / f"battery-report-{stamp}.html"
    completed = run_quiet(["powercfg", "/batteryreport", "/output", str(out)], timeout=60)
    if not out.exists():
        raise RuntimeError((completed.stdout or completed.stderr or "Не удалось создать отчёт").strip())
    return out


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _media_ru(media: str) -> str:
    return {"SSD": "SSD", "HDD": "HDD", "Unspecified": "не указан", "SCM": "SCM"}.get(media, media or "—")
