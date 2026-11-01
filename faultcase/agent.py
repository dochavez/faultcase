"""Build a warranty case: rules -> redact -> analysis -> case writing.

``build_case`` computes deterministic findings, redacts everything personal,
asks the evidence_analysis role to interpret and the case_writing role to
produce the manufacturer case. The real serial number never reaches a model:
the model writes ``{{SERIAL}}`` and the placeholder is replaced locally at
the very end, only if a serial was provided.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from faultcase import redact, rules
from faultcase.normalize import load_playbooks
from faultcase.router import RouterError, analysis_mode, call_parallel_with_info, call_with_info

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
CASE_SCHEMA = json.loads((ROOT / "schemas" / "case.schema.json").read_text(encoding="utf-8"))
CASE_VERDICTS = CASE_SCHEMA["properties"]["verdict"]["enum"]

ANALYSIS_SCHEMA = {
    "type": "object",
    "required": ["verdict", "confidence", "findings", "healthy_components", "missing"],
    "properties": {
        "verdict": {"enum": CASE_VERDICTS},
        "confidence": {
            # Levels preferred; numbers accepted and normalized because
            # some models emit 0.8 and stall when constrained to strings.
            "anyOf": [
                {"enum": ["high", "medium", "low"]},
                {"type": "number"},
                {"type": "string", "pattern": "^[0-9]*\\.?[0-9]+$"},
            ],
        },
        "summary": {
            "type": "string",
            "description": "optional free-text description of the verdict",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "type"],
                "properties": {
                    "text": {"type": "string"},
                    "type": {"enum": ["fact", "hypothesis"]},
                },
            },
        },
        "healthy_components": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
    },
}


def _static_reference(schema_keys: list) -> str:
    """Build the static (cacheable) prefix shared by every request of a role.

    Playbook rules and the expected output shape are identical for all
    cases, so providers can reuse the cached prefix; case data always
    comes last in the user message.
    """
    lines = ["Static reference (identical for every case).", "", "Playbook rules:"]
    for playbook in load_playbooks():
        for rule in playbook.get("rules", []):
            lines.append(f"- {playbook['id']}: {rule}")
    lines += [
        "",
        "Return a JSON object with exactly these top-level keys: "
        + ", ".join(schema_keys)
        + ".",
    ]
    return "\n".join(lines)


def _user_content(schema_keys: list, case_data: dict) -> str:
    return (
        _static_reference(schema_keys) + "\n\nCase data:\n" + json.dumps(case_data)
    )


CONFIDENCE_LEVELS = ["low", "medium", "high"]


def _normalize_confidence(value) -> str:
    """Map a model confidence (level, number or numeric string) to a level.

    Numbers use thirds (unknown values fail safe to low); values above 1
    are read as percentages.
    """
    if isinstance(value, str):
        if value in CONFIDENCE_LEVELS:
            return value
        try:
            value = float(value)
        except ValueError:
            return "low"
    if isinstance(value, bool):
        return "low"
    if isinstance(value, (int, float)):
        if value > 1:
            value = value / 100
        if value >= 0.66:
            return "high"
        if value >= 0.33:
            return "medium"
        return "low"
    return "low"


def _lower_confidence(confidence: str) -> str:
    try:
        index = CONFIDENCE_LEVELS.index(confidence)
    except ValueError:
        return "low"
    return CONFIDENCE_LEVELS[max(0, index - 1)]


def _reconcile_opinions(results: list) -> tuple:
    """Merge parallel analyses into (analysis, info, metadata).

    Opinions agree when both the verdict enum and the confidence level
    match: agreement keeps the primary verdict and confidence,
    disagreement lowers confidence one level and adds a hypothesis
    finding. Free-text wording (summary, findings) is ignored. A single
    surviving opinion is used as-is.
    """
    succeeded = [r for r in results if r["success"]]
    if not succeeded:
        detail = "; ".join(f"{r['provider']} ({r['error']})" for r in results)
        raise RouterError(
            f"all providers failed for role 'evidence_analysis': {detail or 'empty route'}"
        )
    for result in succeeded:
        result["data"]["confidence"] = _normalize_confidence(
            result["data"].get("confidence")
        )
    opinions = []
    for result in results:
        entry = {
            "provider": result["provider"], "model": result["model"],
            "success": result["success"],
        }
        if result["success"]:
            entry.update({
                "verdict": result["data"]["verdict"],
                "confidence": result["data"]["confidence"],
                "latency_ms": result["info"]["latency_ms"],
                "prompt_tokens": result["info"]["prompt_tokens"],
                "completion_tokens": result["info"]["completion_tokens"],
            })
        else:
            entry["error"] = result["error"]
        opinions.append(entry)
    primary = succeeded[0]
    analysis = dict(primary["data"])
    agreement = None
    if len(succeeded) >= 2:
        first, second = succeeded[0], succeeded[1]
        agreement = (
            first["data"]["verdict"] == second["data"]["verdict"]
            and first["data"]["confidence"] == second["data"]["confidence"]
        )
        if not agreement:
            analysis["confidence"] = _lower_confidence(first["data"]["confidence"])
            analysis["findings"] = list(first["data"]["findings"]) + [{
                "text": (
                    "Two independent analyses disagreed "
                    f"({first['provider']}: {first['data']['verdict']} "
                    f"with {first['data']['confidence']} confidence; "
                    f"{second['provider']}: {second['data']['verdict']} "
                    f"with {second['data']['confidence']} confidence); "
                    "treat the root cause as uncertain."
                ),
                "type": "hypothesis",
            }]
    info = {
        "provider": primary["provider"], "model": primary["model"],
        "latency_ms": max(r["info"]["latency_ms"] for r in succeeded),
        "prompt_tokens": sum(r["info"]["prompt_tokens"] for r in succeeded),
        "completion_tokens": sum(r["info"]["completion_tokens"] for r in succeeded),
        "fallback_used": False,
    }
    metadata = {
        "analysis_opinions": opinions,
        "second_opinion_agreement": agreement,
    }
    return analysis, info, metadata


def _replace_serial(obj: object, serial: str) -> object:
    if isinstance(obj, str):
        return obj.replace("{{SERIAL}}", serial)
    if isinstance(obj, dict):
        return {key: _replace_serial(value, serial) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_replace_serial(value, serial) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_replace_serial(value, serial) for value in obj)
    return obj


def build_case(
    evidence: dict,
    ui_language: str = "en",
    device: dict | None = None,
    timezone: str | None = None,
) -> dict:
    """Build the warranty case for normalized evidence. Returns case + metadata."""
    findings = rules.apply_rules(evidence, tz=timezone)
    clean_findings = redact.redact_obj(findings)
    clean_evidence = redact.redact_obj(evidence)
    clean_device = redact.redact_obj(dict(device or {}))
    serial = clean_device.pop("serial", None)

    system_analysis = (PROMPTS_DIR / "evidence_analysis.md").read_text(encoding="utf-8")
    analysis_messages = [
        {"role": "system", "content": system_analysis},
        {
            "role": "user",
            "content": _user_content(
                ["verdict", "confidence", "findings", "healthy_components",
                 "missing"],
                {"findings": clean_findings, "evidence": clean_evidence,
                 "timezone": timezone},
            ),
        },
    ]
    opinion_metadata: dict = {}
    if analysis_mode("evidence_analysis") == "second_opinion":
        results = call_parallel_with_info(
            "evidence_analysis", analysis_messages, ANALYSIS_SCHEMA
        )
        analysis, analysis_info, opinion_metadata = _reconcile_opinions(results)
    else:
        analysis, analysis_info = call_with_info(
            "evidence_analysis", analysis_messages, ANALYSIS_SCHEMA
        )
    analysis["confidence"] = _normalize_confidence(analysis.get("confidence"))

    system_writer = (PROMPTS_DIR / "case_writer.md").read_text(encoding="utf-8")
    case, case_info = call_with_info(
        "case_writing",
        [
            {"role": "system", "content": system_writer},
            {
                "role": "user",
                "content": _user_content(
                    sorted(CASE_SCHEMA.get("properties", {})),
                    {
                        "analysis": analysis,
                        "summary": clean_findings["summary"],
                        "device": clean_device,
                        "ui_language": ui_language,
                        "timezone": timezone,
                    },
                ),
            },
        ],
        CASE_SCHEMA,
    )
    validate(instance=case, schema=CASE_SCHEMA)
    if serial:
        case = _replace_serial(case, serial)
    prompt_tokens = analysis_info["prompt_tokens"] + case_info["prompt_tokens"]
    completion_tokens = (
        analysis_info["completion_tokens"] + case_info["completion_tokens"]
    )
    return {
        "case": case,
        "metadata": {
            "providers_used": [analysis_info["provider"], case_info["provider"]],
            "total_latency_ms": analysis_info["latency_ms"] + case_info["latency_ms"],
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            **opinion_metadata,
        },
    }
