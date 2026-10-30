"""Load transcribed fixture events into the raw event format.

Reads fixtures/real_case/events_41.json and returns the same event dicts
that evtx.py produces (time, log, source, event_id, fields), so tests can
run without an .evtx file. Kernel-Power events live in the System log,
as verified against fixtures/real_case/failures.evtx.
"""

from __future__ import annotations

import json
from pathlib import Path

RECOGNIZED_KEYS = {"time", "log", "source", "event_id"}

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures" / "real_case" / "events_41.json"
)


def load_fixture_events(path: str | Path | None = None) -> list[dict]:
    """Load fixture events in the raw adapter event format."""
    with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    events = []
    for item in data["events"]:
        events.append({
            "time": item["time"],
            "log": item.get("log", "System"),
            "source": item["source"],
            "event_id": item["event_id"],
            "fields": {
                key: value for key, value in item.items()
                if key not in RECOGNIZED_KEYS
            },
        })
    return events
