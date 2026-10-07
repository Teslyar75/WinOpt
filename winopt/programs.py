"""Установленные программы: обычные (реестр) и приложения Магазина (AppX).

Удаление выполняется только по явной команде пользователя (галочки + кнопка
+ подтверждение) и только для отмеченных пунктов: у обычных программ
запускается их собственный деинсталлятор, приложения Магазина удаляются
командой Remove-AppxPackage для текущего пользователя.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from winopt.winutil import IS_WINDOWS, data_dir, run_powershell

_PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$sources = @(
    @{ Path = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'; Hive = 'HKLM' },
    @{ Path = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'; Hive = 'HKLM-WOW' },
    @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'; Hive = 'HKCU' }
)
$items = New-Object System.Collections.ArrayList
foreach ($src in $sources) {
    Get-ItemProperty $src.Path | Where-Object { $_.DisplayName } | ForEach-Object {
        [void]$items.Add([pscustomobject]@{
            Source = 'win32'
            Hive = $src.Hive
            Key = [string]$_.PSChildName
            Name = [string]$_.DisplayName
            Publisher = [string]$_.Publisher
            Version = [string]$_.DisplayVersion
            InstallDate = [string]$_.InstallDate
            EstimatedSizeMB = if ($_.EstimatedSize) { [double]$_.EstimatedSize / 1024 } else { 0 }
            Uninstall = [string]$_.UninstallString
            QuietUninstall = [string]$_.QuietUninstallString
            Location = [string]$_.InstallLocation
            SystemComponent = [string]$_.SystemComponent
            Parent = [string]$_.ParentKeyName
            NoRemove = [string]$_.NoRemove
        })
    }
}
$start = @{}
try { Get-StartApps | ForEach-Object { $pfn = ($_.AppID -split '!')[0]; if (-not $start.ContainsKey($pfn)) { $start[$pfn] = $_.Name } } } catch {}
try {
    Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.IsResourcePackage -and $_.SignatureKind -ne 'System' } | ForEach-Object {
        $date = ''
        try { if ($_.InstallLocation) { $date = (Get-Item -LiteralPath $_.InstallLocation).LastWriteTime.ToString('yyyyMMdd') } } catch {}
        [void]$items.Add([pscustomobject]@{
            Source = 'appx'
            Hive = 'User'
            Key = [string]$_.PackageFamilyName
            Name = [string]$_.Name
            Friendly = [string]$start[$_.PackageFamilyName]
            FullName = [string]$_.PackageFullName
            Publisher = [string]$_.Publisher
            Version = [string]$_.Version
            InstallDate = $date
            EstimatedSizeMB = 0
            Location = [string]$_.InstallLocation
            NonRemovable = [bool]$_.NonRemovable
            Signature = [string]$_.SignatureKind
        })
    }
} catch {}
$json = if ($items.Count -eq 0) { '[]' } else { @($items) | ConvertTo-Json -Compress -Depth 4 }
[System.IO.File]::WriteAllText($env:WINOPT_OUT, $json, [System.Text.UTF8Encoding]::new($false))
"""

REVIEW_LABELS = {"A": "лишнее", "B": "на ваше усмотрение"}


@dataclass
class InstalledProgram:
    name: str
    publisher: str
    version: str
    install_date: str
    size_mb: float
    uninstall: str
    location: str
    flags: tuple[str, ...] = ()
    install_sort: str = ""  # ГГГГММДД — для правильной сортировки по дате
    source: str = "win32"  # win32 | appx
    hive: str = ""  # HKLM | HKLM-WOW | HKCU | User
    key: str = ""  # имя раздела реестра или PackageFamilyName
    quiet_uninstall: str = ""
    package_name: str = ""  # AppX: Name пакета (Microsoft.BingNews)
    package_full_name: str = ""  # AppX: PackageFullName
    system_component: bool = False
    non_removable: bool = False
    review: str = ""  # A / B / C из обзора программ
    review_reason: str = ""
    lock_reason: str = ""  # почему удалять из WinOpt нельзя (пусто — можно)

    @property
    def uid(self) -> str:
        return f"{self.source}|{self.hive}|{self.key or self.name}"

    @property
    def sort_size(self) -> float:
        return self.size_mb

    @property
    def is_store(self) -> bool:
        return self.source == "appx"

    @property
    def locked(self) -> bool:
        return bool(self.lock_reason)

    @property
    def needs_admin(self) -> bool:
        return self.source == "win32" and self.hive.startswith("HKLM")

    @property
    def kind_label(self) -> str:
        return "Магазин" if self.is_store else "Программа"

    def uninstall_command(self) -> str:
        """Команда удаления: QuietUninstallString, если есть, иначе UninstallString (MSI: /I → /X)."""
        command = (self.quiet_uninstall or self.uninstall).strip()
        if "msiexec" in command.casefold():
            command = re.sub(r"(?i)/I\s*(\{)", r"/X\1", command)
        return command


