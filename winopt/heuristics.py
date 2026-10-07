"""Эвристики подозрительных процессов. Это не антивирус."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SUSPICIOUS_DIR_MARKERS = (
    "\\temp\\",
    "\\tmp\\",
    "\\downloads\\",
    "\\recycle.bin\\",
    "\\appdata\\local\\temp\\",
    "\\appdata\\roaming\\temp\\",
    "\\users\\public\\",
)

SYSTEM_IMPERSONATORS = {
    "svchost.exe": (r"\windows\system32\svchost.exe", r"\windows\syswow64\svchost.exe"),
    "lsass.exe": (r"\windows\system32\lsass.exe",),
    "csrss.exe": (r"\windows\system32\csrss.exe",),
    "winlogon.exe": (r"\windows\system32\winlogon.exe",),
    "services.exe": (r"\windows\system32\services.exe",),
    "smss.exe": (r"\windows\system32\smss.exe",),
    "wininit.exe": (r"\windows\system32\wininit.exe",),
    "explorer.exe": (r"\windows\explorer.exe",),
    "runtimebroker.exe": (r"\windows\system32\runtimebroker.exe",),
    "taskhostw.exe": (r"\windows\system32\taskhostw.exe",),
    "sihost.exe": (r"\windows\system32\sihost.exe",),
    "fontdrvhost.exe": (r"\windows\system32\fontdrvhost.exe",),
    "dwm.exe": (r"\windows\system32\dwm.exe",),
    "conhost.exe": (r"\windows\system32\conhost.exe",),
}

TYPOSQUAT_NAMES = {
    "svhost.exe",
    "scvhost.exe",
    "svch0st.exe",
    "lssass.exe",
    "lsas.exe",
    "expl0rer.exe",
    "explorer.com",
    "csrsss.exe",
    "winlog0n.exe",
}

KERNEL_PROCESS_NAMES = {
    "system",
    "idle",
    "registry",
    "memcompression",
    "secure system",
    "memory compression",
}


@dataclass(frozen=True)
class Finding:
    code: str
    points: int
    message: str


def evaluate_process(proc) -> list[Finding]:
    findings: list[Finding] = []
    name = (proc.name or "").casefold()
    exe = (proc.exe or "").replace("/", "\\")
    exe_l = exe.casefold()
    meta = proc.meta

    if name in TYPOSQUAT_NAMES:
        findings.append(
            Finding(
                "typosquat",
                80,
                f"Имя похоже на системный процесс, но это известный вариант подделки: {proc.name}",
            )
        )

    if name in KERNEL_PROCESS_NAMES or getattr(proc, "pid", 0) in {0, 4}:
        return findings

    if getattr(proc, "access_denied", False) or not name:
        return findings

    if not exe:
        findings.append(Finding("no_path", 45, "Нет пути к исполняемому файлу"))
    elif "\\" not in exe and "/" not in exe:
        return findings
    elif meta and not meta.exists:
        findings.append(Finding("missing_file", 70, "Файл процесса отсутствует на диске"))

    if exe_l:
        for marker in SUSPICIOUS_DIR_MARKERS:
            if marker in exe_l:
                findings.append(
                    Finding("temp_path", 40, f"Запущен из подозрительной папки: {exe}")
                )
                break

    expected = SYSTEM_IMPERSONATORS.get(name)
    if expected and exe_l:
        if not any(exe_l.endswith(path) for path in expected):
            findings.append(
                Finding(
                    "fake_system",
                    75,
                    f"{proc.name} должен быть в системной папке Windows, а не здесь: {exe}",
                )
            )

    store_app = _looks_store_app(exe_l)
    if meta and not store_app:
        status = meta.signature_status.lower()
        if meta.hash_mismatch:
            findings.append(Finding("hash_mismatch", 90, "Цифровая подпись файла повреждена (HashMismatch)"))
        elif status in {"notsigned", "nottrusted", "unknownerror", "error"}:
            if _looks_user_or_temp(exe_l):
                findings.append(
                    Finding(
                        "unsigned",
                        35,
                        f"Нет доверенной подписи ({meta.signature_status})",
                    )
                )
        if not meta.company and not meta.description and exe and meta.exists:
            if _looks_user_or_temp(exe_l):
                findings.append(Finding("no_version_info", 15, "У файла нет CompanyName/Description"))

    if proc.cpu_percent >= 25:
        findings.append(
            Finding("high_cpu", 10, f"Высокая загрузка CPU: {proc.cpu_percent:.1f}%")
        )
    if proc.memory_mb >= 700 and not _looks_windows_dir(exe_l):
        findings.append(
            Finding("high_ram", 8, f"Много памяти: {proc.memory_mb:.0f} МБ")
        )

    return findings


def _looks_windows_dir(path: str) -> bool:
    windir = os.environ.get("WINDIR", r"C:\Windows").casefold().replace("/", "\\")
    normalized = path.replace("/", "\\")
    return (
        normalized.startswith(windir)
        or "\\windows\\system32\\" in normalized
        or "\\windows\\syswow64\\" in normalized
    )


def _looks_store_app(path: str) -> bool:
    return "\\windowsapps\\" in path or "\\systemapps\\" in path


def _looks_user_or_temp(path: str) -> bool:
    home = str(Path.home()).casefold().replace("/", "\\")
    return home in path or "\\appdata\\" in path or "\\temp\\" in path or "\\downloads\\" in path


def score_level(score: int) -> str:
    if score >= 60:
        return "подозрительно"
    if score >= 25:
        return "внимание"
    return "норма"
