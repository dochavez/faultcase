"""Synthetic benchmark fixtures: valid evidence with known incident counts."""

import json
from pathlib import Path

from jsonschema import validate

from faultcase import rules

SYNTHETIC = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"
EVIDENCE_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "evidence.schema.json")
    .read_text(encoding="utf-8")
)

EXPECTED_INCIDENTS = {
    "healthy": 0,
    "disk_failure": 3,
    "single_crash": 1,
    "wifi": 6,
    "usb": 5,
    "battery": 0,
}


def _load(name):
    return json.loads((SYNTHETIC / f"{name}.json").read_text(encoding="utf-8"))


def test_synthetic_fixtures_validate_and_match_counts():
    assert sorted(p.stem for p in SYNTHETIC.glob("*.json")) == sorted(
        EXPECTED_INCIDENTS
    )
    for name, total in EXPECTED_INCIDENTS.items():
        case = _load(name)
        validate(instance=case["evidence"], schema=EVIDENCE_SCHEMA)
        findings = rules.apply_rules(case["evidence"], tz=case["timezone"])
        assert findings["summary"]["total_incidents"] == total
        assert case["expected_verdict_contains"]


def test_disk_fixture_reports_bad_blocks():
    case = _load("disk_failure")
    findings = rules.apply_rules(case["evidence"], tz=case["timezone"])
    assert ("disk", "bad_block") in [
        (p["playbook"], p["id"]) for p in findings["patterns"]
    ]


def _patterns(name):
    case = _load(name)
    findings = rules.apply_rules(case["evidence"], tz=case["timezone"])
    return {(p["playbook"], p["id"]): p for p in findings["patterns"]}


def test_wifi_fixture_golden_findings():
    patterns = _patterns("wifi")
    assert patterns[("wifi", "wifi_events")]["verdict"] == "fact"
    frequent = patterns[("wifi", "wifi_frequent_disconnects")]
    assert frequent["verdict"] == "fact"
    assert "5 Wi-Fi disconnections on 2026-05-01" in frequent["detail"]
    assert patterns[("wifi", "wifi_driver_issues")]["verdict"] == "fact"
    assert patterns[("wifi", "wifi_after_resume")]["verdict"] == "hypothesis"


def test_usb_fixture_golden_findings():
    patterns = _patterns("usb")
    assert patterns[("usb", "usb_events")]["verdict"] == "fact"
    repeat = patterns[("usb", "usb_same_device_repeats")]
    assert repeat["verdict"] == "fact"
    assert "VID_1234&PID_ABCD" in repeat["detail"]
    assert "failed 3 times" in repeat["detail"]
    assert patterns[("usb", "usb_driver_failed")]["verdict"] == "fact"
    assert patterns[("usb", "usb_after_resume")]["verdict"] == "hypothesis"


def test_battery_fixture_golden_findings():
    patterns = _patterns("battery")
    assert set(patterns) == {
        ("battery", "battery_wear"),
        ("battery", "battery_early_wear"),
        ("battery", "battery_rapid_decline"),
    }
    assert "35%" in patterns[("battery", "battery_early_wear")]["detail"]
    assert "10 months" in patterns[("battery", "battery_early_wear")]["detail"]
    assert all(p["verdict"] == "fact" for p in patterns.values())
