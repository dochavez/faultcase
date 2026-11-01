"""Parse WinDbg text output (``!analyze -v`` and ``lmvm``) into dump fields.

Returns the ``dumps`` entry shape from schemas/evidence.schema.json:
bugcheck_code, params, image_name, symbol_name, failure_bucket_id,
failure_id_hash, process_name and driver_timestamp (ISO date).
Anything the text does not contain stays None; values are never invented.
"""

from __future__ import annotations

import re
from pathlib import Path

ANALYZE_KEYS = {
    "BUGCHECK_CODE": "bugcheck_code",
    "PROCESS_NAME": "process_name",
    "SYMBOL_NAME": "symbol_name",
    "IMAGE_NAME": "image_name",
    "FAILURE_BUCKET_ID": "failure_bucket_id",
    "FAILURE_ID_HASH": "failure_id_hash",
}

TIMESTAMP_RE = re.compile(
    r"Timestamp:\s+\w{3}\s+(\w{3})\s+(\d{1,2})\s+\d{2}:\d{2}:\d{2}\s+(\d{4})"
)
MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _driver_timestamp(text: str) -> str | None:
    match = TIMESTAMP_RE.search(text)
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if month is None:
        return None
    return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"


def parse_windbg(path: str | Path) -> dict:
    """Parse one WinDbg output file into a dump dict (missing fields are None)."""
    return parse_windbg_text(Path(path).read_text(encoding="utf-8"))


def parse_windbg_text(text: str) -> dict:
    """Parse WinDbg output text into a dump dict (missing fields are None)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key in ANALYZE_KEYS or key in (
            "BUGCHECK_P1", "BUGCHECK_P2", "BUGCHECK_P3", "BUGCHECK_P4",
        ):
            value = value.strip()
            if value:
                values[key] = value
    params = [values.get(f"BUGCHECK_P{i}") for i in range(1, 5)]
    return {
        "bugcheck_code": values.get("BUGCHECK_CODE"),
        "params": params if all(params) else None,
        "image_name": values.get("IMAGE_NAME"),
        "symbol_name": values.get("SYMBOL_NAME"),
        "failure_bucket_id": values.get("FAILURE_BUCKET_ID"),
        "failure_id_hash": values.get("FAILURE_ID_HASH"),
        "process_name": values.get("PROCESS_NAME"),
        "driver_timestamp": _driver_timestamp(text),
    }
