"""Precomputed demo case: builders shared by the app and the build script."""

from __future__ import annotations

from pathlib import Path

from faultcase.adapters.windows import fixture_events, windbg
from faultcase.normalize import normalize

REAL_CASE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
DEMO_CASE_PATH = REAL_CASE_DIR / "demo_case.json"
DEMO_TIMEZONE = "America/Managua"
DEMO_DEVICE = {
    "manufacturer": "Lenovo",
    "model": "Legion Pro 7 16IAX10H",
    "machine_type": "83F5",
    "gpu": "NVIDIA",
    "purchase_date": "2026-01",
}


def build_demo_evidence() -> tuple[dict, dict[str, str]]:
    """Normalize the real case fixtures; return (evidence, windbg summaries)."""
    events = fixture_events.load_fixture_events(REAL_CASE_DIR / "events_41.json")
    for event in list(events):
        related = event["fields"].get("related_6008")
        if related:
            events.append({
                "time": related,
                "log": "System",
                "source": "EventLog",
                "event_id": 6008,
                "fields": {},
            })
    dumps = []
    summaries = {}
    for path in sorted((REAL_CASE_DIR / "windbg").glob("*.txt")):
        summaries[path.name] = path.read_text(encoding="utf-8")
        dumps.append({
            "file": path.name.replace(".txt", ".dmp"),
            **windbg.parse_windbg(path),
        })
    return normalize(events, dumps).evidence, summaries


def load_demo_summaries() -> dict[str, str]:
    """Read the WinDbg summary texts shipped with the app (no models)."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((REAL_CASE_DIR / "windbg").glob("*.txt"))
    }
