"""Normalizing the real case fixtures: 6 incidents, 4 linked dumps."""

from pathlib import Path

from faultcase import normalize
from faultcase.adapters.windows import fixture_events, windbg

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
WINDBG_DIR = REAL_CASE / "windbg"

EXPECTED_DUMP_DATES = {
    "042226-15687-01.txt": "2026-04-22",
    "071726-15718-01.txt": "2026-07-17",
    "072126-14468-01.txt": "2026-07-21",
    "102326-15484-01.txt": "2026-10-23",
}


def _real_case_input():
    events = fixture_events.load_fixture_events()
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
    for name in sorted(EXPECTED_DUMP_DATES):
        dumps.append({"file": name, **windbg.parse_windbg(WINDBG_DIR / name)})
    return events, dumps


def test_real_case_produces_six_incidents():
    events, dumps = _real_case_input()
    result = normalize.normalize(events, dumps)
    incidents = {e["incident_id"] for e in result.evidence["events"]}
    assert len(incidents) == 6
    assert result.noise == 0


def test_dumps_linked_to_incident_dates():
    events, dumps = _real_case_input()
    evidence = normalize.normalize(events, dumps).evidence
    incident_dates = {
        e["incident_id"]: e["time"][:10]
        for e in evidence["events"]
        if e["kind"] == "unexpected_reboot"
    }
    assert len(evidence["dumps"]) == 4
    for dump in evidence["dumps"]:
        assert incident_dates[dump["incident_id"]] == EXPECTED_DUMP_DATES[dump["file"]]


def test_unmatched_events_counted_as_noise():
    events = [{
        "time": "2026-01-01T00:00:00+00:00",
        "log": "System",
        "source": "Some-Unknown-Provider",
        "event_id": 9999,
        "fields": {},
    }]
    result = normalize.normalize(events, [])
    assert result.evidence["events"] == []
    assert result.noise == 1
