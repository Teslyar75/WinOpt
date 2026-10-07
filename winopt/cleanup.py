"""Безопасная очистка временных файлов, кэшей браузеров и корзины.

Правила безопасности:
  * удаляются только файлы внутри заранее известных папок (temp, кэши);
  * в папках TEMP удаляются только файлы старше 24 часов
    (свежие могут использоваться установщиками прямо сейчас);
  * кэш браузера пропускается, если браузер открыт;
  * занятые файлы пропускаются, ошибки не прерывают очистку.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from winopt.recycle import empty_recycle_bin, query_recycle_bin
from winopt.winutil import format_size  # noqa: F401  (реэкспорт для старых импортов)

ALLOWED_LEAF_NAMES = {
    "temp",
    "tmp",
    "inetcache",
    "crashdumps",
    "reportarchive",
    "reportqueue",
    "cbs",
    "logs",
    "cache",
    "cache_data",
    "code cache",
    "gpucache",
    "cache2",
    "shadercache",
    "grshadercache",
    "graphitedawncache",
}


@dataclass(frozen=True)
class CleanupCategory:
    id: str
    label: str
    description: str
    paths: tuple[Path, ...]
    default_selected: bool = True
    min_age_hours: float = 0.0
    process_names: tuple[str, ...] = ()
    special: str = ""  # "recycle" — корзина
    group: str = "system"  # system | browser | other


@dataclass
class CategoryScan:
    category_id: str
    label: str
    description: str
    group: str = "system"
    paths: list[str] = field(default_factory=list)
    file_count: int = 0
    size_bytes: int = 0
    accessible: bool = True
    blocked_reason: str = ""
    default_selected: bool = True


@dataclass
class CleanupResult:
    freed_bytes: int = 0
    deleted_files: int = 0
    skipped_files: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_categories: list[str] = field(default_factory=list)


def _env_path(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else fallback


def _local() -> Path:
    return _env_path("LOCALAPPDATA", Path.home() / "AppData" / "Local")


def _roaming() -> Path:
    return _env_path("APPDATA", Path.home() / "AppData" / "Roaming")


def _windir() -> Path:
    return _env_path("WINDIR", Path(r"C:\Windows"))


def _unique(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


CHROMIUM_BROWSERS = (
    ("chrome", "Google Chrome", ("Google", "Chrome", "User Data"), ("chrome.exe",)),
    ("edge", "Microsoft Edge", ("Microsoft", "Edge", "User Data"), ("msedge.exe",)),
    ("yandex", "Яндекс Браузер", ("Yandex", "YandexBrowser", "User Data"), ("browser.exe",)),
    ("brave", "Brave", ("BraveSoftware", "Brave-Browser", "User Data"), ("brave.exe",)),
    ("vivaldi", "Vivaldi", ("Vivaldi", "User Data"), ("vivaldi.exe",)),
    ("opera", "Opera", ("Opera Software", "Opera Stable"), ("opera.exe",)),
    ("operagx", "Opera GX", ("Opera Software", "Opera GX Stable"), ("opera.exe",)),
)
CHROMIUM_CACHE_DIRS = ("Cache", "Code Cache", "GPUCache")
CHROMIUM_ROOT_CACHE_DIRS = ("ShaderCache", "GrShaderCache", "GraphiteDawnCache")


def _chromium_cache_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    found: list[Path] = []
    candidates = [root]
    try:
        for entry in os.scandir(root):
            if entry.is_dir() and (
                entry.name == "Default"
                or entry.name.startswith("Profile ")
                or entry.name in {"Guest Profile", "System Profile"}
            ):
                candidates.append(Path(entry.path))
    except OSError:
        pass
    for base in candidates:
        for name in CHROMIUM_CACHE_DIRS:
            path = base / name
            if path.is_dir():
                found.append(path)
    for name in CHROMIUM_ROOT_CACHE_DIRS:
        path = root / name
        if path.is_dir():
            found.append(path)
    return found


def _firefox_cache_paths() -> list[Path]:
    root = _local() / "Mozilla" / "Firefox" / "Profiles"
    if not root.exists():
        return []
    found = []
    try:
        for entry in os.scandir(root):
            cache = Path(entry.path) / "cache2"
            if cache.is_dir():
                found.append(cache)
    except OSError:
        pass
    return found


def list_categories() -> list[CleanupCategory]:
    local = _local()
    windir = _windir()
    temp_dirs = [_env_path(key, local / "Temp") for key in ("TEMP", "TMP")] + [local / "Temp"]

    categories = [
        CleanupCategory(
            id="user_temp",
            label="Временные файлы пользователя",
            description="Папки TEMP. Удаляются только файлы старше 24 часов.",
            paths=_unique(temp_dirs),
            min_age_hours=24,
        ),
        CleanupCategory(
            id="windows_temp",
            label="Временные файлы Windows",
            description="C:\\Windows\\Temp — файлы старше 24 часов. Без прав администратора очищается частично.",
            paths=(windir / "Temp",),
            min_age_hours=24,
        ),
        CleanupCategory(
            id="crash_dumps",
            label="Дампы сбоев и отчёты об ошибках",
            description="Файлы *.dmp и отчёты Windows Error Reporting после падений программ.",
            paths=_unique(
                [
                    local / "CrashDumps",
                    local / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                    local / "Microsoft" / "Windows" / "WER" / "ReportQueue",
                ]
            ),
        ),
        CleanupCategory(
            id="inet_cache",
            label="Кэш Internet Explorer / WinINet",
            description="Старый системный веб-кэш (используется некоторыми программами). Безопасно удалять.",
            paths=(local / "Microsoft" / "Windows" / "INetCache",),
            default_selected=False,
        ),
        CleanupCategory(
            id="windows_logs",
            label="Журналы установки Windows",
            description="Логи CBS и Windows Update. Нужны права администратора.",
            paths=(windir / "Logs" / "CBS", windir / "SoftwareDistribution" / "DataStore" / "Logs"),
            default_selected=False,
            min_age_hours=24,
        ),
    ]

    for cid, label, parts, procs in CHROMIUM_BROWSERS:
        base = local.joinpath(*parts)
        paths = _chromium_cache_paths(base)
        if cid.startswith("opera"):
            paths += _chromium_cache_paths(_roaming().joinpath(*parts))
        if not paths:
            continue
        categories.append(
            CleanupCategory(
                id=f"browser_{cid}",
                label=f"Кэш браузера {label}",
                description="Кэш страниц и шейдеров. Пароли, история и вкладки НЕ удаляются.",
                paths=_unique(paths),
                process_names=procs,
                group="browser",
            )
        )
    ff = _firefox_cache_paths()
    if ff:
        categories.append(
            CleanupCategory(
                id="browser_firefox",
                label="Кэш браузера Firefox",
                description="Кэш страниц. Пароли, история и вкладки НЕ удаляются.",
                paths=_unique(ff),
                process_names=("firefox.exe",),
                group="browser",
            )
        )

    categories.append(
        CleanupCategory(
            id="recycle_bin",
            label="Корзина",
            description="Окончательно удаляет файлы из корзины на всех дисках. Восстановить их будет нельзя.",
            paths=(),
            default_selected=False,
            special="recycle",
            group="other",
        )
    )
    return categories


def running_process_names() -> set[str]:
    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if name:
                names.add(name.casefold())
        except (psutil.Error, OSError):
            continue
    return names


def scan_categories(category_ids: list[str] | None = None, progress=None) -> list[CategoryScan]:
    selected = set(category_ids) if category_ids else None
    running = running_process_names()
    results: list[CategoryScan] = []
    for category in list_categories():
        if selected is not None and category.id not in selected:
            continue
        if progress:
            progress(f"Сканирую: {category.label}")
        scan = CategoryScan(
            category_id=category.id,
            label=category.label,
            description=category.description,
            group=category.group,
            default_selected=category.default_selected,
        )
        if category.special == "recycle":
            size, count = query_recycle_bin()
            scan.size_bytes, scan.file_count = size, count
            results.append(scan)
            continue
        busy = [p for p in category.process_names if p.casefold() in running]
        if busy:
            scan.blocked_reason = "браузер открыт — закройте его, чтобы очистить кэш"
        for path in category.paths:
            if not _is_safe_root(path) or not path.exists():
                continue
            scan.paths.append(str(path))
            count, size = _scan_tree(path, category.min_age_hours)
            scan.file_count += count
            scan.size_bytes += size
        if not scan.paths:
            scan.accessible = False
        results.append(scan)
    return results


def clean_categories(category_ids: list[str], progress=None) -> CleanupResult:
    result = CleanupResult()
    wanted = set(category_ids)
    running = running_process_names()
    for category in list_categories():
        if category.id not in wanted:
            continue
        if progress:
            progress(f"Очищаю: {category.label}")
        if category.special == "recycle":
            size, count = query_recycle_bin()
            try:
                empty_recycle_bin()
                result.freed_bytes += size
                result.deleted_files += count
            except Exception as exc:  # noqa: BLE001
                result.errors.append(str(exc))
            continue
        if any(p.casefold() in running for p in category.process_names):
            result.skipped_categories.append(f"{category.label} (браузер открыт)")
            continue
        for path in category.paths:
            if not _is_safe_root(path) or not path.exists():
                continue
            deleted, skipped, freed, errors = _clean_tree(path, category.min_age_hours)
            result.deleted_files += deleted
            result.skipped_files += skipped
            result.freed_bytes += freed
            result.errors.extend(errors[: max(0, 10 - len(result.errors))])
    return result


def format_scan(results: list[CategoryScan]) -> str:
    lines = ["=== Временные файлы и кэши ===", ""]
    total = 0
    for item in results:
        lines.append(f"{item.label}: {format_size(item.size_bytes)} ({item.file_count} файлов)")
        if item.description:
            lines.append(f"  {item.description}")
        if item.blocked_reason:
            lines.append(f"  ! {item.blocked_reason}")
        lines.append("")
        total += item.size_bytes
    lines.append(f"Итого можно освободить: {format_size(total)}")
    return "\n".join(lines)


def _too_new(mtime: float, min_age_hours: float, now: float) -> bool:
    return min_age_hours > 0 and (now - mtime) < min_age_hours * 3600


def _scan_tree(root: Path, min_age_hours: float = 0.0) -> tuple[int, int]:
    count = 0
    size = 0
    now = time.time()
    try:
        for dirpath, _dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            for name in filenames:
                try:
                    st = os.stat(os.path.join(dirpath, name), follow_symlinks=False)
                except OSError:
                    continue
                if _too_new(st.st_mtime, min_age_hours, now):
                    continue
                size += st.st_size
                count += 1
    except OSError:
        pass
    return count, size


def _clean_tree(root: Path, min_age_hours: float = 0.0) -> tuple[int, int, int, list[str]]:
    deleted = skipped = freed = 0
    errors: list[str] = []
    now = time.time()
    empty_dirs: list[str] = []
    try:
        for dirpath, _dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path, follow_symlinks=False)
                    if _too_new(st.st_mtime, min_age_hours, now):
                        continue
                    os.unlink(path)
                    deleted += 1
                    freed += st.st_size
                except OSError as exc:
                    skipped += 1
                    if len(errors) < 5:
                        errors.append(f"{name}: {exc.strerror or exc}")
            if os.path.normcase(dirpath) != os.path.normcase(str(root)):
                empty_dirs.append(dirpath)
    except OSError as exc:
        errors.append(f"{root}: {exc}")
    for folder in empty_dirs:
        try:
            os.rmdir(folder)  # удаляется только если папка пуста
        except OSError:
            continue
    return deleted, skipped, freed, errors


def _is_safe_root(path: Path) -> bool:
    """Разрешаем удаление только внутри известных временных/кэш-папок."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    text = str(resolved).casefold().replace("/", "\\")
    if len(text) < 8 or resolved.name.casefold() not in ALLOWED_LEAF_NAMES:
        return False
    bases = [_local(), _roaming(), _windir() / "Temp", _windir() / "Logs", _windir() / "SoftwareDistribution"]
    for key in ("TEMP", "TMP"):
        raw = os.environ.get(key)
        if raw:
            bases.append(Path(raw))
    for base in bases:
        try:
            base_text = str(base.resolve()).casefold().replace("/", "\\")
        except OSError:
            base_text = str(base).casefold()
        if text == base_text or text.startswith(base_text.rstrip("\\") + "\\"):
            return True
    return False
