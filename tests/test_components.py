"""Component playbooks (wifi, usb, battery): matching, patterns, filter."""

import xml.etree.ElementTree as ET
from pathlib import Path

from faultcase import normalize, rules
from faultcase.normalize import load_playbooks

ROOT = Path(__file__).resolve().parent.parent


def _raw(time, source, event_id, fields=None):
    return {
        "time": time, "log": "System", "source": source, "event_id": event_id,
        "fields": fields or {},
    }


def test_wifi_playbook_matches_and_drops_ssid():
    events = [
        _raw("2026-05-01T10:00:00+00:00", "Microsoft-Windows-WLAN-AutoConfig",
             8003, {"SSID": "HomeNet", "ProfileName": "HomeNet",
                    "Reason": "The network is disconnected by the driver.",
                    "ReasonCode": 0}),
        _raw("2026-05-01T10:05:00+00:00", "Netwaw18", 6062, {}),
    ]
    result = normalize.normalize(events)
    assert result.noise == 0
    by_kind = {e["kind"]: e for e in result.evidence["events"]}
    assert by_kind["wifi_disconnected"]["playbook"] == "wifi"
    assert by_kind["wifi_driver_warning"]["playbook"] == "wifi"
    kept = by_kind["wifi_disconnected"]["fields"]
    assert "SSID" not in kept and "ProfileName" not in kept
    assert kept["ReasonCode"] == 0


def test_resume_marker_gets_no_incident():
    events = [
        _raw("2026-05-01T09:59:00+00:00", "Microsoft-Windows-Power-Troubleshooter",
             1, {}),
    ]
    result = normalize.normalize(events)
    assert result.evidence["events"][0]["kind"] == "resume_from_sleep"
    assert result.evidence["events"][0]["incident_id"] is None
    findings = rules.apply_rules(result.evidence)
    assert findings["summary"]["total_incidents"] == 0


def test_wifi_frequent_disconnects_pattern():
    events = [
        _raw(f"2026-05-01T1{i}:00:00+00:00",
             "Microsoft-Windows-WLAN-AutoConfig", 8003, {})
        for i in range(3)
    ]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    assert ("wifi", "wifi_frequent_disconnects") in patterns
    assert patterns[("wifi", "wifi_frequent_disconnects")]["verdict"] == "fact"
    assert "2026-05-01" in patterns[("wifi", "wifi_frequent_disconnects")]["detail"]


def test_wifi_driver_and_after_resume_patterns():
    events = [
        _raw("2026-05-01T09:00:00+00:00", "Microsoft-Windows-Power-Troubleshooter",
             1, {}),
        _raw("2026-05-01T09:05:00+00:00", "Microsoft-Windows-WLAN-AutoConfig",
             8002, {"FailureReason": "No AP visible", "ReasonCode": 1}),
        _raw("2026-05-01T12:00:00+00:00", "Netwaw18", 6062, {}),
    ]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    assert patterns[("wifi", "wifi_driver_issues")]["verdict"] == "fact"
    assert "6062" in patterns[("wifi", "wifi_driver_issues")]["detail"]
    assert patterns[("wifi", "wifi_after_resume")]["verdict"] == "hypothesis"
    assert ("wifi", "wifi_frequent_disconnects") not in patterns


def test_filter_covers_wifi_channels_and_ids():
    xml = ET.parse(ROOT / "filters" / "device-diagnostics.xml")
    selects = {
        select.get("Path"): select.text
        for select in xml.getroot().iter("Select")
    }
    assert "Microsoft-Windows-WLAN-AutoConfig/Operational" in selects
    wlan = selects["Microsoft-Windows-WLAN-AutoConfig/Operational"]
    assert "EventID=8002" in wlan and "EventID=8003" in wlan
    system = selects["System"]
    for event_id in ("EventID=1", "EventID=5002", "EventID=5005",
                     "EventID=5007", "EventID=6062"):
        assert event_id in system


def test_wifi_playbook_documents_verification():
    playbook = next(p for p in load_playbooks() if p["id"] == "wifi")
    assert playbook["verification"]["wifi_driver_warning"]
    assert "Netwtw" in playbook["verification"]["providers"]
