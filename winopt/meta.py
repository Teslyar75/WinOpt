"""Метаданные файлов: подпись Authenticode и сведения о версии."""

from __future__ import annotations

from winopt.winutil import run_powershell

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$paths = Get-Content -LiteralPath $env:WINOPT_PATHS -Encoding UTF8 | ConvertFrom-Json
$result = foreach ($p in $paths) {
    $exists = Test-Path -LiteralPath $p
    $status = 'Unknown'
    $signer = ''
    $company = ''
    $description = ''
    $original = ''
    $product = ''
    if ($exists) {
        try {
            $sig = Get-AuthenticodeSignature -LiteralPath $p
            $status = [string]$sig.Status
            if ($sig.SignerCertificate) {
                $signer = [string]$sig.SignerCertificate.Subject
            }
        } catch {
            $status = 'Error'
        }
        try {
            $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($p)
            $company = [string]$vi.CompanyName
            $description = [string]$vi.FileDescription
            $original = [string]$vi.OriginalFilename
            $product = [string]$vi.ProductName
        } catch {}
    } else {
        $status = 'MissingFile'
    }
    [pscustomobject]@{
        Path = $p
        Exists = $exists
        SignatureStatus = $status
        Signer = $signer
        Company = $company
        Description = $description
        OriginalName = $original
        Product = $product
    }
}
$json = if ($null -eq $result) { '[]' } else { @($result) | ConvertTo-Json -Compress -Depth 4 }
[System.IO.File]::WriteAllText($env:WINOPT_OUT, $json, [System.Text.UTF8Encoding]::new($false))
"""


@dataclass(frozen=True)
class FileMeta:
    path: str
    exists: bool
    signature_status: str
    signer: str
    company: str
    description: str
    original_name: str
    product: str

    @property
    def signed_ok(self) -> bool:
        return self.signature_status.lower() == "valid"

    @property
    def hash_mismatch(self) -> bool:
        return self.signature_status.lower() == "hashmismatch"


def collect_file_meta(paths: list[str]) -> dict[str, FileMeta]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        key = raw.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)

    if not unique:
        return {}

    with tempfile.TemporaryDirectory(prefix="winopt_") as tmp:
        list_file = Path(tmp) / "paths.json"
        out_file = Path(tmp) / "meta.json"
        list_file.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
        completed = run_powershell(_PS_SCRIPT, {
                "WINOPT_PATHS": str(list_file),
                "WINOPT_OUT": str(out_file),
            }, timeout=180)
        payload = out_file.read_text(encoding="utf-8") if out_file.exists() else ""

    if not payload:
        err = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(err or "PowerShell не вернул метаданные файлов")

    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]

    result: dict[str, FileMeta] = {}
    for item in data:
        path = str(item.get("Path") or "")
        result[path.casefold()] = FileMeta(
            path=path,
            exists=bool(item.get("Exists")),
            signature_status=str(item.get("SignatureStatus") or "Unknown"),
            signer=str(item.get("Signer") or ""),
            company=str(item.get("Company") or ""),
            description=str(item.get("Description") or ""),
            original_name=str(item.get("OriginalName") or ""),
            product=str(item.get("Product") or ""),
        )
    return result


def _os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)
