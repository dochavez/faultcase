"""Golden test: the real case must produce exactly the expected conclusions.

Builds evidence from fixtures/real_case (events_41.json + windbg/*.txt),
applies the rules engine and checks every field of expected.json except
acceptable_verdicts, minimum_confidence and must_not_claim, which are
checked later against the model output. expected.json is never edited to
make a test pass; a failure here means the code is wrong.
"""

import json
from pathlib import Path

from faultcase import normalize, rules
from faultcase.adapters.windows import fixture_events, windbg
from faultcase.normalize import normalize_hex

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
EXPECTED = json.loads((REAL_CASE / "expected.json").read_text(encoding="utf-8"))


def _build():
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
    for path in sorted((REAL_CASE / "windbg").glob("*.txt")):
        dumps.append({"file": path.name, **windbg.parse_windbg(path)})
    evidence = normalize.normalize(events, dumps).evidence
    return evidence, rules.apply_rules(evidence)


EVIDENCE, FINDINGS = _build()


def test_total_incidents():
    assert len(FINDINGS["incidents"]) == EXPECTED["total_incidents"]


def test_rules_summary():
    summary = {k: v for k, v in FINDINGS["summary"].items() if k != "incidents"}
    assert summary == {
        "total_incidents": 6,
        "incidents_with_dump": 4,
        "freezes_without_dump": 2,
        "first_incident_date": "2026-04-22",
        "last_incident_date": "2026-10-23",
        "months_span": 6,
        "driver_change_direction": "older",
        "shutdowns_after_long_power_off": 0,
    }


def _dumped_incident(day, stamp, incident_id):
    return {
        "time": f"{day}T12:00:00+00:00",
        "source": "Microsoft-Windows-Kernel-Power",
        "event_id": 41,
        "kind": "unexpected_reboot",
        "playbook": "stability",
        "code": 307,
        "fields": {"BugcheckCode": 307},
        "incident_id": incident_id,
    }, {
        "file": f"{incident_id}.dmp",
        "bugcheck_code": "133",
        "params": ["1", "1e00", "0", "0"],
        "image_name": "nvlddmkm.sys",
        "driver_timestamp": stamp,
        "incident_id": incident_id,
    }


def _direction_for(stamps):
    events, dumps = [], []
    for i, (day, stamp) in enumerate(stamps):
        event, dump = _dumped_incident(day, stamp, f"inc-00{i + 1}")
        events.append(event)
        dumps.append(dump)
    evidence = {
        "os": "windows",
        "collected_at": "2026-10-24T00:00:00+00:00",
        "events": events,
        "dumps": dumps,
    }
    return rules.apply_rules(evidence)["summary"]["driver_change_direction"]


def test_driver_change_direction():
    assert _direction_for([
        ("2026-04-22", "2026-03-04"), ("2026-10-23", "2026-02-14"),
    ]) == "older"
    assert _direction_for([
        ("2026-04-22", "2026-02-14"), ("2026-10-23", "2026-03-04"),
    ]) == "newer"
    assert _direction_for([("2026-04-22", "2026-03-04")]) == "unknown"
    assert _direction_for([
        ("2026-04-22", "2026-03-04"), ("2026-10-23", "2026-03-04"),
    ]) == "unknown"


def test_summary_incidents_list():
    entries = FINDINGS["summary"]["incidents"]
    assert [e["date"] for e in entries] == [
        "2026-04-22", "2026-04-30", "2026-07-17",
        "2026-07-21", "2026-07-24", "2026-10-23",
    ]
    assert entries[0] == {
        "date": "2026-04-22",
        "time": "20:38:54",
        "label": "Blue screen: driver timeout",
        "code": "0x133",
        "has_dump": True,
        "dump_module": "nvlddmkm.sys",
        "driver_timestamp": None,
    }
    assert entries[1] == {
        "date": "2026-04-30",
        "time": "17:34:39",
        "label": "Freeze without blue screen",
        "code": "0x0",
        "has_dump": False,
        "dump_module": None,
        "driver_timestamp": None,
    }
    assert entries[-1]["label"] == "Blue screen: display driver"


def test_months_span_uses_elapsed_days():
    # 2026-04-22 to 2026-10-23 is 184 days: round(184 / 30.44) = 6.
    evidence = {
        "os": "windows",
        "collected_at": "2026-10-24T00:00:00+00:00",
        "events": [
            {
                "time": f"{day}T12:00:00+00:00",
                "source": "Microsoft-Windows-Kernel-Power",
                "event_id": 41,
                "kind": "unexpected_reboot",
                "playbook": "stability",
                "code": 307,
                "fields": {"BugcheckCode": 307},
                "incident_id": f"inc-00{i + 1}",
            }
            for i, day in enumerate(["2026-04-22", "2026-10-23"])
        ],
        "dumps": [],
    }
    summary = rules.apply_rules(evidence)["summary"]
    assert summary["months_span"] == 6
    assert summary["first_incident_date"] == "2026-04-22"
    assert summary["last_incident_date"] == "2026-10-23"


