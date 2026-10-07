"""Поиск повторяющихся файлов и удаление лишних копий в корзину."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from winopt.recycle import RecycleResult, send_to_recycle_bin
from winopt.winutil import format_size

SKIP_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "appdata",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
}

DEFAULT_MIN_SIZE = 256 * 1024  # 256 КБ — мелкие файлы почти не влияют на место
PARTIAL_BYTES = 64 * 1024


@dataclass(frozen=True)
class DuplicateFile:
    path: str
    size_bytes: int
    mtime: float


@dataclass
class DuplicateGroup:
    file_hash: str
    size_bytes: int
    files: list[DuplicateFile] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        if len(self.files) < 2:
            return 0
        return self.size_bytes * (len(self.files) - 1)

    @property
    def keep(self) -> DuplicateFile:
        """Файл, который предлагается оставить: самый старый (оригинал)."""
        return self.files[0]


@dataclass
class DuplicateScanResult:
    groups: list[DuplicateGroup]
    scanned_files: int
    scanned_bytes: int
    roots: list[str]


def default_scan_roots() -> list[Path]:
    home = Path.home()
    onedrive = os.environ.get("OneDrive")
    candidates = [home / name for name in ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music")]
    if onedrive:
        od = Path(onedrive)
        candidates += [od / name for name in ("Downloads", "Documents", "Desktop", "Pictures", "Videos")]
    roots: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = str(path.resolve()).casefold()
        except OSError:
            resolved = str(path).casefold()
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        roots.append(path)
    return roots


def scan_duplicates(
    roots: list[Path] | None = None,
    min_size_bytes: int = DEFAULT_MIN_SIZE,
    progress=None,
    cancel=None,
) -> DuplicateScanResult:
    scan_roots = roots or default_scan_roots()
    by_size: dict[int, list[Path]] = {}
    scanned_files = 0
    scanned_bytes = 0

    for root in scan_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            if cancel and cancel():
                break
            dirnames[:] = [d for d in dirnames if d.casefold() not in SKIP_DIR_NAMES and not d.startswith("$")]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                if st.st_size < min_size_bytes:
                    continue
                scanned_files += 1
                scanned_bytes += st.st_size
                by_size.setdefault(st.st_size, []).append(path)
                if progress and scanned_files % 500 == 0:
                    progress(f"Просмотрено файлов: {scanned_files}")

    # Шаг 1: быстрый хеш первых 64 КБ, шаг 2: полный хеш только у совпавших.
    candidates = [(size, paths) for size, paths in by_size.items() if len(paths) > 1]
    groups: list[DuplicateGroup] = []
    total = sum(len(p) for _s, p in candidates)
    checked = 0
    for size, paths in candidates:
        if cancel and cancel():
            break
        partial: dict[str, list[Path]] = {}
        for path in paths:
            digest = _file_hash(path, limit=PARTIAL_BYTES)
            checked += 1
            if digest:
                partial.setdefault(digest, []).append(path)
            if progress and checked % 50 == 0:
                progress(f"Сравниваю файлы: {checked} из {total}")
        for same in partial.values():
            if len(same) < 2:
                continue
            full: dict[str, list[DuplicateFile]] = {}
            for path in same:
                digest = _file_hash(path) if size > PARTIAL_BYTES else _file_hash(path, limit=PARTIAL_BYTES)
                if not digest:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                full.setdefault(digest, []).append(DuplicateFile(str(path), size, mtime))
            for digest, files in full.items():
                if len(files) > 1:
                    files.sort(key=lambda f: (f.mtime, len(f.path)))
                    groups.append(DuplicateGroup(file_hash=digest, size_bytes=size, files=files))

    groups.sort(key=lambda g: g.reclaimable_bytes, reverse=True)
    return DuplicateScanResult(groups, scanned_files, scanned_bytes, [str(p) for p in scan_roots])


def delete_files(paths: list[str]) -> RecycleResult:
    """Переместить выбранные файлы в корзину (не безвозвратно)."""
    return send_to_recycle_bin(paths)


def format_duplicate_report(result: DuplicateScanResult) -> str:
    reclaim = sum(g.reclaimable_bytes for g in result.groups)
    lines = [
        "=== Повторяющиеся файлы ===",
        "",
        f"Папки: {', '.join(result.roots)}",
        f"Просмотрено файлов: {result.scanned_files} ({format_size(result.scanned_bytes)})",
        f"Групп дубликатов: {len(result.groups)}",
        f"Можно освободить (если оставить по 1 копии): {format_size(reclaim)}",
        "",
    ]
    for index, group in enumerate(result.groups[:40], start=1):
        lines.append(f"Группа {index}: {format_size(group.size_bytes)} x {len(group.files)} копий")
        for n, item in enumerate(group.files):
            lines.append(f"  {'[оставить] ' if n == 0 else ''}{item.path}")
        lines.append("")
    if len(result.groups) > 40:
        lines.append(f"… и ещё {len(result.groups) - 40} групп")
    return "\n".join(lines)


def _file_hash(path: Path, block_size: int = 1024 * 1024, limit: int | None = None) -> str:
    digest = hashlib.blake2b(digest_size=20)
    read = 0
    try:
        with path.open("rb") as handle:
            while True:
                want = block_size if limit is None else min(block_size, limit - read)
                if want <= 0:
                    break
                chunk = handle.read(want)
                if not chunk:
                    break
                digest.update(chunk)
                read += len(chunk)
    except OSError:
        return ""
    return digest.hexdigest()
