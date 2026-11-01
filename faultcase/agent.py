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
from faultcase.router import call_with_info

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
CASE_SCHEMA = json.loads((ROOT / "schemas" / "case.schema.json").read_text(encoding="utf-8"))

ANALYSIS_SCHEMA = {
    "type": "object",
    "required": ["verdict", "confidence", "findings", "healthy_components", "missing"],
    "properties": {
        "verdict": {"type": "string"},
        "confidence": {"enum": ["high", "medium", "low"]},
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
    evidence: dict, ui_language: str = "en", device: dict | None = None
) -> dict:
    """Build the warranty case for normalized evidence. Returns case + metadata."""
    findings = rules.apply_rules(evidence)
    clean_findings = redact.redact_obj(findings)
    clean_evidence = redact.redact_obj(evidence)
    clean_device = redact.redact_obj(dict(device or {}))
    serial = clean_device.pop("serial", None)

    system_analysis = (PROMPTS_DIR / "evidence_analysis.md").read_text(encoding="utf-8")
    analysis, analysis_info = call_with_info(
        "evidence_analysis",
        [
            {"role": "system", "content": system_analysis},
            {
                "role": "user",
                "content": json.dumps(
                    {"findings": clean_findings, "evidence": clean_evidence}
                ),
            },
        ],
        ANALYSIS_SCHEMA,
    )

    system_writer = (PROMPTS_DIR / "case_writer.md").read_text(encoding="utf-8")
    case, case_info = call_with_info(
        "case_writing",
        [
            {"role": "system", "content": system_writer},
            {
                "role": "user",
                "content": json.dumps({
                    "analysis": analysis,
                    "device": clean_device,
                    "ui_language": ui_language,
                }),
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
        },
    }
