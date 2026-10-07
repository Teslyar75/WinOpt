"""Живые показатели системы (CPU, память, диск, сеть, батарея) и оценка состояния."""

from __future__ import annotations

import os
import platform
import time
from collections import deque
from dataclasses import dataclass, field

import psutil

from winopt.winutil import format_duration, format_size

HISTORY_POINTS = 90  # 90 секунд истории на графиках


@dataclass
class Snapshot:
    cpu_percent: float
    cpu_freq_mhz: float
    ram_percent: float
    ram_used: int
    ram_total: int
    swap_percent: float
    net_down: float  # байт/с
    net_up: float
    disk_read: float
    disk_write: float
    battery_percent: float | None
    battery_plugged: bool | None
    battery_secs_left: int | None
    uptime_seconds: float
    process_count: int


@dataclass
class LiveSampler:
    """Снимает показатели раз в секунду и хранит историю для графиков."""

    cpu: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    ram: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    down: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    up: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    disk: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    _last_net: tuple | None = None
    _last_disk: tuple | None = None
    _last_time: float = 0.0
    _proc_count: int = 0
    _proc_time: float = 0.0
    last: Snapshot | None = None

    def __post_init__(self) -> None:
        psutil.cpu_percent(interval=None)
        self._prime()

    def _prime(self) -> None:
        self._last_time = time.monotonic()
        try:
            n = psutil.net_io_counters()
            self._last_net = (n.bytes_recv, n.bytes_sent)
        except Exception:
            self._last_net = None
        try:
            d = psutil.disk_io_counters()
            self._last_disk = (d.read_bytes, d.write_bytes) if d else None
        except Exception:
            self._last_disk = None

    def sample(self) -> Snapshot:
        now = time.monotonic()
        dt = max(now - self._last_time, 0.001)
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        try:
            swap = psutil.swap_memory().percent
        except Exception:
            swap = 0.0
        try:
            freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0.0
        except Exception:
            freq = 0.0

        down = up = rd = wr = 0.0
        try:
            n = psutil.net_io_counters()
            if self._last_net:
                down = max(0.0, (n.bytes_recv - self._last_net[0]) / dt)
                up = max(0.0, (n.bytes_sent - self._last_net[1]) / dt)
            self._last_net = (n.bytes_recv, n.bytes_sent)
        except Exception:
            pass
        try:
            d = psutil.disk_io_counters()
            if d and self._last_disk:
                rd = max(0.0, (d.read_bytes - self._last_disk[0]) / dt)
                wr = max(0.0, (d.write_bytes - self._last_disk[1]) / dt)
            self._last_disk = (d.read_bytes, d.write_bytes) if d else None
        except Exception:
            pass
        self._last_time = now

        batt_pct = batt_plug = batt_left = None
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                batt_pct = float(batt.percent)
                batt_plug = bool(batt.power_plugged)
                if batt.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                    batt_left = int(batt.secsleft)
        except Exception:
            pass

        if now - self._proc_time > 5:
            try:
                self._proc_count = len(psutil.pids())
            except Exception:
                pass
            self._proc_time = now

        snap = Snapshot(
            cpu_percent=cpu,
            cpu_freq_mhz=freq,
            ram_percent=mem.percent,
            ram_used=mem.total - mem.available,
            ram_total=mem.total,
            swap_percent=swap,
            net_down=down,
            net_up=up,
            disk_read=rd,
            disk_write=wr,
            battery_percent=batt_pct,
            battery_plugged=batt_plug,
            battery_secs_left=batt_left,
            uptime_seconds=time.time() - psutil.boot_time(),
            process_count=self._proc_count,
        )
        self.cpu.append(cpu)
        self.ram.append(mem.percent)
        self.down.append(down)
        self.up.append(up)
        self.disk.append(rd + wr)
        self.last = snap
        return snap


@dataclass(frozen=True)
class SystemInfo:
    os_name: str
    os_build: str
    cpu_name: str
    cores: int
    threads: int
    ram_total: int
    computer: str
    user: str


