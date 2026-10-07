"""Точки восстановления Windows."""

from __future__ import annotations

from winopt.winutil import run_powershell

import json
from dataclasses import dataclass

_CHECK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$enabled = $false
try {
    $key = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' -ErrorAction Stop
    if ($key.RPSessionInterval -ne 0) { $enabled = $true }
} catch {}
[pscustomobject]@{
    Enabled = $enabled
} | ConvertTo-Json -Compress
"""

_CREATE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Checkpoint-Computer -Description $env:WINOPT_DESC -RestorePointType MODIFY_SETTINGS
'ok'
"""


@dataclass(frozen=True)
class RestoreStatus:
    enabled: bool


def get_restore_status() -> RestoreStatus:
    completed = run_powershell(_CHECK_SCRIPT, None, timeout=30)
    if completed.returncode != 0:
        return RestoreStatus(enabled=False)
    data = json.loads(completed.stdout.strip() or "{}")
    return RestoreStatus(enabled=bool(data.get("Enabled")))


def create_restore_point(description: str = "WinOpt — перед изменениями") -> None:
    completed = run_powershell(_CREATE_SCRIPT, { "WINOPT_DESC": description}, timeout=120)
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        if "access" in err.casefold() or "privilege" in err.casefold() or "authorized" in err.casefold():
            raise PermissionError(
                "Нужны права администратора и включённое восстановление системы."
            )
        if "frequency" in err.casefold() or "221" in err:
            raise RuntimeError(
                "Windows не создаёт точки слишком часто. Подождите или используйте последнюю точку."
            )
        raise RuntimeError(err or "Не удалось создать точку восстановления")


def create_restore_point_elevated(description: str = "WinOpt — перед удалением программ", timeout: int = 300) -> str:
    """Создать точку восстановления через отдельный PowerShell с правами администратора.

    Windows покажет окно UAC. Возвращает понятный итог; бросает исключение при ошибке/отказе.
    """
    import base64
    import os
    import tempfile
    import time
    from pathlib import Path

    from winopt.winutil import shell_execute

    out = Path(tempfile.gettempdir()) / f"winopt_rp_{os.getpid()}_{int(time.time())}.txt"
    desc = description.replace("'", "")
    target = str(out).replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        f"try {{ Checkpoint-Computer -Description '{desc}' -RestorePointType APPLICATION_UNINSTALL -WarningVariable w -WarningAction SilentlyContinue;"
        f" if ($w) {{ 'WARN ' + ($w -join ' ') | Out-File -LiteralPath '{target}' -Encoding utf8 }} else {{ 'OK' | Out-File -LiteralPath '{target}' -Encoding utf8 }}; exit 0 }}"
        f" catch {{ 'ERR ' + $_.Exception.Message | Out-File -LiteralPath '{target}' -Encoding utf8; exit 1 }}"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    handle = shell_execute("powershell.exe", f"-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {encoded}", elevate=True, show=0)
    try:
        handle.wait(timeout * 1000)
    finally:
        handle.close()
    text = ""
    for _ in range(10):
        if out.exists():
            text = out.read_text(encoding="utf-8-sig", errors="replace").strip()
            break
        time.sleep(0.3)
    try:
        out.unlink()
    except OSError:
        pass
    if text.startswith("OK"):
        return "Точка восстановления создана."
    if text.startswith("WARN"):
        return "Windows не создала новую точку (не чаще раза в сутки) — будет использована последняя."
    raise RuntimeError(text[4:] if text.startswith("ERR") else "Не удалось создать точку восстановления")