# --- Обзор программ (категории A/B/C) ---------------------------------------------


def review_csv_candidates() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    return [data_dir() / "programs-review.csv", root / "data" / "programs-review.csv"]


def load_review(path: Path | None = None) -> dict[tuple[str, str], tuple[str, str, float]]:
    """Ключ (source, ключ реестра/PFN или имя в нижнем регистре) → (категория, причина, размер МБ)."""
    paths = [path] if path else review_csv_candidates()
    for candidate in paths:
        if candidate and candidate.is_file():
            break
    else:
        return {}
    result: dict[tuple[str, str], tuple[str, str, float]] = {}
    with open(candidate, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cat = (row.get("Category") or "").strip().upper()
            if not cat:
                continue
            source = "appx" if (row.get("Source") or "").strip().lower() == "appx" else "win32"
            reason = (row.get("Reason") or "").strip()
            try:
                size = float((row.get("SizeMB") or "0").replace(",", "."))
            except ValueError:
                size = 0.0
            for ident in ((row.get("KeyName") or "").strip(), (row.get("Name") or "").strip()):
                if ident:
                    result.setdefault((source, ident.casefold()), (cat, reason, size))
    return result


# --- Что блокируется ---------------------------------------------------------------

_LOCK_RULES: list[tuple[str, re.Pattern]] = [
    ("драйвер устройства", re.compile(r"driver|драйвер|whql|\bgraphics\b|radeon|realtek|synaptics|chipset|dolby|nvidia virtual audio|amdradeonsoftware|synapticsincorporated", re.I)),
    ("Visual C++ — нужен многим программам", re.compile(r"visual c\+\+|vc_?redist|vcredist", re.I)),
    (".NET — нужен программам (в т.ч. Perry)", re.compile(r"\.net\b|asp\.net|dotnet|desktop runtime|targeting pack|\bworkload\b|\.net\.sdk|microsoft\.net\.", re.I)),
    ("Docker / WSL — нужны для разработки", re.compile(r"docker|subsystem for linux|subsystemforlinux|\bwsl\b", re.I)),
    ("защита компьютера", re.compile(r"defender|antivirus|anti-virus|kaspersky|\beset\b|avast|\bavg\b|malwarebytes|norton|mcafee|bitdefender|dr\.?web|sechealthui|windows security|\bsecurity\b", re.I)),
    ("основной Python — на нём работает WinOpt", re.compile(r"^python 3\.14\.3|^python launcher|pythonsoftwarefoundation\.pythonmanager", re.I)),
    ("рабочий инструмент (Cursor)", re.compile(r"^cursor$", re.I)),
    ("рабочий инструмент (Git)", re.compile(r"^git$|^git version", re.I)),
    ("рабочий инструмент (Node.js)", re.compile(r"^node\.?js", re.I)),
    ("через него работает ассистент", re.compile(r"^grok bot", re.I)),
    ("компонент Windows", re.compile(
        r"^update for |\(kb\d+\)|microsoft update health tools|application compatibility|windows sdk|^microsoft edge$|webview2"
        r"|^microsoft\.(windowsstore|desktopappinstaller|storepurchaseapp|winget\.source|microsoftedge\.stable|applicationcompatibilityenhancements"
        r"|widgetsplatformruntime|xbox\.tcui|xboxidentityprovider|startexperiencesapp)$"
        r"|^microsoft\.languageexperiencepack|^microsoftcorporationii\.winappruntime|^microsoftwindows\.client\.webexperience$"
        r"|^microsoft\.\w+(image|video)extension(s|firstparty)?$|^microsoft\.webmediaextensions$", re.I)),
]

# Встроенные приложения Windows: блокируются, если обзор не отметил их как A/B.
_SOFT_COMPONENTS = re.compile(
    r"^microsoft\.(windowsnotepad|windowscalculator|windows\.photos|paint|screensketch|windowsterminal|powershell|windowscamera)$", re.I)


def lock_reason_for(prog: InstalledProgram) -> str:
    """Почему пункт нельзя отметить к удалению ('' — можно)."""
    texts = [prog.name, prog.package_name, prog.key if prog.is_store else ""]
    for reason, pattern in _LOCK_RULES:
        if any(t and pattern.search(t) for t in texts):
            return reason
    if prog.is_store:
        if prog.non_removable:
            return "системный пакет Windows"
        if prog.review not in ("A", "B") and _SOFT_COMPONENTS.search(prog.package_name or ""):
            return "встроенное приложение Windows"
        return ""
    if prog.system_component:
        return "часть другой программы"
    if not prog.uninstall_command():
        return "нет команды удаления"
    return ""


# --- Чтение списка ----------------------------------------------------------------


def list_programs(review: dict | None = None) -> list[InstalledProgram]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="winopt_") as tmp:
        out_file = Path(tmp) / "programs.json"
        completed = run_powershell(_PS_SCRIPT, {"WINOPT_OUT": str(out_file)}, timeout=120)
        payload = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
    if not payload:
        err = (completed.stderr or completed.stdout or "не удалось прочитать программы").strip()
        raise RuntimeError(err)
    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]
    return parse_programs(data, load_review() if review is None else review)


