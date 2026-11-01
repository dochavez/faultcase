"""Agent unit tests with a stubbed router (no network)."""

import pytest
from jsonschema.exceptions import ValidationError

from faultcase import agent

ANALYSIS = {
    "verdict": "recurring display driver crashes",
    "confidence": "medium",
    "findings": [{"text": "nvlddmkm.sys crashed twice", "type": "fact"}],
    "healthy_components": ["disk"],
    "missing": ["manufacturer hardware scan"],
}

CASE = {
    "verdict": "likely_driver_fault",
    "confidence": "medium",
    "user_summary": "Your laptop restarts because the display driver fails.",
    "findings": [{"text": "The display driver failed twice.", "type": "fact",
                  "evidence": ["inc-001"]}],
    "checklist": [{"step": "Install the manufacturer driver.", "status": "pending"}],
    "manufacturer_report": {
        "subject": "Warranty case for S/N {{SERIAL}}",
        "body_en": "Unit {{SERIAL}} reboots unexpectedly.",
        "body_es": "La unidad {{SERIAL}} se reinicia inesperadamente.",
    },
}

EVIDENCE = {
    "os": "windows",
    "collected_at": "2026-05-02T00:00:00+00:00",
    "events": [{
        "time": "2026-05-01T10:00:00+00:00",
        "source": "Microsoft-Windows-Kernel-Power",
        "event_id": 41,
        "kind": "unexpected_reboot",
        "playbook": "stability",
        "code": 307,
        "params": ["0x1", "0x1e00", "0x0", "0x0"],
        "fields": {"BugcheckCode": 307, "SleepInProgress": 0},
        "incident_id": "inc-001",
    }],
    "dumps": [{
        "file": "050126-00000-01.dmp",
        "bugcheck_code": "133",
        "params": ["1", "1e00", "0", "0"],
        "image_name": "nvlddmkm.sys",
        "process_name": "C:\\Users\\janedoe\\game.exe",
        "incident_id": "inc-001",
    }],
}


def _stub_factory(captured, case=None):
    def fake_call(role, messages, response_schema):
        captured.append({"role": role, "messages": messages})
        if role == "evidence_analysis":
            data = ANALYSIS
            info = {"provider": "baseten", "model": "m1", "latency_ms": 100,
                    "prompt_tokens": 50, "completion_tokens": 20,
                    "fallback_used": False}
        else:
            data = CASE if case is None else case
            info = {"provider": "meta", "model": "m2", "latency_ms": 200,
                    "prompt_tokens": 80, "completion_tokens": 40,
                    "fallback_used": False}
        return data, info
    return fake_call


def test_build_case_returns_case_and_metadata(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    result = agent.build_case(EVIDENCE, device={"manufacturer": "Lenovo"})
    assert result["case"]["verdict"] == "likely_driver_fault"
    assert result["metadata"] == {
        "providers_used": ["baseten", "meta"],
        "total_latency_ms": 300,
        "total_tokens": 190,
        "prompt_tokens": 130,
        "completion_tokens": 60,
    }
    assert [c["role"] for c in captured] == ["evidence_analysis", "case_writing"]


def test_personal_data_and_serial_never_reach_models(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    agent.build_case(EVIDENCE, device={"serial": "SECRET123"})
    payload = "".join(m["content"] for c in captured for m in c["messages"])
    assert "janedoe" not in payload
    assert "SECRET123" not in payload


def test_serial_replaced_locally_only_when_provided(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    with_serial = agent.build_case(EVIDENCE, device={"serial": "SECRET123"})
    assert "{{SERIAL}}" not in str(with_serial["case"])
    assert "SECRET123" in with_serial["case"]["manufacturer_report"]["body_en"]
    without_serial = agent.build_case(EVIDENCE)
    assert "{{SERIAL}}" in without_serial["case"]["manufacturer_report"]["body_en"]


def test_invalid_case_output_raises(monkeypatch):
    captured = []
    monkeypatch.setattr(
        agent, "call_with_info", _stub_factory(captured, case={"verdict": "bogus"})
    )
    with pytest.raises(ValidationError):
        agent.build_case(EVIDENCE)


def test_cross_machine_defect_claim_detector():
    from tests.helpers import cross_machine_defect_claim

    assert cross_machine_defect_claim(
        "This proves the same defect as other machines."
    ) is not None
    assert cross_machine_defect_claim(
        "Same failure category, not proof of the same defect as other machines."
    ) is None
    assert cross_machine_defect_claim("The same module failed twice.") is None
