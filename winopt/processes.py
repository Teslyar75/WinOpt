"""Сбор сведений о запущенных процессах."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import psutil

from winopt.heuristics import Finding, evaluate_process
from winopt.meta import FileMeta, collect_file_meta


@dataclass
class ProcessInfo:
    pid: int
    name: str
    exe: str
    username: str
    cpu_percent: float
    memory_mb: float
    status: str
    cmdline: str
    meta: FileMeta | None
    access_denied: bool = False
    findings: list[Finding] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(item.points for item in self.findings)


def iter_processes(sample_seconds: float = 0.8, with_meta: bool = True) -> list[ProcessInfo]:
    procs = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc.cpu_percent(interval=None)
            procs.append(proc)
        except (psutil.Error, OSError):
            continue

    time.sleep(sample_seconds)

    snapshots: list[dict] = []
    paths: list[str] = []
    for proc in procs:
        try:
            with proc.oneshot():
                access_denied = False
                try:
                    exe = proc.exe() or ""
                except psutil.AccessDenied:
                    exe = ""
                    access_denied = True
                memory = proc.memory_info().rss / (1024 * 1024)
                try:
                    username = proc.username() or ""
                except (psutil.Error, OSError, PermissionError):
                    username = ""
                try:
                    cmdline_list = proc.cmdline() or []
                except (psutil.Error, OSError, PermissionError):
                    cmdline_list = []
                snapshots.append(
                    {
                        "pid": proc.pid,
                        "name": proc.name() or "",
                        "exe": exe,
                        "username": username or "",
                        "cpu_percent": proc.cpu_percent(interval=None),
                        "memory_mb": memory,
                        "status": proc.status(),
                        "cmdline": " ".join(cmdline_list),
                        "access_denied": access_denied,
                    }
                )
                if exe:
                    paths.append(exe)
        except (psutil.Error, OSError, PermissionError):
            continue

    meta_map = collect_file_meta(paths) if with_meta else {}
    result: list[ProcessInfo] = []
    for item in snapshots:
        exe = item["exe"]
        meta = meta_map.get(exe.casefold()) if exe else None
        info = ProcessInfo(
            pid=item["pid"],
            name=item["name"],
            exe=exe,
            username=item["username"],
            cpu_percent=item["cpu_percent"],
            memory_mb=item["memory_mb"],
            status=item["status"],
            cmdline=item["cmdline"],
            meta=meta,
            access_denied=item["access_denied"],
        )
        info.findings = evaluate_process(info)
        result.append(info)

    result.sort(key=lambda p: (p.score, p.cpu_percent, p.memory_mb), reverse=True)
    return result


# ---------------------------------------------------------------------------
# Быстрый живой список процессов для страницы «Процессы» (без проверки подписей)
# ---------------------------------------------------------------------------

CRITICAL_NAMES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "fontdrvhost.exe",
    "dwm.exe", "explorer.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "msmpeng.exe", "nissrv.exe", "memory compression",
    "audiodg.exe", "conhost.exe", "spoolsv.exe", "wudfhost.exe", "dllhost.exe",
    "applicationframehost.exe", "lockapp.exe", "systemsettings.exe",
}


@dataclass
class ProcRow:
    pid: int
    name: str
    exe: str
    username: str
    cpu: float  # % от всего процессора (как в диспетчере задач)
    memory: int  # байт (частный рабочий набор, если доступен)
    threads: int
    group_count: int = 1


class ProcessMonitor:
    """Хранит объекты процессов между обновлениями, чтобы правильно считать CPU."""

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}
        self._ncpu = psutil.cpu_count(logical=True) or 1
        self._user = _current_user()

    def refresh(self) -> list[ProcRow]:
        rows: list[ProcRow] = []
        alive: set[int] = set()
        for proc in psutil.process_iter(["pid", "name"]):
            pid = proc.info["pid"]
            alive.add(pid)
            if pid == 0:
                continue
            cached = self._procs.get(pid)
            if cached is None:
                # Новый процесс: первый замер CPU всегда 0, но в список его включаем сразу.
                self._procs[pid] = proc
                cached = proc
            try:
                with cached.oneshot():
                    cpu = cached.cpu_percent(interval=None) / self._ncpu
                    mem = cached.memory_info()
                    memory = getattr(mem, "private", 0) or mem.rss
                    name = cached.name()
                    try:
                        exe = cached.exe() or ""
                    except (psutil.Error, OSError):
                        exe = ""
                    try:
                        user = cached.username() or ""
                    except (psutil.Error, OSError):
                        user = ""
                    threads = cached.num_threads()
                rows.append(ProcRow(pid, name, exe, user, round(cpu, 1), memory, threads))
            except (psutil.Error, OSError):
                continue
        for pid in list(self._procs):
            if pid not in alive:
                del self._procs[pid]
        return rows

    def can_terminate(self, row: ProcRow) -> tuple[bool, str]:
        return can_terminate(row, self._user)


def _current_user() -> str:
    return os.environ.get("USERNAME", "").casefold()


def can_terminate(row: ProcRow, current_user: str | None = None) -> tuple[bool, str]:
    user = (current_user if current_user is not None else _current_user()).casefold()
    name = row.name.casefold()
    exe = row.exe.casefold().replace("/", "\\")
    windir = os.environ.get("WINDIR", r"C:\Windows").casefold()
    if row.pid in (0, 4) or row.pid == os.getpid():
        return False, "системный процесс"
    if name in CRITICAL_NAMES:
        return False, "важный процесс Windows"
    if exe.startswith(windir):
        return False, "процесс из папки Windows"
    if not row.username or row.username.split("\\")[-1].casefold() != user:
        return False, "процесс другого пользователя или системы"
    return True, ""


def terminate_process(row: ProcRow) -> None:
    ok, reason = can_terminate(row)
    if not ok:
        raise PermissionError(f"«{row.name}» завершать нельзя: {reason}.")
    proc = psutil.Process(row.pid)
    if proc.name() != row.name:
        raise RuntimeError("Процесс уже завершился (PID занят другим процессом).")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        raise RuntimeError(f"«{row.name}» не завершился за 5 секунд.")