def parse_programs(data: list[dict], review: dict) -> list[InstalledProgram]:
    """Превратить сырые записи (из PowerShell) в список программ с категориями и блокировками."""
    result: list[InstalledProgram] = []
    seen: set[str] = set()
    for raw in data:
        source = str(raw.get("Source") or "win32").lower()
        name = str(raw.get("Name") or "").strip()
        if not name:
            continue
        hive = str(raw.get("Hive") or "")
        key = str(raw.get("Key") or "").strip()
        ident = f"{source}|{hive}|{(key or name).casefold()}"
        if ident in seen:
            continue
        seen.add(ident)
        if source == "appx":
            prog = InstalledProgram(
                name=_appx_display_name(str(raw.get("Friendly") or "").strip(), name),
                publisher=_appx_publisher(str(raw.get("Publisher") or "")),
                version=str(raw.get("Version") or "").strip(),
                install_date=_fmt_date(str(raw.get("InstallDate") or "")),
                size_mb=0.0,
                uninstall="",
                location=str(raw.get("Location") or "").strip(),
                install_sort=_sort_date(str(raw.get("InstallDate") or "")),
                source="appx",
                hive="User",
                key=key,
                package_name=name,
                package_full_name=str(raw.get("FullName") or "").strip(),
                non_removable=bool(raw.get("NonRemovable")),
            )
            match = review.get(("appx", key.casefold())) or review.get(("appx", name.casefold()))
        else:
            publisher = str(raw.get("Publisher") or "").strip()
            prog = InstalledProgram(
                name=name,
                publisher=publisher,
                version=str(raw.get("Version") or "").strip(),
                install_date=_fmt_date(str(raw.get("InstallDate") or "")),
                size_mb=float(raw.get("EstimatedSizeMB") or 0),
                uninstall=str(raw.get("Uninstall") or "").strip(),
                quiet_uninstall=str(raw.get("QuietUninstall") or "").strip(),
                location=str(raw.get("Location") or "").strip(),
                install_sort=_sort_date(str(raw.get("InstallDate") or "")),
                source="win32",
                hive=hive,
                key=key,
                system_component=str(raw.get("SystemComponent") or "").strip() == "1" or bool(str(raw.get("Parent") or "").strip()),
            )
            match = review.get(("win32", key.casefold())) or review.get(("win32", name.casefold()))
        if match:
            prog.review, prog.review_reason = match[0], match[1]
            if not prog.size_mb and len(match) > 2:
                prog.size_mb = float(match[2] or 0)  # размер из обзора (замер папки)
        prog.flags = _detect_flags(prog)
        prog.lock_reason = lock_reason_for(prog)
        result.append(prog)
    result.sort(key=lambda p: p.name.casefold())
    return result


def filter_programs(programs: list[InstalledProgram], mode: str) -> list[InstalledProgram]:
    if mode == "large":
        return sorted([p for p in programs if p.size_mb >= 500], key=lambda p: p.size_mb, reverse=True)
    if mode == "no_publisher":
        return [p for p in programs if not p.publisher]
    if mode == "recent":
        dated = [p for p in programs if p.install_sort]
        dated.sort(key=lambda p: p.install_sort, reverse=True)
        return dated[:30]
    if mode in ("A", "B"):
        return [p for p in programs if p.review == mode]
    if mode == "store":
        return [p for p in programs if p.is_store]
    if mode == "win32":
        return [p for p in programs if not p.is_store]
    if mode == "removable":
        return [p for p in programs if not p.locked]
    return programs


