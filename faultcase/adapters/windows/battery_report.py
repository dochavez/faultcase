"""Parse the HTML produced by ``powercfg /batteryreport`` (Windows only).

Extracts design capacity, full charge capacity, cycle count, manufacture
date (when present), the report date and the capacity history, then
computes the wear percentage deterministically. Only numbers and dates
are kept: the computer name, serial number and any other identifiers in
the report are never extracted. Missing fields are None.

``generate_local_report`` runs powercfg into a temp folder (read-only
command), parses the output and deletes it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

REPORT_TIMEOUT_SECONDS = 60

LABELS = {
    "DESIGN CAPACITY": "design",
    "FULL CHARGE CAPACITY": "full",
    "CYCLE COUNT": "cycles",
    "MANUFACTURE DATE": "manufacture_date",
    "REPORT TIME": "report_date",
}

AMOUNT_RE = re.compile(r"([\d\s,\.]+)\s*(m?wh)", re.IGNORECASE)
INT_RE = re.compile(r"[\d,]+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class _Tables(HTMLParser):
    """Collect every table as a list of text-cell rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list = []
        self._rows: list | None = None
        self._row: list | None = None
        self._cell: list | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None


def _parse_amount(text: str) -> int | None:
    match = AMOUNT_RE.search(text or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "").replace(" ", ""))
    except ValueError:
        return None
    if match.group(2).lower() == "wh":
        value *= 1000
    return int(round(value))


def _parse_int(text: str) -> int | None:
    match = INT_RE.search((text or "").replace(" ", ""))
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _first_date(text: str) -> str | None:
    match = DATE_RE.search(text or "")
    return match.group(0) if match else None


def parse_battery_report_text(html: str) -> dict:
    """Parse battery report HTML into capacity facts (missing are None)."""
    parser = _Tables()
    parser.feed(html or "")
    labels: dict[str, str] = {}
    history: list[dict] = []
    for table in parser.tables:
        for row in table:
            if not row:
                continue
            head = row[0].strip().upper()
            if head == "PERIOD" and len(row) >= 3:
                continue
            if head in LABELS and len(row) >= 2:
                labels[head] = row[1]
        header = next(
            (row for row in table
             if len(row) >= 3 and row[0].strip().upper() == "PERIOD"
             and "FULL CHARGE" in row[1].upper()),
            None,
        )
        if header is None:
            continue
        started = False
        for row in table:
            if not started:
                if row == header:
                    started = True
                continue
            if len(row) < 2:
                continue
            dates = DATE_RE.findall(row[0])
            entry = {
                "period_start": dates[0] if dates else None,
                "period_end": dates[1] if len(dates) > 1 else None,
                "full_charge_mwh": _parse_amount(row[1]),
                "design_mwh": _parse_amount(row[2]) if len(row) > 2 else None,
            }
            if entry["period_start"] and entry["full_charge_mwh"] is not None:
                history.append(entry)
    design = _parse_amount(labels.get("DESIGN CAPACITY", ""))
    full = _parse_amount(labels.get("FULL CHARGE CAPACITY", ""))
    wear = None
    if design and full is not None:
        wear = round(100 * (1 - full / design), 1)
    manufacture = labels.get("MANUFACTURE DATE", "").strip() or None
    return {
        "design_capacity_mwh": design,
        "full_charge_capacity_mwh": full,
        "cycle_count": _parse_int(labels.get("CYCLE COUNT", "")),
        "manufacture_date": manufacture,
        "report_date": _first_date(labels.get("REPORT TIME", "")),
        "capacity_history": history,
        "wear_percent": wear,
    }


def parse_battery_report_bytes(data: bytes) -> dict:
    """Parse battery report HTML bytes (UTF-8 with BOM tolerance)."""
    return parse_battery_report_text(data.decode("utf-8-sig", errors="replace"))


def parse_battery_report(path: str | Path) -> dict:
    """Parse a battery report HTML file."""
    return parse_battery_report_bytes(Path(path).read_bytes())


def is_available() -> bool:
    """Check that powercfg exists (local Windows battery reports)."""
    if os.name != "nt":
        return False
    return shutil.which("powercfg") is not None


def generate_local_report(timeout: int = REPORT_TIMEOUT_SECONDS) -> dict:
    """Run powercfg /batteryreport into a temp folder and parse it.

    The read-only command writes one HTML file to a temp folder, which is
    parsed and deleted; the returned dict holds numbers and dates only.
    """
    powercfg = shutil.which("powercfg")
    if powercfg is None:
        raise FileNotFoundError("powercfg not found")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "battery-report.html"
        try:
            completed = subprocess.run(
                [powercfg, "/batteryreport", "/output", str(target)],
                capture_output=True, text=True, errors="replace",
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"powercfg timed out after {timeout} seconds"
            ) from exc
        if completed.returncode != 0 or not target.is_file():
            detail = (completed.stderr or "").strip() or "powercfg failed"
            raise RuntimeError(detail)
        return parse_battery_report(target)
