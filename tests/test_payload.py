"""Compact model payload, incident grouping and known-benign events."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from faultcase import agent, normalize, rules
from faultcase.adapters.windows.evtx import parse_record_xml
from faultcase.router import _error_fields
from tests.test_agent import _case_data, _stub_factory


@pytest.fixture(autouse=True)
def _single_analysis_mode(monkeypatch):
    monkeypatch.setattr(agent, "analysis_mode", lambda role: "single")


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _raw(minutes, source, event_id, fields=None, level=None):
    event = {
        "time": (START + timedelta(minutes=minutes)).isoformat(),
        "log": "System", "source": source, "event_id": event_id,
        "fields": fields or {},
    }
    if level is not None:
        event["level"] = level
    return event


def _reboot(minutes):
    return _raw(minutes, "Microsoft-Windows-Kernel-Power", 41,
                {"BugcheckCode": 278, "SleepInProgress": 0}, level=1)


def _big_evidence(n_noise=20_000):
    events = [_reboot(i * 30 * 24 * 60) for i in range(6)]
    for i in range(n_noise):
        events.append(_raw(i * 7, "Microsoft-Windows-WLAN-AutoConfig", 8003,
                           {"Reason": "The network is disconnected."}, level=4))
    return normalize.normalize(events).evidence


def test_twenty_thousand_events_fit_the_token_budget(monkeypatch):
    evidence = _big_evidence()
    assert len(evidence["events"]) == 20_006
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    agent.build_case(evidence, "en", timezone="UTC")
    content = captured[0]["messages"][1]["content"]
    assert agent.estimate_tokens(content) <= agent.MAX_PROMPT_TOKENS
    data = _case_data(content)
    components = data["evidence"]["components"]
    assert components["wifi"]["event_count"] == 20_000
    for component in components.values():
        assert len(component["sample_events"]) <= agent.MAX_EVENTS_PER_COMPONENT
    assert data["findings"]["summary"]["total_incidents"] == 6


def test_oversized_payload_raises_before_any_model_call(monkeypatch):
    called = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(called))
    monkeypatch.setattr(agent, "MAX_PROMPT_TOKENS", 200)
    with pytest.raises(agent.PayloadTooLargeError):
        agent.build_case(_big_evidence(50), "en", timezone="UTC")
    assert called == []


def test_spread_keeps_first_and_last():
    picked = agent._spread(list(range(100)), 5)
    assert picked[0] == 0 and picked[-1] == 99 and len(picked) == 5


def test_only_stability_events_form_incidents():
    evidence = _big_evidence(30)
    ids = {e["incident_id"] for e in evidence["events"] if e["incident_id"]}
    assert len(ids) == 6
    assert all(e["incident_id"] is None
               for e in evidence["events"] if e["playbook"] == "wifi")
    findings = rules.apply_rules(evidence)
    assert findings["summary"]["total_incidents"] == 6
    assert all(i["code_hex"] for i in findings["incidents"])


def test_bugcheck_1001_joins_nearest_reboot():
    events = [
        _reboot(0),
        _raw(4, "Microsoft-Windows-WER-SystemErrorReporting", 1001, {}, level=2),
        _reboot(60 * 24),
    ]
    evidence = normalize.normalize(events).evidence
    by_kind = {e["kind"]: e["incident_id"] for e in evidence["events"]}
    assert by_kind["bugcheck_logged"] == evidence["events"][0]["incident_id"]
    assert rules.apply_rules(evidence)["summary"]["total_incidents"] == 2


def test_known_benign_events_are_not_counted():
    pnp = "Microsoft-Windows-Kernel-PnP"
    events = [
        _raw(1, pnp, 411, {"DeviceInstanceId": "ROOT\\VMS_VSMP\\0000"}, level=2),
        _raw(2, pnp, 411, {"DeviceInstanceId": "ROOT\\VMS_VSMP\\0001"}, level=2),
        _raw(3, pnp, 219, {"FailureName": "\\Driver\\WUDFRd"}, level=3),
        _raw(4, "Ntfs", 98, {}, level=4),
        _raw(5, "Microsoft-Windows-WindowsUpdateClient", 19, {}, level=4),
        _raw(6, "Netwtw14", 5002, {}, level=4),
    ]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    status = {c["id"]: c for c in findings["components"]}
    assert status["usb"]["status"] == "ok" and status["usb"]["ignored"] == 3
    assert status["disk"]["status"] == "ok"
    assert status["software"]["status"] == "ok"
    assert status["wifi"]["status"] == "ok"
    assert not [p for p in findings["patterns"] if p["playbook"] != "stability"]


def test_ntfs_98_counts_at_warning_level():
    events = [_raw(1, "Ntfs", 98, {}, level=3)]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    status = {c["id"]: c["status"] for c in findings["components"]}
    assert status["disk"] == "attention"


def test_component_statuses_cover_every_playbook():
    evidence = _big_evidence(30)
    findings = rules.apply_rules(evidence)
    status = {c["id"]: c["status"] for c in findings["components"]}
    assert status["stability"] == "problem"
    assert status["battery"] == "no_data"
    assert set(status.values()) <= {"problem", "attention", "ok", "no_data"}


def test_evtx_level_is_captured():
    xml = (
        '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
        '<System><Provider Name="Ntfs"/><EventID>98</EventID><Level>4</Level>'
        '<TimeCreated SystemTime="2026-05-01T10:00:00.000000+00:00"/>'
        '<Channel>System</Channel></System><EventData/></Event>'
    )
    assert parse_record_xml(xml)["level"] == 4


def test_router_error_fields_hide_secrets():
    fields = _error_fields(RuntimeError("bad key Bearer abcdefghijklmnop123"))
    assert fields["error_type"] == "RuntimeError"
    assert "abcdefghijklmnop123" not in fields["error_message"]


def _status(events):
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    return {c["id"]: c for c in findings["components"]}, findings


def test_real_case_noise_is_ignored():
    wlan = "Microsoft-Windows-WLAN-AutoConfig"
    pnp = "Microsoft-Windows-Kernel-PnP"
    events = [
        _raw(1, "Netwaw18", 6062, {}, level=3),
        _raw(2, wlan, 8003, {"ReasonCode": "3"}, level=4),
        _raw(3, wlan, 8003, {"ReasonCode": "11"}, level=4),
        _raw(4, wlan, 8002, {"ReasonCode": "229396"}, level=2),
        _raw(5, pnp, 411, {"DeviceInstanceId": "PCI\\VEN_8086&DEV_7D67\\3&1"}, level=2),
        _raw(6, "Ntfs", 55, {"DeviceName": "\\Device\\HarddiskVolumeShadowCopy5"}, level=2),
    ]
    status, _ = _status(events)
    assert status["wifi"]["status"] == "ok" and status["wifi"]["ignored"] == 4
    assert status["usb"]["status"] == "ok"
    assert status["disk"]["status"] == "ok"


def test_real_usb_and_wifi_failures_still_count():
    events = [
        _raw(1, "Microsoft-Windows-Kernel-PnP", 411,
             {"DeviceInstanceId": "USB\\VID_1234&PID_ABCD\\1"}, level=2),
        _raw(2, "Microsoft-Windows-WLAN-AutoConfig", 8003, {"ReasonCode": "0"}, level=4),
    ]
    status, _ = _status(events)
    assert status["usb"]["status"] == "attention"
    assert status["wifi"]["status"] == "attention"


def test_disk_errors_on_secondary_or_removable_drive_need_attention_only():
    data = "<string>\\Device\\Harddisk1\\DR2</string>"
    events = [_raw(i, "disk", 51, {"Data0": data}, level=3) for i in range(3)]
    events += [_raw(10 + i, "disk", 51, {"Data0": f"<string>\\DR{3 + i}</string>"}, level=3)
               for i in range(3)]
    status, findings = _status(events)
    assert status["disk"]["status"] == "attention"
    details = [p["detail"] for p in findings["patterns"] if p["playbook"] == "disk"]
    assert "3 paging_error events on disk 1, 2026-01-01..2026-01-01" in details
    assert any("removable drive" in d for d in details)


def test_disk_errors_on_system_disk_are_a_problem():
    events = [_raw(1, "disk", 51, {"Data0": "<string>\\Device\\Harddisk0\\DR0</string>"}, level=3)]
    status, _ = _status(events)
    assert status["disk"]["status"] == "problem"


def test_nvidia_gpu_resets_are_reported():
    events = [_raw(i, "nvlddmkm", 153,
                   {"Data0": "<string>GpuRcReset TDR occurred on GPUID:200</string>"},
                   level=2) for i in range(4)]
    _, findings = _status(events)
    gpu = [p for p in findings["patterns"] if p["id"] == "gpu_resets"]
    assert gpu and gpu[0]["verdict"] == "fact"
    assert gpu[0]["detail"].startswith("4 display driver resets")
    assert findings["summary"]["total_incidents"] == 0



def test_shutdown_without_crash_code_gets_a_label():
    events = [_raw(0, "EventLog", 6008, {}, level=2)]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    incident = findings["incidents"][0]
    assert incident["code_hex"] is None
    assert incident["label_key"] == "unexpected_shutdown"
    assert findings["summary"]["incidents"][0]["label"] == "Unexpected shutdown (no crash code)"



def _shutdown(minutes, alive_minutes_before):
    import base64, struct
    alive = START + timedelta(minutes=minutes - alive_minutes_before)
    st = struct.pack("<8H", alive.year, alive.month, 0, alive.day,
                     alive.hour, alive.minute, alive.second, 0)
    return _raw(minutes, "EventLog", 6008,
                {"Binary": base64.b64encode(st + st).decode()}, level=2)


def test_long_power_off_before_boot_is_a_power_loss_hypothesis():
    events = [_shutdown(0, 600), _shutdown(3000, 240), _shutdown(9000, 3)]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    offs = sorted(i["off_minutes"] for i in findings["incidents"])
    assert offs == [3, 240, 600]
    pattern = next(p for p in findings["patterns"] if p["id"] == "power_loss_shutdowns")
    assert pattern["verdict"] == "hypothesis" and pattern["detail"].startswith("2/3 ")
    assert findings["summary"]["shutdowns_after_long_power_off"] == 2


def test_bad_6008_binary_is_ignored():
    events = [_raw(0, "EventLog", 6008, {"Binary": "not-base64"}, level=2)]
    findings = rules.apply_rules(normalize.normalize(events).evidence)
    assert findings["incidents"][0]["off_minutes"] is None