def format_programs(programs: list[InstalledProgram]) -> str:
    lines = ["=== Установленные программы ===", ""]
    if not programs:
        lines.append("Список пуст.")
        return "\n".join(lines)
    for prog in programs[:80]:
        pub = prog.publisher or "—"
        size = f"{prog.size_mb:.0f} МБ" if prog.size_mb else "—"
        extra = []
        if prog.review in REVIEW_LABELS:
            extra.append(REVIEW_LABELS[prog.review])
        if prog.locked:
            extra.append(f"нельзя удалить: {prog.lock_reason}")
        tail = f"  [{'; '.join(extra)}]" if extra else ""
        lines.append(f"{prog.name}  ({prog.kind_label}){tail}")
        lines.append(f"  издатель: {pub}; размер: {size}; дата: {prog.install_date or '—'}")
    if len(programs) > 80:
        lines.append(f"\n… и ещё {len(programs) - 80}")
    return "\n".join(lines)


def open_uninstall_settings() -> None:
    os.startfile("ms-settings:appsfeatures")  # type: ignore[attr-defined]


# --- Подтверждение удаления -----------------------------------------------------------


@dataclass
class RemovalPlan:
    items: list[InstalledProgram] = field(default_factory=list)
    skipped: list[InstalledProgram] = field(default_factory=list)  # заблокированные (не удаляются)
    total_mb: float = 0.0
    admin_count: int = 0
    store_count: int = 0

    @property
    def lines(self) -> list[str]:
        out = []
        for p in self.items:
            size = _fmt_mb(p.size_mb) if p.size_mb else "размер неизвестен"
            extra = " · нужны права администратора" if p.needs_admin else ""
            out.append(f"{p.name} — {size} · {p.kind_label}{extra}")
        return out


def build_removal_plan(programs: list[InstalledProgram]) -> RemovalPlan:
    """Собрать список к удалению из отмеченных пунктов (заблокированные отбрасываются)."""
    plan = RemovalPlan()
    seen: set[str] = set()
    for p in programs:
        if p.uid in seen:
            continue
        seen.add(p.uid)
        if p.locked:
            plan.skipped.append(p)
            continue
        plan.items.append(p)
        plan.total_mb += p.size_mb
        plan.admin_count += int(p.needs_admin)
        plan.store_count += int(p.is_store)
    return plan


def _fmt_mb(mb: float) -> str:
    return f"{mb / 1024:.2f} ГБ" if mb >= 1024 else f"{mb:.0f} МБ" if mb >= 1 else f"{mb * 1024:.0f} КБ"


# --- Удаление одного пункта -----------------------------------------------------------


@dataclass
class UninstallOutcome:
    status: str  # removed | unconfirmed | cancelled | error
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "removed"


_MSI_CODES = {
    1602: ("cancelled", "отменено в окне удаления"),
    1605: ("removed", "программа уже не установлена"),
    1618: ("error", "сейчас идёт другая установка/удаление — повторите позже"),
    1641: ("removed", "удалено, Windows перезагрузится"),
    3010: ("removed", "удалено, нужна перезагрузка"),
}


def registry_entry_exists(prog: InstalledProgram) -> bool:
    if not IS_WINDOWS or not prog.key:
        return False
    import winreg

    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    if prog.hive == "HKCU":
        root, path, flags = winreg.HKEY_CURRENT_USER, base, 0
    elif prog.hive == "HKLM-WOW":
        root, path, flags = winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", 0
    else:
        root, path, flags = winreg.HKEY_LOCAL_MACHINE, base, winreg.KEY_WOW64_64KEY
    try:
        with winreg.OpenKey(root, f"{path}\\{prog.key}", 0, winreg.KEY_READ | flags):
            return True
    except OSError:
        return False


def appx_installed(prog: InstalledProgram) -> bool:
    completed = run_powershell("@(Get-AppxPackage -Name $env:WINOPT_NAME).Count", {"WINOPT_NAME": prog.package_name}, timeout=60)
    return (completed.stdout or "").strip() not in ("", "0")


def _helper_processes_alive(since: float) -> bool:
    """Идут ли ещё процессы-деинсталляторы, запущенные после since (Inno/NSIS копируют себя во временную папку)."""
    try:
        import psutil
    except ImportError:
        return False
    pattern = re.compile(r"^(au_|un_a|_iu|unins|uninst|uninstall|setup|msiexec)|\.tmp$", re.I)
    for proc in psutil.process_iter(["name", "create_time"]):
        try:
            if proc.info["create_time"] and proc.info["create_time"] >= since - 1 and pattern.search(proc.info["name"] or ""):
                return True
        except (psutil.Error, TypeError):
            continue
    return False


