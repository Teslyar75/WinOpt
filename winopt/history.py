"""Журнал действий программы (история изменений).

Каждое изменение системы (очистка, отключение автозагрузки, изменение
службы, удаление файлов в корзину и т.д.) записывается одной строкой JSON
в %LOCALAPPDATA%\\WinOpt\\history.jsonl. Журнал виден на странице «Журнал».
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from winopt.winutil import data_dir

_LOCK = threading.Lock()
MAX_LINES = 2000


@dataclass(frozen=True)
class HistoryEntry:
    time: str
    category: str
    action: str
    details: str
    ok: bool


def history_path() -> Path:
    return data_dir() / "history.jsonl"


def log_action(category: str, action: str, details: str = "", ok: bool = True) -> None:
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "category": category,
        "action": action,
        "details": details,
        "ok": ok,
    }
    try:
        with _LOCK:
            path = history_path()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            _trim(path)
    except OSError:
        pass


def read_history(limit: int = 500) -> list[HistoryEntry]:
    path = history_path()
    if not path.exists():
        return []
    entries: list[HistoryEntry] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines[-limit:]):
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        entries.append(
            HistoryEntry(
                time=str(raw.get("time", "")),
                category=str(raw.get("category", "")),
                action=str(raw.get("action", "")),
                details=str(raw.get("details", "")),
                ok=bool(raw.get("ok", True)),
            )
        )
    return entries


def clear_history() -> None:
    with _LOCK:
        path = history_path()
        if path.exists():
            path.unlink()


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > MAX_LINES:
        path.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
