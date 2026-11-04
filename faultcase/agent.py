"""Build a warranty case: rules -> redact -> analysis -> case writing.

``build_case`` computes deterministic findings, redacts everything personal,
asks the evidence_analysis role to interpret and the case_writing role to
produce the manufacturer case. The real serial number never reaches a model:
the model writes ``{{SERIAL}}`` and the placeholder is replaced locally at
the very end, only if a serial was provided.
"""

from __future__ import annotations

import json
import re
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


# Models never see the raw event list: a real System log export can hold
# tens of thousands of events (hundreds of thousands of tokens). They get
# the deterministic findings, per-component counts and a small spread of
# representative events per component.
MAX_EVENTS_PER_COMPONENT = 20
MAX_PROMPT_TOKENS = 30_000
MAX_FIELD_CHARS = 200
MAX_LIST_ITEMS = 24


class PayloadTooLargeError(ValueError):
    """The compact case data still exceeds the prompt token budget."""


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for JSON-heavy text (~3.5 chars/token)."""
    return int(len(text) / 3.5) + 1


def _spread(items: list, limit: int) -> list:
    """Pick up to ``limit`` items evenly across the list (first and last kept)."""
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[0]]
    step = (len(items) - 1) / (limit - 1)
    return [items[round(i * step)] for i in range(limit)]


def _trim(value: object) -> object:
    if isinstance(value, str):
        return value if len(value) <= MAX_FIELD_CHARS else value[:MAX_FIELD_CHARS] + "..."
    if isinstance(value, list):
        return [_trim(v) for v in value[-MAX_LIST_ITEMS:]]
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    return value


def compact_evidence(evidence: dict, per_component: int = MAX_EVENTS_PER_COMPONENT) -> dict:
    """Summarize normalized evidence for the models.

    Per component: total events, counts per kind, first/last time and up to
    ``per_component`` representative events. Stability events that form an
    incident are always preferred as representatives.
    """
    by_playbook: dict = {}
    for event in sorted(evidence.get("events", []), key=lambda e: e["time"]):
        by_playbook.setdefault(event.get("playbook") or "other", []).append(event)
    components = {}
    for playbook, events in sorted(by_playbook.items()):
        kinds: dict = {}
        for event in events:
            kinds[event.get("kind")] = kinds.get(event.get("kind"), 0) + 1
        preferred = [e for e in events if e.get("incident_id")]
        rest = [e for e in events if not e.get("incident_id")]
        sample = _spread(preferred, per_component)
        if len(sample) < per_component:
            sample += _spread(rest, per_component - len(sample))
        sample.sort(key=lambda e: e["time"])
        components[playbook] = {
            "event_count": len(events),
            "kinds": kinds,
            "first_time": events[0]["time"],
            "last_time": events[-1]["time"],
            "sample_events": [
                {
                    key: _trim(event[key])
                    for key in ("time", "kind", "event_id", "code", "level",
                                "params", "fields", "incident_id")
                    if event.get(key) not in (None, {}, [])
                }
                for event in sample
            ],
        }
    compact = {
        "os": evidence.get("os"),
        "total_events": len(evidence.get("events", [])),
        "components": components,
        "dumps": _trim(evidence.get("dumps", [])),
    }
    if evidence.get("battery"):
        compact["battery"] = _trim(evidence["battery"])
    return compact


def _analysis_case_data(findings: dict, evidence: dict, timezone: str | None) -> dict:
    """Case data for evidence_analysis, shrunk until it fits the budget."""
    for per_component in (MAX_EVENTS_PER_COMPONENT, 10, 5, 0):
        data = {
            "findings": findings,
            "evidence": compact_evidence(evidence, per_component),
            "timezone": timezone,
        }
        tokens = estimate_tokens(json.dumps(data))
        if tokens <= MAX_PROMPT_TOKENS:
            return data
    raise PayloadTooLargeError(
        f"the evidence is too large to analyze (about {tokens:,} tokens; "
        f"limit {MAX_PROMPT_TOKENS:,}). Export a shorter period or use the "
        "FaultCase filter so only device events are included"
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


_BUCKET_REF = re.compile(
    r"\s*\(?(?:as defined by |with |by )?FAILURE_(?:BUCKET_ID|ID_HASH)\b[:=]?\s*"
    r"\S*?(?=[.,;)]?(?:\s|$))\)?",
)


def strip_bucket_ids(text: str) -> str:
    """Remove FAILURE_BUCKET_ID / FAILURE_ID_HASH strings from a report.

    The writer prompt forbids them (they identify a failure category, not
    a defect, and confuse support staff); this is the deterministic guard.
    """
    cleaned = _BUCKET_REF.sub("", text)
    return re.sub(r" +([.,;])", r"\1", cleaned)


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
    # Component statuses are for the UI only; models get the findings.
    model_findings = {
        k: v for k, v in clean_findings.items() if k not in ("components",)
    }
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
                _analysis_case_data(model_findings, clean_evidence, timezone),
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
                        "components": [
                            {k: c[k] for k in ("id", "status", "count")}
                            for c in clean_findings.get("components", [])
                        ],
                        "patterns": [
                            {"component": p.get("playbook"),
                             "type": p.get("verdict"), "detail": p.get("detail")}
                            for p in clean_findings.get("patterns", [])
                        ],
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
    report = case["manufacturer_report"]
    for key in ("body_en", "body_es"):
        report[key] = strip_bucket_ids(report[key])
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


COMPONENT_IDS = [
    "stability", "disk", "hardware", "thermal", "wifi", "usb", "battery", "software",
]

EXPLANATION_SCHEMA = {
    "type": "object",
    "required": ["overview", "components", "glossary", "next_steps"],
    "properties": {
        "overview": {"type": "string"},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["component", "meaning", "action"],
                "properties": {
                    "component": {"enum": COMPONENT_IDS},
                    "meaning": {"type": "string"},
                    "action": {"type": "string"},
                },
            },
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["term", "plain"],
                "properties": {
                    "term": {"type": "string"},
                    "plain": {"type": "string"},
                },
            },
        },
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
}


def explain_case(findings: dict, case: dict, ui_language: str = "en") -> dict:
    """Plain-language walkthrough of a finished diagnosis (on demand).

    The model only gets the deterministic findings and the verdict, all
    redacted: never raw events, device details or the serial number.
    """
    clean = redact.redact_obj(findings)
    summary = clean.get("summary", {})
    data = {
        "ui_language": ui_language,
        "verdict": case.get("verdict"),
        "confidence": case.get("confidence"),
        "summary": {
            key: summary.get(key) for key in (
                "total_incidents", "first_incident_date", "last_incident_date",
                "months_span", "incidents_with_dump", "freezes_without_dump",
            )
        },
        "incidents": [
            {"date": i.get("date"), "label": i.get("label"),
             "code_name": next(
                 (x.get("code_name") for x in clean.get("incidents", [])
                  if x.get("date") == i.get("date") and x.get("time") == i.get("time")),
                 None),
             "has_memory_dump": i.get("has_dump")}
            for i in summary.get("incidents", [])
        ],
        "components": [
            {k: c[k] for k in ("id", "status", "count")}
            for c in clean.get("components", [])
        ],
        "patterns": [
            {"component": p.get("playbook"), "type": p.get("verdict"),
             "detail": p.get("detail")}
            for p in clean.get("patterns", [])
        ],
        "healthy_components": sorted({h.get("playbook") for h in clean.get("healthy", [])}),
    }
    system = (PROMPTS_DIR / "explainer.md").read_text(encoding="utf-8")
    explanation, info = call_with_info(
        "explanation",
        [
            {"role": "system", "content": system},
            {"role": "user", "content": _user_content(
                ["overview", "components", "glossary", "next_steps"], data)},
        ],
        EXPLANATION_SCHEMA,
    )
    return {"explanation": explanation, "provider": info["provider"],
            "latency_ms": info["latency_ms"]}
