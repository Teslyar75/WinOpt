"""Диски: обзор разделов, крупнейшие папки и поиск больших файлов."""

from __future__ import annotations

import os
import stat as stat_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import psutil

from winopt.winutil import format_size

MAX_FILES_PER_FOLDER = 150_000

SKIP_FOLDER_NAMES = {
    "$recycle.bin",
    "system volume information",
    "recovery",
    "$windows.~bt",
    "$windows.~ws",
    "$winreagent",
    "config.msi",
}

# Папки, файлы в которых нельзя предлагать удалять: системные и программные.
LARGE_FILES_SKIP = SKIP_FOLDER_NAMES | {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "appdata",
    "windowsapps",
    "node_modules",
    ".git",
}


@dataclass(frozen=True)
class DiskInfo:
    drive: str
    label: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / 1024**3, 1)

    @property
    def free_gb(self) -> float:
        return round(self.free_bytes / 1024**3, 1)

    @property
    def used_gb(self) -> float:
        return round(self.used_bytes / 1024**3, 1)


@dataclass(frozen=True)
class FolderUsage:
    path: str
    size_bytes: int
    label: str = ""
    file_count: int = 0
    partial: bool = False


@dataclass(frozen=True)
class LargeFile:
    path: str
    size_bytes: int
    mtime: float
    extension: str


def list_drives() -> list[DiskInfo]:
    disks: list[DiskInfo] = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts.lower() or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        drive = part.mountpoint.rstrip("\\")
        disks.append(
            DiskInfo(
                drive=drive,
                label=_volume_label(part.mountpoint),
                fstype=part.fstype,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                used_percent=round(usage.percent, 1),
            )
        )
    disks.sort(key=lambda d: (not d.drive.upper().startswith("C"), d.drive))
    return disks


def system_drive() -> str:
    return os.environ.get("SystemDrive", "C:") + "\\"


def scan_largest_folders(
    drive: str | None = None,
    limit: int = 40,
    min_size_mb: int = 100,
    progress=None,
    cancel=None,
) -> list[FolderUsage]:
    """Крупнейшие папки диска. Профиль текущего пользователя раскрывается глубже,
    чтобы было видно, что именно занимает место (Загрузки, AppData\\Local\\…)."""
    root = Path(drive or system_drive())
    home = Path.home()
    targets: list[Path] = []

    for entry in _safe_scandir(root):
        if not _is_dir(entry) or entry.name.casefold() in SKIP_FOLDER_NAMES:
            continue
        path = Path(entry.path)
        if path.name.casefold() == "users" and _same_drive(home, root):
            for user_entry in _safe_scandir(path):
                if not _is_dir(user_entry):
                    continue
                user_path = Path(user_entry.path)
                if _same_path(user_path, home):
                    targets.extend(_expand_home(home))
                else:
                    targets.append(user_path)
            continue
        targets.append(path)

    min_bytes = min_size_mb * 1024 * 1024
    results: list[FolderUsage] = []
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_folder_size, path, cancel): path for path in targets}
        for future in as_completed(futures):
            path = futures[future]
            done += 1
            if progress:
                progress(f"Папки: {done} из {len(targets)} — {path.name}")
            try:
                size, count, partial = future.result()
            except OSError:
                continue
            if size >= min_bytes:
                results.append(FolderUsage(str(path), size, path.name, count, partial))
    results.sort(key=lambda item: item.size_bytes, reverse=True)
    return results[:limit]


def default_large_file_roots() -> list[Path]:
    roots = [Path.home()]
    sys_drive = system_drive().casefold()
    for disk in list_drives():
        mount = disk.drive + "\\"
        if mount.casefold() != sys_drive:
            roots.append(Path(mount))
    return roots


def find_large_files(
    roots: list[Path] | None = None,
    min_size_mb: int = 250,
    limit: int = 300,
    progress=None,
    cancel=None,
) -> list[LargeFile]:
    min_bytes = min_size_mb * 1024 * 1024
    found: list[LargeFile] = []
    seen_files = 0
    for root in roots or default_large_file_roots():
        stack = [root]
        while stack:
            if cancel and cancel():
                return _top(found, limit)
            current = stack.pop()
            for entry in _safe_scandir(current):
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        name = entry.name.casefold()
                        if name in LARGE_FILES_SKIP or name.startswith("$"):
                            continue
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        seen_files += 1
                        st = entry.stat(follow_symlinks=False)
                        if st.st_size >= min_bytes and not _is_system_file(st):
                            found.append(
                                LargeFile(entry.path, st.st_size, st.st_mtime, Path(entry.name).suffix.lower())
                            )
                        if progress and seen_files % 2000 == 0:
                            progress(f"Просмотрено файлов: {seen_files}, найдено больших: {len(found)}")
                except OSError:
                    continue
    return _top(found, limit)


def format_disk_report(items: list[FolderUsage]) -> str:
    lines = ["=== Крупнейшие папки ===", ""]
    if not items:
        lines.append("Крупные папки (от 100 МБ) не найдены или доступ ограничен.")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        mark = " (подсчёт неполный)" if item.partial else ""
        lines.append(f"{index:2d}. {format_size(item.size_bytes):>10}  {item.path}{mark}")
    return "\n".join(lines)


def _top(found: list[LargeFile], limit: int) -> list[LargeFile]:
    found.sort(key=lambda f: f.size_bytes, reverse=True)
    return found[:limit]


def _expand_home(home: Path) -> list[Path]:
    result: list[Path] = []
    for entry in _safe_scandir(home):
        if not _is_dir(entry):
            continue
        path = Path(entry.path)
        if entry.name.casefold() == "appdata":
            for sub in ("Local", "Roaming", "LocalLow"):
                sub_path = path / sub
                for inner in _safe_scandir(sub_path):
                    if _is_dir(inner):
                        result.append(Path(inner.path))
        else:
            result.append(path)
    return result


def _folder_size(root: Path, cancel=None) -> tuple[int, int, bool]:
    total = 0
    count = 0
    stack = [root]
    while stack:
        if cancel and cancel():
            return total, count, True
        current = stack.pop()
        for entry in _safe_scandir(current):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                    count += 1
                    if count > MAX_FILES_PER_FOLDER:
                        return total, count, True
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
            except OSError:
                continue
    return total, count, False


def _is_system_file(st) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat_mod, "FILE_ATTRIBUTE_SYSTEM", 0x4))


def _is_dir(entry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False) and not entry.is_symlink()
    except OSError:
        return False


def _safe_scandir(path: Path):
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


def _same_drive(a: Path, b: Path) -> bool:
    return a.drive.casefold() == b.drive.casefold()


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _volume_label(mount: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(mount, buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:
        return ""
