"""«Быстрая оптимизация»: безопасный набор действий в один клик с отчётом.

Что делает:
  1. Анализирует временные файлы, кэши браузеров, дампы сбоев.
  2. Считает лишнюю автозагрузку и свободное место (только совет — без изменений).
  3. После подтверждения удаляет выбранные временные файлы.
  4. Сохраняет текстовый отчёт и запись в журнал.

Что НЕ делает: не трогает автозагрузку, службы, реестр и программы
без отдельного решения пользователя на соответствующих страницах.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from winopt.cleanup import CategoryScan, CleanupResult, clean_categories, scan_categories
from winopt.disk import list_drives
from winopt.history import log_action
from winopt.winutil import format_size, reports_dir

SAFE_CATEGORY_IDS_PREFIX = ("user_temp", "windows_temp", "crash_dumps", "browser_")


@dataclass
class OptimizePlan:
    scans: list[CategoryScan]
    startup_recommended: list[str] = field(default_factory=list)
    system_free_bytes: int = 0
    system_total_bytes: int = 0

    @property
    def safe_scans(self) -> list[CategoryScan]:
        return [
            s
            for s in self.scans
            if s.category_id.startswith(SAFE_CATEGORY_IDS_PREFIX) and s.size_bytes > 0
        ]

    @property
    def total_bytes(self) -> int:
        return sum(s.size_bytes for s in self.safe_scans if not s.blocked_reason)


def build_plan(progress=None) -> OptimizePlan:
    scans = scan_categories(progress=progress)
    plan = OptimizePlan(scans=scans)
    if progress:
        progress("Проверяю автозагрузку…")
    try:
        from winopt.actions import collect_actionable_startup
        from winopt.startup import pretty_name
        from winopt.advice import is_recommended

        plan.startup_recommended = [pretty_name(i.name) for i in collect_actionable_startup() if is_recommended(i)]
    except Exception:  # noqa: BLE001 — автозагрузка не критична для плана
        plan.startup_recommended = []
    drives = list_drives()
    if drives:
        plan.system_free_bytes = drives[0].free_bytes
        plan.system_total_bytes = drives[0].total_bytes
    return plan


def run_plan(plan: OptimizePlan, category_ids: list[str], progress=None) -> tuple[CleanupResult, Path]:
    free_before = plan.system_free_bytes
    result = clean_categories(category_ids, progress=progress)
    drives = list_drives()
    free_after = drives[0].free_bytes if drives else 0
    report = _write_report(plan, category_ids, result, free_before, free_after)
    log_action(
        "Оптимизация",
        "Быстрая оптимизация",
        f"удалено файлов: {result.deleted_files}, освобождено {format_size(result.freed_bytes)}",
        ok=not result.errors or result.deleted_files > 0,
    )
    return result, report


def _write_report(plan, category_ids, result: CleanupResult, free_before: int, free_after: int) -> Path:
    stamp = datetime.now()
    path = reports_dir() / f"optimize-{stamp:%Y%m%d-%H%M%S}.txt"
    labels = {s.category_id: s for s in plan.scans}
    lines = [
        "ОТЧЁТ WinOpt — быстрая оптимизация",
        f"Дата: {stamp:%d.%m.%Y %H:%M}",
        "",
        "Очищено:",
    ]
    for cid in category_ids:
        scan = labels.get(cid)
        if scan:
            lines.append(f"  • {scan.label}: было {format_size(scan.size_bytes)}")
    lines += [
        "",
        f"Удалено файлов: {result.deleted_files}",
        f"Освобождено: {format_size(result.freed_bytes)}",
        f"Пропущено занятых файлов: {result.skipped_files}",
    ]
    if result.skipped_categories:
        lines.append("Пропущены категории: " + "; ".join(result.skipped_categories))
    if free_before or free_after:
        lines.append(f"Свободно на системном диске: было {format_size(free_before)}, стало {format_size(free_after)}")
    if plan.startup_recommended:
        lines += ["", "Совет: можно отключить автозагрузку (страница «Автозагрузка»):"]
        lines += [f"  • {name}" for name in plan.startup_recommended]
    if result.errors:
        lines += ["", "Сообщения:"] + [f"  - {e}" for e in result.errors[:10]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
