"""Parse a System Information export (msinfo32 > File > Export).

The export is tab-separated text, often UTF-16 with BOM; the encoding is
detected from the BOM with UTF-8 as fallback. Labels are matched in
English and Spanish. Only device facts are extracted: the user name and
computer name ("User Name", "System Name") are never extracted or kept.
Missing fields are None.
"""

from __future__ import annotations

import re
from pathlib import Path

SYSTEM_SECTIONS = {"[system summary]", "[resumen del sistema]"}
DISPLAY_SECTIONS = {"[display]", "[pantalla]"}
HEADER_CELLS = {"item", "elemento"}

LABELS = {
    "os_name": {"os name", "nombre del sistema operativo"},
    "os_version": {"version", "versión"},
    "manufacturer": {"system manufacturer", "fabricante del sistema"},
    "model": {"system model", "modelo del sistema"},
    "system_sku": {"system sku", "sku del sistema"},
    "bios": {"bios version/date", "versión y fecha de bios"},
    "disp_name": {"name", "nombre"},
    "adapter_description": {"adapter description", "descripción del adaptador"},
    "driver_version": {"driver version", "versión del controlador"},
    "driver_date": {"driver date", "fecha del controlador"},
}
LABEL_TO_FIELD = {
    label: field for field, labels in LABELS.items() for label in labels
}
MACHINE_TYPE_RE = re.compile(r"MT_([A-Za-z0-9]{4})(?![A-Za-z0-9])", re.IGNORECASE)
LENOVO_TYPE_RE = re.compile(r"^[A-Za-z0-9]{4}$")


def decode_msinfo_bytes(data: bytes) -> str:
    """Decode an msinfo export, detecting UTF-16/UTF-8 BOMs first."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _machine_type(model: str | None, sku: str | None) -> str | None:
    if sku:
        match = MACHINE_TYPE_RE.search(sku)
        if match:
            return match.group(1).upper()
    if model:
        candidate = model.strip()
        if LENOVO_TYPE_RE.match(candidate) and any(c.isdigit() for c in candidate):
            return candidate.upper()
    return None


def parse_msinfo_text(text: str) -> dict:
    """Parse msinfo export text into device facts (missing fields are None)."""
    system: dict[str, str] = {}
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.lower()
            current = None
            continue
        if "\t" not in raw_line:
            continue
        label, _, value = raw_line.partition("\t")
        label = label.strip().lower()
        value = value.strip().rstrip("\t").strip()
        if not value or label in HEADER_CELLS:
            continue
        field = LABEL_TO_FIELD.get(label)
        if field is None:
            continue
        if section in SYSTEM_SECTIONS and field in (
            "os_name", "os_version", "manufacturer", "model", "system_sku", "bios",
        ):
            system.setdefault(field, value)
        elif section in DISPLAY_SECTIONS and field in (
            "disp_name", "adapter_description", "driver_version", "driver_date",
        ):
            if field == "disp_name":
                current = {}
                records.append(current)
            if current is None:
                current = {}
                records.append(current)
            current[field] = value
    bios_version, bios_date = None, None
    if system.get("bios"):
        version, comma, date = system["bios"].partition(",")
        bios_version = version.strip() or None
        bios_date = date.strip() or None if comma else None
    gpus = []
    for record in records:
        name = record.get("adapter_description") or record.get("disp_name")
        if not name:
            continue
        gpus.append({
            "name": name,
            "driver_version": record.get("driver_version"),
            "driver_date": record.get("driver_date"),
        })
    return {
        "manufacturer": system.get("manufacturer"),
        "model": system.get("model"),
        "system_sku": system.get("system_sku"),
        "machine_type": _machine_type(system.get("model"), system.get("system_sku")),
        "bios_version": bios_version,
        "bios_date": bios_date,
        "os_name": system.get("os_name"),
        "os_version": system.get("os_version"),
        "gpus": gpus,
    }


def parse_msinfo_bytes(data: bytes) -> dict:
    """Decode and parse an msinfo export given as bytes."""
    return parse_msinfo_text(decode_msinfo_bytes(data))


def parse_msinfo(path: str | Path) -> dict:
    """Parse an msinfo export file into device facts."""
    return parse_msinfo_bytes(Path(path).read_bytes())
