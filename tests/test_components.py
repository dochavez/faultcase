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


USB_ID = "USB\\VID_046D&PID_C52B\\6&2a1f3c4d&0&2"


def test_usb_playbook_matches_and_limits_fields():
    events = [
        _raw("2026-05-01T10:00:00+00:00", "Microsoft-Windows-Kernel-PnP",
             411, {"DeviceInstanceId": USB_ID, "DriverName": "usb.inf",
                   "Problem": "0xa", "Status": "0x0",
                   "ClassGuid": "{12345678-1234-1234-1234-123456789abc}",
                   "ServiceName": "USB"}),
        _raw("2026-05-01T10:05:00+00:00", "Microsoft-Windows-Kernel-PnP",
             219, {"FailureName": "\\Driver\\WUDFRd", "Status": 3221226341,
                   "DriverName": "PCI\\VEN_8086&DEV_AD03\\3&11583659&0&B0"}),
    ]
    result = normalize.normalize(events)
    assert result.noise == 0
    by_kind = {e["kind"]: e for e in result.evidence["events"]}
    assert by_kind["usb_device_failed"]["playbook"] == "usb"
    assert by_kind["usb_driver_failed"]["playbook"] == "usb"
    kept = by_kind["usb_device_failed"]["fields"]
    assert "ClassGuid" not in kept and "ServiceName" not in kept
    assert kept["DeviceInstanceId"] == USB_ID
    assert "DriverName" not in by_kind["usb_driver_failed"]["fields"]


def test_usb_same_device_repeats_groups_by_model_part():
    events = [
        _raw("2026-05-01T10:00:00+00:00", "Microsoft-Windows-Kernel-PnP",
             411, {"DeviceInstanceId": USB_ID, "Problem": "0xa"}),
        _raw("2026-05-02T10:00:00+00:00", "Microsoft-Windows-Kernel-PnP",
             411, {"DeviceInstanceId": USB_ID, "Problem": "0xa"}),
    ]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    repeat = patterns[("usb", "usb_same_device_repeats")]
    assert repeat["verdict"] == "fact"
    assert "USB\\VID_046D&PID_C52B" in repeat["detail"]
    assert "6&2a1f3c4d&0&2" not in repeat["detail"]
    assert "0xa" in repeat["detail"]


def test_usb_driver_failed_and_after_resume_patterns():
    events = [
        _raw("2026-05-01T09:00:00+00:00", "Microsoft-Windows-Power-Troubleshooter",
             1, {}),
        _raw("2026-05-01T09:05:00+00:00", "Microsoft-Windows-Kernel-PnP",
             219, {"FailureName": "\\Driver\\WUDFRd"}),
    ]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    assert patterns[("usb", "usb_driver_failed")]["verdict"] == "fact"
    assert "WUDFRd" in patterns[("usb", "usb_driver_failed")]["detail"]
    assert patterns[("usb", "usb_after_resume")]["verdict"] == "hypothesis"
    assert ("usb", "usb_same_device_repeats") not in patterns


def test_filter_covers_usb_channel_and_ids():
    xml = ET.parse(ROOT / "filters" / "device-diagnostics.xml")
    selects = {
        select.get("Path"): select.text
        for select in xml.getroot().iter("Select")
    }
    assert "Microsoft-Windows-Kernel-PnP/Configuration" in selects
    pnp = selects["Microsoft-Windows-Kernel-PnP/Configuration"]
    assert "EventID=411" in pnp
    assert "EventID=219" in selects["System"]


def test_usb_playbook_documents_verification():
    playbook = next(p for p in load_playbooks() if p["id"] == "usb")
    assert playbook["verification"]["usb_driver_failed"]
    assert "USBHUB3" in playbook["verification"]["not_observed"]


def _battery_evidence(**overrides):
    battery = {
        "design_capacity_mwh": 80000,
        "full_charge_capacity_mwh": 52000,
        "cycle_count": 231,
        "manufacture_date": None,
        "report_date": "2026-10-01",
        "capacity_history": [
            {"period_start": "2025-12-01", "period_end": "2025-12-29",
             "full_charge_mwh": 78500, "design_mwh": 80000},
            {"period_start": "2026-09-01", "period_end": "2026-10-01",
             "full_charge_mwh": 52000, "design_mwh": 80000},
        ],
        "wear_percent": 35.0,
    }
    battery.update(overrides)
    return {"os": "windows", "events": [], "dumps": [], "battery": battery}


def test_battery_early_wear_reports_numbers():
    findings = rules.apply_rules(_battery_evidence())
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    assert patterns[("battery", "battery_wear")]["verdict"] == "fact"
    early = patterns[("battery", "battery_early_wear")]
    assert early["verdict"] == "fact"
    assert "35%" in early["detail"]
    assert "10 months" in early["detail"]
    assert "battery" not in {h["playbook"] for h in findings["healthy"]}


def test_battery_rapid_decline_needs_span_and_drop():
    findings = rules.apply_rules(_battery_evidence())
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    decline = patterns[("battery", "battery_rapid_decline")]
    assert decline["verdict"] == "fact"
    assert "78,500 to 52,000 mWh" in decline["detail"]
    flat = _battery_evidence(capacity_history=[
        {"period_start": "2026-09-01", "period_end": "2026-09-10",
         "full_charge_mwh": 52000, "design_mwh": 80000},
    ])
    flat_findings = rules.apply_rules(flat)
    assert ("battery", "battery_rapid_decline") not in {
        (p["playbook"], p["id"]) for p in flat_findings["patterns"]
    }


def test_battery_missing_numbers_reports_no_data():
    empty = _battery_evidence(
        design_capacity_mwh=None, full_charge_capacity_mwh=None,
        cycle_count=None, capacity_history=[], wear_percent=None,
    )
    findings = rules.apply_rules(empty)
    patterns = {(p["playbook"], p["id"]): p for p in findings["patterns"]}
    assert ("battery", "battery_no_data") in patterns


def test_battery_without_report_stays_honest():
    findings = rules.apply_rules({"os": "windows", "events": [], "dumps": []})
    healthy = {h["playbook"]: h["note"] for h in findings["healthy"]}
    assert healthy["battery"] == "No battery report was uploaded."
