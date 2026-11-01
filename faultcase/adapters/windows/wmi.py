"""Read device facts on local Windows via read-only CIM queries.

Used only when the app runs locally on Windows and the user confirms this
computer is the one with the problem. Only Get-CimInstance queries run
(read-only); computer and user names are never selected. The BIOS serial
number is returned for local use only: agent.py strips it before anything
reaches a model.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

CIM_TIMEOUT_SECONDS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MACHINE_TYPE_RE = re.compile(r"^[A-Z0-9]{4}$")

QUERY = r"""
function ConvertTo-IsoDate($value) {
  if ($null -eq $value) { return $null }
  if ($value -is [datetime]) { return $value.ToString('yyyy-MM-dd') }
  $text = [string]$value
  if ($text -match '^(\d{4})(\d{2})(\d{2})') {
    return $Matches[1] + '-' + $Matches[2] + '-' + $Matches[3]
  }
  return $null
}
$cs = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1
$csp = Get-CimInstance Win32_ComputerSystemProduct | Select-Object -First 1
$bios = Get-CimInstance Win32_BIOS | Select-Object -First 1
$gpus = Get-CimInstance Win32_VideoController | ForEach-Object {
  [PSCustomObject]@{
    name = $_.Name
    driver_version = $_.DriverVersion
    driver_date = ConvertTo-IsoDate $_.DriverDate
  }
}
[PSCustomObject]@{
  manufacturer = $cs.Manufacturer
  model = $cs.Model
  machine_type = $csp.Name
  bios_manufacturer = $bios.Manufacturer
  bios_smbios = @($bios.SMBIOSBIOSVersion)
  bios_date = ConvertTo-IsoDate $bios.ReleaseDate
  serial = $bios.SerialNumber
  gpus = @($gpus)
} | ConvertTo-Json -Depth 4 -Compress
"""


def is_available() -> bool:
    """True when CIM queries can run (local Windows with PowerShell)."""
    return os.name == "nt" and shutil.which("powershell") is not None


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_date(value: object) -> str | None:
    if isinstance(value, str) and DATE_RE.match(value.strip()):
        return value.strip()
    return None


def _machine_type(value: object) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    candidate = text.upper()
    if MACHINE_TYPE_RE.match(candidate) and any(c.isdigit() for c in candidate):
        return candidate
    return None


def read_device_info(timeout: int = CIM_TIMEOUT_SECONDS) -> dict:
    """Run read-only CIM queries and return msinfo-shaped device facts."""
    powershell = shutil.which("powershell")
    if powershell is None:
        raise RuntimeError("local device reading needs Windows with PowerShell")
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", QUERY],
        capture_output=True, text=True, errors="replace",
        timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"CIM query failed: {(completed.stderr or '').strip()[:300]}")
    try:
        data = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CIM query returned invalid JSON: {exc}") from exc
    smbios = data.get("bios_smbios") or []
    if isinstance(smbios, str):
        smbios = [smbios]
    first_version = next((v for v in smbios if v), None)
    bios_version = " ".join(
        part for part in [data.get("bios_manufacturer"), first_version] if part
    ).strip() or None
    gpus = data.get("gpus") or []
    if isinstance(gpus, dict):
        gpus = [gpus]
    return {
        "manufacturer": _clean(data.get("manufacturer")),
        "model": _clean(data.get("model")),
        "machine_type": _machine_type(data.get("machine_type")),
        "system_sku": None,
        "bios_version": bios_version,
        "bios_date": _clean_date(data.get("bios_date")),
        "os_name": None,
        "os_version": None,
        "gpus": [
            {
                "name": gpu.get("name"),
                "driver_version": gpu.get("driver_version"),
                "driver_date": _clean_date(gpu.get("driver_date")),
            }
            for gpu in gpus
            if isinstance(gpu, dict) and gpu.get("name")
        ],
        "serial": _clean(data.get("serial")),
    }
