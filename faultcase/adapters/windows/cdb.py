"""Local minidump analysis with cdb.exe (local Windows mode only).

Finds cdb.exe, copies dumps from the Minidump folder to a temp folder
(originals are never modified) and runs ``!analyze -v`` plus ``lmvm``
on each copy with a 5 minute timeout. The text output goes through the
deterministic WinDbg parser; .dmp contents are never sent to any model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from faultcase.adapters.windows.windbg import parse_windbg_text

CDB_COMMAND = "!analyze -v; lmvm nvlddmkm; q"
DUMP_TIMEOUT_SECONDS = 300
SYMBOLS_SERVER = "https://msdl.microsoft.com/download/symbols"


def _candidate_paths() -> list[Path]:
    candidates = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(var)
        if root:
            candidates.append(
                Path(root) / "Windows Kits" / "10" / "Debuggers" / "x64" / "cdb.exe"
            )
    return candidates


def find_cdb() -> Path | None:
    """Locate cdb.exe on PATH or in the standard kit folders (Windows only)."""
    if os.name != "nt":
        return None
    found = shutil.which("cdb.exe")
    if found:
        return Path(found)
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
    return None


def default_minidump_dir() -> Path:
    """Return the system Minidump folder (read-only access)."""
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Minidump"


def _symbols_path(symbols_dir: Path | None = None) -> str:
    directory = Path(
        symbols_dir or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        / "FaultCaseSymbols"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return f"srv*{directory}*{SYMBOLS_SERVER}"


def run_cdb(
    dump: str | Path,
    cdb_path: str | Path | None = None,
    timeout: int = DUMP_TIMEOUT_SECONDS,
    symbols_dir: str | Path | None = None,
) -> str:
    """Run cdb on one dump copy and return its text output."""
    cdb = Path(cdb_path) if cdb_path else find_cdb()
    if cdb is None:
        raise FileNotFoundError("cdb.exe not found")
    completed = subprocess.run(
        [str(cdb), "-z", str(dump), "-y", _symbols_path(symbols_dir),
         "-c", CDB_COMMAND],
        capture_output=True, text=True, errors="replace",
        timeout=timeout, check=False,
    )
    output = completed.stdout or ""
    if completed.stderr:
        output += "\n" + completed.stderr
    return output


def analyze_dump_file(
    dump: str | Path,
    cdb_path: str | Path | None = None,
    timeout: int = DUMP_TIMEOUT_SECONDS,
    symbols_dir: str | Path | None = None,
) -> dict:
    """Run cdb on one dump copy and return the parsed dump fields."""
    return parse_windbg_text(
        run_cdb(dump, cdb_path=cdb_path, timeout=timeout, symbols_dir=symbols_dir)
    )


def collect_minidumps(
    source_dir: str | Path | None = None,
    cdb_path: str | Path | None = None,
    timeout: int = DUMP_TIMEOUT_SECONDS,
) -> list[dict]:
    """Copy every .dmp to a temp folder and analyze each copy.

    Returns one record per dump (or one fatal record)::

        {"file": ..., "dump": {...} | None,
         "summary": str | None, "error": str | None}

    Originals are never modified; per-dump failures are recorded, not raised.
    """
    source = Path(source_dir) if source_dir else default_minidump_dir()
    cdb = Path(cdb_path) if cdb_path else find_cdb()
    if cdb is None:
        return [{"file": None, "dump": None, "summary": None,
                 "error": "cdb.exe not found"}]
    try:
        dump_files = sorted(source.glob("*.dmp"))
    except OSError as exc:
        return [{"file": None, "dump": None, "summary": None,
                 "error": f"cannot read {source}: {exc}"}]
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        for dump_file in dump_files:
            record: dict = {
                "file": dump_file.name, "dump": None, "summary": None, "error": None,
            }
            try:
                copy = Path(tmp) / dump_file.name
                shutil.copy2(dump_file, copy)
                record["summary"] = run_cdb(copy, cdb_path=cdb, timeout=timeout)
                record["dump"] = parse_windbg_text(record["summary"])
            except subprocess.TimeoutExpired:
                record["error"] = f"timed out after {timeout} seconds"
            except OSError as exc:
                record["error"] = str(exc)
            records.append(record)
    return records