def uninstall_program(prog: InstalledProgram, is_admin: bool, cancelled=lambda: False, settle_timeout: int = 600) -> UninstallOutcome:
    """Удалить ОДНУ программу. Вызывается только после подтверждения пользователя."""
    if prog.locked:
        return UninstallOutcome("error", f"удаление заблокировано: {prog.lock_reason}")
    if prog.is_store:
        return _remove_appx(prog)
    return _run_win32_uninstaller(prog, is_admin, cancelled, settle_timeout)


def _remove_appx(prog: InstalledProgram) -> UninstallOutcome:
    if not prog.package_full_name:
        return UninstallOutcome("error", "нет полного имени пакета")
    completed = run_powershell(
        "Remove-AppxPackage -Package $env:WINOPT_PKG -ErrorAction Stop",
        {"WINOPT_PKG": prog.package_full_name},
        timeout=600,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip().splitlines()
        text = next((line for line in err if line.strip() and not line.startswith("+")), "ошибка Remove-AppxPackage")
        return UninstallOutcome("error", text[:300])
    if appx_installed(prog):
        return UninstallOutcome("unconfirmed", "команда выполнена, но пакет ещё в списке")
    return UninstallOutcome("removed", "приложение удалено")


def _run_win32_uninstaller(prog: InstalledProgram, is_admin: bool, cancelled, settle_timeout: int) -> UninstallOutcome:
    from winopt.winutil import LaunchError, shell_execute, split_command

    command = prog.uninstall_command()
    exe, args = split_command(command)
    if not exe:
        return UninstallOutcome("error", "нет команды удаления")
    started = time.time()
    try:
        handle = shell_execute(exe, args, elevate=prog.needs_admin and not is_admin)
    except LaunchError as exc:
        status = "cancelled" if exc.code == 1223 else "error"
        return UninstallOutcome(status, str(exc))
    try:
        while not handle.wait(500):
            if cancelled():
                return UninstallOutcome("cancelled", "ожидание прервано — окно деинсталлятора может быть ещё открыто")
        code = handle.exit_code()
    finally:
        handle.close()
    if code in _MSI_CODES and "msiexec" in exe.casefold():
        status, text = _MSI_CODES[code]
        if status != "removed" or not registry_entry_exists(prog):
            return UninstallOutcome(status, text)
    # Некоторые деинсталляторы перезапускают себя из временной папки и сразу завершаются.
    exited = time.time()
    while registry_entry_exists(prog):
        if cancelled():
            return UninstallOutcome("cancelled", "ожидание прервано")
        idle = time.time() - exited
        if idle > settle_timeout or (idle > 8 and not _helper_processes_alive(started)):
            break
        time.sleep(1)
    if not registry_entry_exists(prog):
        return UninstallOutcome("removed", "программа удалена")
    if code not in (None, 0):
        return UninstallOutcome("error", f"деинсталлятор завершился с кодом {code}")
    return UninstallOutcome("unconfirmed", "деинсталлятор закрыт, но программа ещё в списке (возможно, удаление отменено)")


# --- Вспомогательное -----------------------------------------------------------------


def _appx_display_name(friendly: str, package: str) -> str:
    """«Xbox (GamingApp)»: имя из меню «Пуск» + имя пакета, если оно не повторяет первое."""
    pretty = _pretty_package(package)
    if not friendly:
        return pretty
    if pretty.casefold().replace(" ", "") in friendly.casefold().replace(" ", ""):
        return friendly
    return f"{friendly} ({pretty})"


def _pretty_package(name: str) -> str:
    """Microsoft.BingWeather → BingWeather; 7EE7776C.LinkedInforWindows → LinkedInforWindows."""
    return name.split(".", 1)[1] if "." in name and not name.startswith("www.") else name


def _appx_publisher(raw: str) -> str:
    match = re.search(r"CN=([^,]+)", raw)
    cn = (match.group(1) if match else raw).strip()
    if re.fullmatch(r"[0-9A-F-]{30,}", cn, re.I):
        return "сторонний (Магазин)"
    return cn


def _detect_flags(prog: InstalledProgram) -> tuple[str, ...]:
    flags: list[str] = []
    if not prog.publisher:
        flags.append("нет издателя")
    if prog.size_mb >= 1024:
        flags.append("тяжёлая")
    return tuple(flags)


def _fmt_date(raw: str) -> str:
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        try:
            return datetime.strptime(raw, "%Y%m%d").strftime("%d.%m.%Y")
        except ValueError:
            return raw
    return raw


def _sort_date(raw: str) -> str:
    raw = raw.strip()
    return raw if len(raw) == 8 and raw.isdigit() else ""
