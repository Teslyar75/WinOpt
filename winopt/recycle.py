"""Корзина Windows: удаление в корзину, размер корзины, очистка корзины."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from winopt.winutil import IS_WINDOWS

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000

SHERB_NOCONFIRMATION = 0x1
SHERB_NOPROGRESSUI = 0x2
SHERB_NOSOUND = 0x4


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


@dataclass
class RecycleResult:
    moved_files: int = 0
    moved_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def send_to_recycle_bin(paths: list[str]) -> RecycleResult:
    """Переместить файлы в корзину (их можно будет восстановить)."""
    result = RecycleResult()
    if not IS_WINDOWS:
        result.errors.append("Корзина доступна только в Windows")
        return result
    for raw in paths:
        path = Path(raw)
        try:
            size = path.stat().st_size
        except OSError as exc:
            result.errors.append(f"{raw}: {exc}")
            continue
        op = _SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = str(path.resolve()) + "\0\0"
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc == 0 and not op.fAnyOperationsAborted and not path.exists():
            result.moved_files += 1
            result.moved_bytes += size
        else:
            result.errors.append(f"{raw}: не удалось переместить в корзину (код {rc})")
    return result


def query_recycle_bin() -> tuple[int, int]:
    """Вернуть (размер в байтах, количество объектов) во всех корзинах."""
    if not IS_WINDOWS:
        return 0, 0
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
    rc = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if rc != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin() -> None:
    """Очистить корзину на всех дисках (без диалога Windows — подтверждение спрашивает программа)."""
    if not IS_WINDOWS:
        raise RuntimeError("Корзина доступна только в Windows")
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    rc &= 0xFFFFFFFF
    # 0x8000FFFF (E_UNEXPECTED) Windows возвращает, если корзина уже пуста.
    if rc not in (0, 0x8000FFFF):
        raise RuntimeError(f"Не удалось очистить корзину (код 0x{rc:08X})")
