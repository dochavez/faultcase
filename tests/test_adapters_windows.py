"""Tests for the Windows adapter: WinDbg parser, .evtx parser, fixture loader."""

from datetime import datetime
from pathlib import Path

import pytest

from faultcase.adapters.windows import evtx, fixture_events, windbg

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"

WINDBG_EXPECTED = {
    "042226-15687-01.txt": {
        "failure_bucket_id": "0x133_ISR_nvlddmkm!unknown_function",
        "failure_id_hash": "{f97493a5-ea2b-23ca-a808-8602773c2a86}",
        "driver_timestamp": None,
    },
    "071726-15718-01.txt": {
        "failure_bucket_id": "0x133_ISR_nvlddmkm!unknown_function",
        "failure_id_hash": "{f97493a5-ea2b-23ca-a808-8602773c2a86}",
        "driver_timestamp": "2026-03-04",
    },
    "072126-14468-01.txt": {
        "failure_bucket_id": "0x133_ISR_nvlddmkm!unknown_function",
        "failure_id_hash": "{f97493a5-ea2b-23ca-a808-8602773c2a86}",
        "driver_timestamp": "2026-03-04",
    },
    "102326-15484-01.txt": {
        "failure_bucket_id": "0x116_IMAGE_nvlddmkm.sys",
        "failure_id_hash": "{c89bfe8c-ed39-f658-ef27-f2898997fdbd}",
        "driver_timestamp": "2026-02-14",
    },
}


@pytest.mark.parametrize("filename,expected", sorted(WINDBG_EXPECTED.items()))
def test_windbg_parses_dump(filename, expected):
    dump = windbg.parse_windbg(REAL_CASE / "windbg" / filename)
    assert dump["image_name"] == "nvlddmkm.sys"
    assert dump["failure_bucket_id"] == expected["failure_bucket_id"]
    assert dump["failure_id_hash"] == expected["failure_id_hash"]
    assert dump["driver_timestamp"] == expected["driver_timestamp"]


def test_evtx_returns_event_41():
    evtx_path = REAL_CASE / "failures.evtx"
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    result = evtx.parse_evtx(evtx_path)
    reboots = [e for e in result.events if e["event_id"] == 41]
    assert reboots, "expected Kernel-Power 41 events in failures.evtx"
    first = reboots[0]
    assert first["source"] == "Microsoft-Windows-Kernel-Power"
    assert first["log"] == "System"
    assert datetime.fromisoformat(first["time"]).tzinfo is not None
    assert "BugcheckCode" in first["fields"]


def test_fixture_events_match_evtx_format():
    events = fixture_events.load_fixture_events()
    assert len(events) == 6
    assert {e["event_id"] for e in events} == {41}
    for event in events:
        assert set(event) == {"time", "log", "source", "event_id", "fields"}
        assert datetime.fromisoformat(event["time"]).tzinfo is not None