def test_incidents_with_dump():
    with_dump = [i for i in FINDINGS["incidents"] if i["dump_module"]]
    assert len(with_dump) == EXPECTED["incidents_with_dump"]


def test_freezes_without_dump():
    freezes = [
        i for i in FINDINGS["incidents"]
        if i["code"] == 0 and not i["dump_module"]
    ]
    assert len(freezes) == EXPECTED["freezes_without_dump"]


def test_codes_by_date():
    codes = {i["date"]: i["code_hex"] for i in FINDINGS["incidents"]}
    assert codes == EXPECTED["codes_by_date"]
    for incident in FINDINGS["incidents"]:
        assert incident["code_name"], incident["date"]
        assert incident["explanation"], incident["date"]


def test_common_module():
    assert FINDINGS["common_module"] == EXPECTED["common_module"]
    assert FINDINGS["dumps_with_common_module"] == EXPECTED["dumps_with_common_module"]


def test_distinct_driver_timestamps():
    assert FINDINGS["distinct_driver_timestamps"] == EXPECTED["distinct_driver_timestamps"]


def test_incidents_during_power_transition():
    transitions = [i for i in FINDINGS["incidents"] if i["power_transition"]]
    assert len(transitions) == EXPECTED["incidents_during_power_transition"]


def test_required_patterns_are_facts():
    facts = {p["id"] for p in FINDINGS["patterns"] if p["verdict"] == "fact"}
    for pattern in EXPECTED["required_patterns"]:
        assert pattern in facts


def test_hypothesis_patterns_are_hypotheses():
    hypotheses = {
        p["id"] for p in FINDINGS["patterns"] if p["verdict"] == "hypothesis"
    }
    for pattern in EXPECTED["hypothesis_patterns"]:
        assert pattern in hypotheses


def test_photo_parameters_match():
    target = EXPECTED["photo_parameters_match"]
    incident = next(i for i in FINDINGS["incidents"] if i["date"] == target)
    dump = next(
        d for d in EVIDENCE["dumps"]
        if d.get("incident_id") == incident["incident_id"]
    )
    assert incident["params"] is not None
    assert dump.get("params") is not None
    assert [normalize_hex(p) for p in incident["params"]] == [
        normalize_hex(p) for p in dump["params"]
    ]


def test_healthy_components():
    assert {h["playbook"] for h in FINDINGS["healthy"]} == {
        "disk", "hardware", "thermal", "software", "wifi", "usb", "battery",
    }
    for entry in FINDINGS["healthy"]:
        assert entry["note"]


def test_no_invented_wifi_usb_battery_findings():
    playbooks = {p["playbook"] for p in FINDINGS["patterns"]}
    assert playbooks.isdisjoint({"wifi", "usb", "battery"})


def test_incident_date_converts_to_user_timezone():
    evidence = {
        "os": "windows",
        "collected_at": "2026-04-23T00:00:00+00:00",
        "events": [{
            "time": "2026-04-23T02:38:54+00:00",
            "source": "Microsoft-Windows-Kernel-Power",
            "event_id": 41,
            "kind": "unexpected_reboot",
            "playbook": "stability",
            "code": 307,
            "params": ["0x1", "0x1e00", "0x0", "0x0"],
            "fields": {"BugcheckCode": 307},
            "incident_id": "inc-001",
        }],
        "dumps": [],
    }
    local = rules.apply_rules(evidence, tz="America/Managua")
    assert local["incidents"][0]["date"] == "2026-04-22"
    utc = rules.apply_rules(evidence, tz="UTC")
    assert utc["incidents"][0]["date"] == "2026-04-23"


def test_other_playbook_pattern_when_events_exist():
    events = [{
        "time": "2026-05-01T10:00:00+00:00",
        "log": "System",
        "source": "disk",
        "event_id": 7,
        "fields": {},
    }]
    evidence = normalize.normalize(events, []).evidence
    findings = rules.apply_rules(evidence)
    assert {
        "id": "bad_block", "playbook": "disk", "verdict": "fact",
        "detail": "1 bad_block event on 2026-05-01",
    } in findings["patterns"]
    assert "disk" not in {h["playbook"] for h in findings["healthy"]}