def system_info() -> SystemInfo:
    os_name = f"{platform.system()} {platform.release()}"
    build = platform.version()
    cpu_name = platform.processor() or "—"
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
                product = winreg.QueryValueEx(key, "ProductName")[0]
                try:
                    display = winreg.QueryValueEx(key, "DisplayVersion")[0]
                except OSError:
                    display = ""
                build_no = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
                # В реестре Windows 11 по-прежнему пишет «Windows 10» — исправляем по номеру сборки.
                if int(build_no) >= 22000:
                    product = product.replace("Windows 10", "Windows 11")
                os_name = product
                build = f"{display} (сборка {build_no})".strip()
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                cpu_name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except Exception:
            pass
    return SystemInfo(
        os_name=os_name,
        os_build=build,
        cpu_name=cpu_name,
        cores=psutil.cpu_count(logical=False) or 0,
        threads=psutil.cpu_count(logical=True) or 0,
        ram_total=psutil.virtual_memory().total,
        computer=platform.node(),
        user=os.environ.get("USERNAME", ""),
    )


@dataclass(frozen=True)
class HealthIssue:
    level: str  # ok | info | warn | danger
    title: str
    text: str
    page: str = ""  # куда перейти, чтобы исправить


def assess_health(
    snapshot: Snapshot | None,
    disks: list,
    startup_recommended: int | None,
    defender_ok: bool | None,
    junk_bytes: int | None,
    ram_history: list[float] | None = None,
) -> tuple[int, list[HealthIssue]]:
    """Простая оценка «здоровья» 0–100 и список советов."""
    score = 100
    issues: list[HealthIssue] = []

    sys_disk = next((d for d in disks if d.drive.upper().startswith("C")), disks[0] if disks else None)
    if sys_disk:
        free_pct = 100 - sys_disk.used_percent
        if sys_disk.free_bytes < 5 * 1024**3 or free_pct < 7:
            score -= 30
            issues.append(
                HealthIssue(
                    "danger",
                    f"Диск {sys_disk.drive} почти заполнен",
                    f"Свободно {format_size(sys_disk.free_bytes)}. Windows и программы замедляются, "
                    "обновления могут не установиться.",
                    "cleanup",
                )
            )
        elif free_pct < 15:
            score -= 12
            issues.append(
                HealthIssue("warn", f"Мало места на {sys_disk.drive}", f"Свободно {format_size(sys_disk.free_bytes)}.", "cleanup")
            )

    if defender_ok is False:
        score -= 25
        issues.append(HealthIssue("danger", "Защитник Windows выключен", "Включите защиту в «Безопасность Windows».", "security"))

    if ram_history:
        avg = sum(ram_history) / len(ram_history)
        if avg > 88:
            score -= 12
            issues.append(
                HealthIssue("warn", "Память почти вся занята", f"В среднем {avg:.0f}% — закройте лишние программы.", "processes")
            )

    if startup_recommended:
        penalty = min(15, startup_recommended * 3)
        score -= penalty
        issues.append(
            HealthIssue(
                "warn" if startup_recommended >= 3 else "info",
                f"Автозагрузка: {startup_recommended} лишн.",
                "Эти программы замедляют включение ноутбука.",
                "startup",
            )
        )

    if junk_bytes and junk_bytes > 300 * 1024**2:
        score -= 8 if junk_bytes < 2 * 1024**3 else 12
        issues.append(
            HealthIssue("info", "Есть что почистить", f"Временные файлы и кэши: {format_size(junk_bytes)}.", "cleanup")
        )

    if snapshot and snapshot.uptime_seconds > 7 * 86400:
        score -= 5
        issues.append(
            HealthIssue(
                "info",
                "Давно не было перезагрузки",
                f"Компьютер работает {format_duration(snapshot.uptime_seconds)}. Перезагрузка освежит систему.",
            )
        )

    if not issues:
        issues.append(HealthIssue("ok", "Всё в порядке", "Серьёзных проблем не найдено."))
    return max(0, min(100, score)), issues
