"""Сетевые подключения процессов."""

from __future__ import annotations

from dataclasses import dataclass

import psutil

import ipaddress


@dataclass(frozen=True)
class NetConnection:
    pid: int
    process_name: str
    local: str
    remote: str
    status: str
    external: bool


def collect_connections() -> list[NetConnection]:
    proc_names: dict[int, str] = {}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_names[proc.info["pid"]] = proc.info["name"] or ""
        except (psutil.Error, OSError):
            continue

    rows: list[NetConnection] = []
    seen: set[tuple] = set()
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.Error, PermissionError) as exc:
        raise RuntimeError(
            "Не удалось прочитать сетевые подключения. "
            "Запустите программу от имени администратора для полного списка."
        ) from exc

    for conn in connections:
        if not conn.raddr:
            continue
        remote_ip = conn.raddr.ip
        remote_port = conn.raddr.port
        local = _fmt_addr(conn.laddr)
        remote = f"{remote_ip}:{remote_port}"
        pid = conn.pid or 0
        name = proc_names.get(pid, "")
        if pid and not name:
            name = _resolve_name(pid)
        key = (pid, local, remote, conn.status)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            NetConnection(
                pid=pid,
                process_name=name or "—",
                local=local,
                remote=remote,
                status=conn.status,
                external=_is_external(remote_ip),
            )
        )

    rows.sort(key=lambda row: (not row.external, row.process_name.casefold(), row.remote))
    return rows


def format_connections(items: list[NetConnection], external_only: bool = False) -> str:
    filtered = [item for item in items if item.external] if external_only else items
    lines = ["=== Сетевые подключения ===", ""]
    if not filtered:
        lines.append("Активных подключений не найдено (или доступ ограничен).")
        return "\n".join(lines)
    for item in filtered[:80]:
        tag = "внешнее" if item.external else "локальное"
        lines.append(
            f"[{tag}] {item.process_name} (PID {item.pid})  {item.local} → {item.remote}  ({item.status})"
        )
    if len(filtered) > 80:
        lines.append(f"\n… и ещё {len(filtered) - 80} подключений")
    return "\n".join(lines)


def _resolve_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return ""


def _fmt_addr(addr) -> str:
    if not addr:
        return "—"
    return f"{addr.ip}:{addr.port}"


def _is_external(ip: str) -> bool:
    if ip in {"0.0.0.0", "::", "*"}:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        return False
