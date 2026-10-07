"""Консольный интерфейс диагностики Windows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from winopt import __version__
from winopt.cleanup import clean_categories, format_scan, format_size, list_categories, scan_categories
from winopt.disk import find_large_files, format_disk_report, scan_largest_folders
from winopt.duplicates import format_duplicate_report, scan_duplicates
from winopt.heuristics import score_level
from winopt.network import collect_connections, format_connections
from winopt.processes import ProcessInfo, iter_processes
from winopt.programs import filter_programs, format_programs, list_programs
from winopt.restore import create_restore_point
from winopt.services import format_services, list_services
from winopt.startup import collect_startup


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="winopt",
        description=(
            "WinOpt — диагностика и бережная оптимизация Windows. "
            "Без аргументов открывается окно программы. "
            "Это не антивирус: программа ищет подозрительные признаки, но не лечит заражение."
        ),
    )
    parser.add_argument("--version", action="version", version=f"winopt {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan_p = sub.add_parser("scan", help="Проверить запущенные процессы")
    scan_p.add_argument("--min-score", type=int, default=25, help="Минимальный балл для вывода (по умолчанию 25)")
    scan_p.add_argument("--json", action="store_true", help="Вывести JSON")
    scan_p.add_argument("--limit", type=int, default=30, help="Сколько процессов показать")

    res_p = sub.add_parser("resources", help="Процессы с высокой нагрузкой CPU/RAM")
    res_p.add_argument("--limit", type=int, default=15)

    start_p = sub.add_parser("startup", help="Показать автозагрузку")
    start_p.add_argument("--json", action="store_true")

    gui_p = sub.add_parser("gui", help="Открыть окно программы")
    gui_p.add_argument(
        "--page",
        default="dashboard",
        help="Раздел при открытии: dashboard, optimize, processes, startup, cleanup, disk, "
        "programs, services, network, security, health, journal",
    )

    sub.add_parser("shortcut", help="Создать ярлык на рабочем столе")

    clean_p = sub.add_parser("cleanup", help="Сканировать или очистить временные файлы")
    clean_p.add_argument("--scan", action="store_true", help="Только показать, сколько можно удалить")
    clean_p.add_argument("--all", action="store_true", help="Очистить все безопасные категории по умолчанию")
    clean_p.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение (только с --all)")

    disk_p = sub.add_parser("disk", help="Крупнейшие папки на диске")
    disk_p.add_argument("--drive", default=None, help="Диск, например D: (по умолчанию системный)")
    lf_p = sub.add_parser("large-files", help="Большие файлы в папках пользователя и на других дисках")
    lf_p.add_argument("--min-mb", type=int, default=250)
    sub.add_parser("health", help="Состояние дисков (SMART) и батареи")
    sub.add_parser("history", help="Журнал действий программы")
    sub.add_parser("duplicates", help="Поиск повторяющихся файлов")
    net_p = sub.add_parser("network", help="Сетевые подключения процессов")
    net_p.add_argument("--external", action="store_true", help="Только внешние адреса")
    prog_p = sub.add_parser("programs", help="Установленные программы")
    prog_p.add_argument(
        "--filter",
        choices=["all", "large", "no_publisher", "recent", "A", "B", "store", "removable"],
        help="A — «лишнее», B — «на ваше усмотрение» (по обзору), store — приложения Магазина, removable — не защищённые",
        default="all",
    )
    sub.add_parser("services", help="Рекомендуемые службы для ручного запуска")
    restore_p = sub.add_parser("restore-point", help="Создать точку восстановления")
    restore_p.add_argument("--yes", action="store_true", help="Не спрашивать (нужны права администратора)")

    rep_p = sub.add_parser("report", help="Сохранить полный отчёт в JSON")
    rep_p.add_argument("--out", default="winopt-report.json", help="Путь к файлу отчёта")

    args = parser.parse_args(argv)
    command = args.command or "scan"
    if command == "scan":
        min_score = getattr(args, "min_score", 25)
        as_json = getattr(args, "json", False)
        limit = getattr(args, "limit", 30)
        return cmd_scan(min_score=min_score, as_json=as_json, limit=limit)
    if command == "resources":
        return cmd_resources(limit=args.limit)
    if command == "startup":
        return cmd_startup(as_json=args.json)
    if command == "gui":
        from winopt.gui import run_gui

        return run_gui(args.page)
    if command == "shortcut":
        from winopt.shortcut import install_desktop_shortcut

        path = install_desktop_shortcut()
        print(f"Ярлык создан: {path}")
        return 0
    if command == "cleanup":
        return cmd_cleanup(scan=args.scan, clean_all=args.all, yes=args.yes)
    if command == "disk":
        return cmd_disk(args.drive)
    if command == "large-files":
        return cmd_large_files(args.min_mb)
    if command == "health":
        return cmd_health()
    if command == "history":
        return cmd_history()
    if command == "duplicates":
        return cmd_duplicates()
    if command == "network":
        return cmd_network(external_only=args.external)
    if command == "programs":
        return cmd_programs(filter_mode=args.filter)
    if command == "services":
        return cmd_services()
    if command == "restore-point":
        return cmd_restore_point(yes=args.yes)
    if command == "report":
        return cmd_report(Path(args.out))
    parser.print_help()
    return 2


def cmd_scan(min_score: int, as_json: bool, limit: int) -> int:
    print("Сканирование процессов, подписей и путей...", file=sys.stderr)
    processes = iter_processes()
    flagged = [p for p in processes if p.score >= min_score][:limit]
    if as_json:
        print(json.dumps([_process_dict(p) for p in flagged], ensure_ascii=False, indent=2))
        return 0

    print()
    print(f"Всего процессов: {len(processes)}")
    print(f"С баллом ≥ {min_score}: {sum(1 for p in processes if p.score >= min_score)}")
    print()
    if not flagged:
        print("Подозрительных по выбранному порогу не найдено.")
        print("Для полного списка: python -m winopt scan --min-score 0")
        return 0

    print(f"{'балл':>5}  {'уровень':<14} {'PID':>7}  {'CPU%':>6}  {'RAM':>7}  имя")
    print("-" * 88)
    for proc in flagged:
        print(
            f"{proc.score:5d}  {score_level(proc.score):<14} {proc.pid:7d}  "
            f"{proc.cpu_percent:5.1f}%  {proc.memory_mb:6.0f}М  {proc.name}"
        )
        if proc.exe:
            print(f"       путь: {proc.exe}")
        if proc.meta:
            company = proc.meta.company or "—"
            print(f"       подпись: {proc.meta.signature_status}; компания: {company}")
        for finding in proc.findings:
            print(f"       - [{finding.code} +{finding.points}] {finding.message}")
        print()

    print("Важно: высокий балл — это признак для проверки, а не доказательство вируса.")
    print("Не завершайте процессы Windows наугад. Для лечения используйте Защитник Windows.")
    return 0


def cmd_resources(limit: int) -> int:
    print("Замер нагрузки CPU/RAM...", file=sys.stderr)
    processes = [
        p
        for p in iter_processes()
        if p.pid != 0 and p.name.casefold() != "system idle process"
    ]
    by_cpu = sorted(processes, key=lambda p: p.cpu_percent, reverse=True)[:limit]
    by_ram = sorted(processes, key=lambda p: p.memory_mb, reverse=True)[:limit]

    print()
    print(f"Топ {limit} по CPU")
    print("-" * 72)
    for proc in by_cpu:
        print(f"{proc.cpu_percent:6.1f}%  {proc.memory_mb:7.0f} МБ  {proc.pid:7d}  {proc.name}")

    print()
    print(f"Топ {limit} по памяти")
    print("-" * 72)
    for proc in by_ram:
        print(f"{proc.memory_mb:7.0f} МБ  {proc.cpu_percent:6.1f}%  {proc.pid:7d}  {proc.name}")
    return 0


def cmd_startup(as_json: bool) -> int:
    print("Чтение автозагрузки...", file=sys.stderr)
    items = collect_startup()
    if as_json:
        print(
            json.dumps(
                [item.__dict__ for item in items],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print()
    print(f"Записей автозапуска: {len(items)}")
    print()
    for item in items:
        print(f"[{item.kind}] {item.name}")
        if item.command:
            print(f"    команда: {item.command}")
        if item.location:
            print(f"    где: {item.location}")
        print()
    return 0


def cmd_cleanup(scan: bool, clean_all: bool, yes: bool) -> int:
    if clean_all and not yes:
        print("Для очистки из консоли добавьте --yes", file=sys.stderr)
        return 2

    print("Сканирование временных файлов...", file=sys.stderr)
    results = scan_categories()
    print(format_scan(results))

    if scan or not clean_all:
        return 0

    ids = [cat.id for cat in list_categories() if cat.default_selected]
    result = clean_categories(ids)
    print()
    print(f"Удалено файлов: {result.deleted_files}")
    print(f"Освобождено: {format_size(result.freed_bytes)}")
    print(f"Пропущено: {result.skipped_files}")
    if result.errors:
        print("Ошибки:")
        for err in result.errors[:10]:
            print(f"  - {err}")
    return 0


def cmd_disk(drive: str | None = None) -> int:
    print("Сканирование крупных папок...", file=sys.stderr)
    items = scan_largest_folders(drive.rstrip("\\") + "\\" if drive else None)
    print(format_disk_report(items))
    return 0


def cmd_large_files(min_mb: int) -> int:
    print(f"Поиск файлов больше {min_mb} МБ...", file=sys.stderr)
    for item in find_large_files(min_size_mb=min_mb, limit=60):
        print(f"{format_size(item.size_bytes):>10}  {item.path}")
    return 0


def cmd_health() -> int:
    from winopt.health import battery_health, physical_disks

    print("=== Накопители ===")
    try:
        for d in physical_disks():
            extra = []
            if d.temperature:
                extra.append(f"{d.temperature} °C")
            if d.wear is not None:
                extra.append(f"износ {d.wear}%")
            print(f"{d.name} ({d.media}, {format_size(d.size_bytes)}): {d.health_ru} {'; '.join(extra)}")
    except Exception as exc:  # noqa: BLE001
        print(f"Недоступно: {exc}")
    print()
    print("=== Батарея ===")
    try:
        bats = battery_health()
        if not bats:
            print("Батарея не найдена")
        for b in bats:
            print(f"{b.name}: здоровье {b.health_percent}% ({b.full_mwh} из {b.design_mwh} мВт·ч), циклов: {b.cycle_count or '—'}")
    except Exception as exc:  # noqa: BLE001
        print(f"Недоступно: {exc}")
    return 0


def cmd_history() -> int:
    from winopt.history import read_history

    entries = read_history(100)
    if not entries:
        print("Журнал пуст.")
    for e in entries:
        print(f"{e.time}  [{e.category}] {e.action}  {e.details}{'' if e.ok else '  (ошибка)'}")
    return 0


def cmd_duplicates() -> int:
    print("Поиск повторяющихся файлов...", file=sys.stderr)
    result = scan_duplicates()
    print(format_duplicate_report(result))
    return 0


def cmd_network(external_only: bool) -> int:
    print("Чтение сетевых подключений...", file=sys.stderr)
    items = collect_connections()
    print(format_connections(items, external_only=external_only))
    return 0


def cmd_programs(filter_mode: str) -> int:
    print("Чтение установленных программ...", file=sys.stderr)
    programs = list_programs()
    filtered = filter_programs(programs, filter_mode)
    print(format_programs(filtered))
    return 0


def cmd_services() -> int:
    print("Чтение служб...", file=sys.stderr)
    items = list_services()
    print(format_services(items, recommended_only=True))
    return 0


def cmd_restore_point(yes: bool) -> int:
    if not yes:
        print("Добавьте --yes для создания точки восстановления (нужны права администратора).", file=sys.stderr)
        return 2
    create_restore_point("WinOpt — точка восстановления из CLI")
    print("Точка восстановления создана.")
    return 0


def cmd_report(out: Path) -> int:
    print("Сбор полного отчёта...", file=sys.stderr)
    processes = iter_processes()
    startup = collect_startup()
    payload = {
        "version": __version__,
        "process_count": len(processes),
        "flagged_count": sum(1 for p in processes if p.score >= 25),
        "processes": [_process_dict(p) for p in processes],
        "startup": [item.__dict__ for item in startup],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Отчёт сохранён: {out.resolve()}")
    print(f"Процессов: {payload['process_count']}, с баллом ≥ 25: {payload['flagged_count']}")
    return 0


def _process_dict(proc: ProcessInfo) -> dict:
    return {
        "pid": proc.pid,
        "name": proc.name,
        "exe": proc.exe,
        "username": proc.username,
        "cpu_percent": round(proc.cpu_percent, 2),
        "memory_mb": round(proc.memory_mb, 1),
        "status": proc.status,
        "score": proc.score,
        "level": score_level(proc.score),
        "signature": proc.meta.signature_status if proc.meta else None,
        "company": proc.meta.company if proc.meta else None,
        "findings": [finding.__dict__ for finding in proc.findings],
    }


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
