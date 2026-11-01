"""Agent unit tests with a stubbed router (no network)."""

import json

import pytest
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from faultcase import agent
from faultcase.router import RouterError


@pytest.fixture(autouse=True)
def _single_analysis_mode(monkeypatch):
    monkeypatch.setattr(agent, "analysis_mode", lambda role: "single")


ANALYSIS = {
    "verdict": "likely_driver_fault",
    "confidence": "medium",
    "summary": "The display driver fails repeatedly.",
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


def _case_data(content):
    """Parse the case JSON at the end of a static-first user message."""
    return json.loads(content.split("Case data:\n", 1)[1])


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


def test_device_with_sources_reaches_case_writer(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    agent.build_case(EVIDENCE, device={
        "manufacturer": "LENOVO",
        "bios_version": "LENOVO N3FCN12W",
        "sources": {
            "manufacturer": "windows_system_information",
            "bios_version": "windows_system_information",
        },
    })
    writer_call = next(c for c in captured if c["role"] == "case_writing")
    payload = _case_data(writer_call["messages"][1]["content"])
    assert payload["device"]["bios_version"] == "LENOVO N3FCN12W"
    assert payload["device"]["sources"] == {
        "manufacturer": "windows_system_information",
        "bios_version": "windows_system_information",
    }


def test_analysis_schema_verdict_matches_case_schema():
    case_verdicts = agent.CASE_SCHEMA["properties"]["verdict"]["enum"]
    assert case_verdicts == [
        "likely_hardware_fault", "likely_driver_fault",
        "instability_unclear_cause", "no_relevant_issues",
    ]
    assert agent.ANALYSIS_SCHEMA["properties"]["verdict"] == {"enum": case_verdicts}
    validate(instance=ANALYSIS, schema=agent.ANALYSIS_SCHEMA)
    with pytest.raises(ValidationError):
        validate(
            instance=dict(ANALYSIS, verdict="recurring display driver crashes"),
            schema=agent.ANALYSIS_SCHEMA,
        )


def _opinion(provider, verdict, confidence, summary="opinion summary"):
    data = dict(ANALYSIS, verdict=verdict, confidence=confidence, summary=summary)
    return {
        "provider": provider, "model": f"m-{provider}", "success": True,
        "data": data,
        "info": {"provider": provider, "model": f"m-{provider}",
                 "latency_ms": 100, "prompt_tokens": 50,
                 "completion_tokens": 20, "fallback_used": False},
        "error": None,
    }


def _stub_second_opinion(monkeypatch, captured, results):
    def fake_parallel(role, messages, response_schema):
        captured.append({"role": role, "messages": messages})
        return results
    monkeypatch.setattr(agent, "call_parallel_with_info", fake_parallel)
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    monkeypatch.setattr(agent, "analysis_mode", lambda role: "second_opinion")


def _writer_analysis(captured):
    writer_call = next(c for c in captured if c["role"] == "case_writing")
    return _case_data(writer_call["messages"][1]["content"])["analysis"]


def test_user_messages_put_static_reference_first(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_with_info", _stub_factory(captured))
    agent.build_case(EVIDENCE)
    assert len(captured) == 2
    for call in captured:
        user_content = call["messages"][1]["content"]
        assert user_content.startswith("Static reference (identical for every case).")
        static_end = user_content.index("Case data:\n")
        assert "bad block" in user_content[:static_end]
        case_data = json.loads(user_content[static_end + len("Case data:\n"):])
        assert "findings" in case_data or "analysis" in case_data


def test_second_opinion_agreement_ignores_wording(monkeypatch):
    captured = []
    _stub_second_opinion(monkeypatch, captured, [
        _opinion("baseten", "likely_driver_fault", "high",
                 "Recurrent display crashes"),
        _opinion("fireworks", "likely_driver_fault", "high",
                 "The display driver keeps failing"),
    ])
    result = agent.build_case(EVIDENCE)
    assert result["metadata"]["second_opinion_agreement"] is True
    assert [o["provider"] for o in result["metadata"]["analysis_opinions"]] == [
        "baseten", "fireworks"]
    assert all(o["success"] for o in result["metadata"]["analysis_opinions"])
    merged = _writer_analysis(captured)
    assert merged["confidence"] == "high"
    assert len(merged["findings"]) == 1


def test_second_opinion_disagreement_lowers_confidence(monkeypatch):
    captured = []
    _stub_second_opinion(monkeypatch, captured, [
        _opinion("baseten", "likely_driver_fault", "high"),
        _opinion("fireworks", "likely_hardware_fault", "medium"),
    ])
    result = agent.build_case(EVIDENCE)
    assert result["metadata"]["second_opinion_agreement"] is False
    merged = _writer_analysis(captured)
    assert merged["verdict"] == "likely_driver_fault"
    assert merged["confidence"] == "medium"
    extra = merged["findings"][-1]
    assert extra["type"] == "hypothesis"
    assert "disagreed" in extra["text"]
    assert "baseten" in extra["text"] and "fireworks" in extra["text"]
    assert "likely_driver_fault" in extra["text"]
    assert "likely_hardware_fault" in extra["text"]


def test_second_opinion_confidence_mismatch_disagrees(monkeypatch):
    captured = []
    _stub_second_opinion(monkeypatch, captured, [
        _opinion("baseten", "likely_driver_fault", "high"),
        _opinion("fireworks", "likely_driver_fault", "medium"),
    ])
    result = agent.build_case(EVIDENCE)
    assert result["metadata"]["second_opinion_agreement"] is False
    assert _writer_analysis(captured)["confidence"] == "medium"


def test_second_opinion_single_survivor_is_used(monkeypatch):
    captured = []
    _stub_second_opinion(monkeypatch, captured, [
        {"provider": "baseten", "model": "m-baseten", "success": False,
         "data": None, "info": None, "error": "RuntimeError: baseten is down"},
        _opinion("fireworks", "likely_driver_fault", "low"),
    ])
    result = agent.build_case(EVIDENCE)
    assert result["metadata"]["second_opinion_agreement"] is None
    opinions = result["metadata"]["analysis_opinions"]
    assert [o["success"] for o in opinions] == [False, True]
    assert "baseten is down" in opinions[0]["error"]
    assert _writer_analysis(captured)["verdict"] == "likely_driver_fault"


def test_second_opinion_both_fail_raises(monkeypatch):
    captured = []
    _stub_second_opinion(monkeypatch, captured, [
        {"provider": "baseten", "model": "m", "success": False,
         "data": None, "info": None, "error": "baseten is down"},
        {"provider": "fireworks", "model": "m", "success": False,
         "data": None, "info": None, "error": "fireworks is down"},
    ])
    with pytest.raises(RouterError, match="evidence_analysis"):
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
