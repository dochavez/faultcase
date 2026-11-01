"""Map raw adapter events and dumps to schemas/evidence.schema.json.

Each raw event is matched against playbooks/*.yaml by event_id AND provider
(``provider_contains`` or ``provider_contains_any``, case-insensitive) and
gets its ``kind`` and ``playbook``. Unmatched events are dropped and counted
as noise. Events 41 and 6008 less than 60 seconds apart share an incident;
a dump joins the incident whose event 41 parameters match its bugcheck
parameters (compared as normalized lowercase hex without leading zeros).
The output is validated against the evidence schema before it is returned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import FormatChecker, validate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAYBOOKS_DIR = ROOT / "playbooks"
DEFAULT_SCHEMA_PATH = ROOT / "schemas" / "evidence.schema.json"

REBOOT_KIND = "unexpected_reboot"
SHUTDOWN_KIND = "unexpected_shutdown"
INCIDENT_WINDOW_SECONDS = 60

DUMP_FIELDS = (
    "file", "time", "bugcheck_code", "params", "image_name", "symbol_name",
    "failure_bucket_id", "failure_id_hash", "process_name", "driver_timestamp",
)


@dataclass
class NormalizeResult:
    evidence: dict
    noise: int = 0


def load_playbooks(path: str | Path | None = None) -> list[dict]:
    """Load every playbook from the playbooks directory, sorted by filename."""
    playbooks = []
    for file in sorted(Path(path or DEFAULT_PLAYBOOKS_DIR).glob("*.yaml")):
        with open(file, encoding="utf-8") as fh:
            playbooks.append(yaml.safe_load(fh))
    return playbooks


def _matches(entry: dict, event: dict) -> bool:
    if entry.get("event_id") != event.get("event_id"):
        return False
    source = (event.get("source") or "").lower()
    if "provider_contains" in entry:
        needle = (entry["provider_contains"] or "").lower()
        return bool(needle) and needle in source
    if "provider_contains_any" in entry:
        needles = entry["provider_contains_any"] or []
        return any(n and n.lower() in source for n in needles)
    return False


def normalize_hex(value: object) -> str:
    """Normalize a hex value: lowercase, no 0x prefix, no leading zeros."""
    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text.lstrip("0") or "0"


def _event_params(fields: dict) -> list[str] | None:
    bugcheck = [fields.get(f"BugcheckParameter{i}") for i in range(1, 5)]
    if all(v is not None and str(v) != "" for v in bugcheck):
        return [str(v) for v in bugcheck]
    raw = fields.get("params")
    if isinstance(raw, list) and len(raw) == 4:
        return [str(v) for v in raw]
    return None


def _event_code(fields: dict) -> int | None:
    if "BugcheckCode" not in fields:
        return None
    try:
        return int(fields["BugcheckCode"])
    except (TypeError, ValueError):
        return None


def _assign_incidents(events: list[dict]) -> None:
    counter = 0

    def new_incident() -> str:
        nonlocal counter
        counter += 1
        return f"inc-{counter:03d}"

    reboots: list[tuple[datetime, str]] = []
    for event in sorted(events, key=lambda e: datetime.fromisoformat(e["time"])):
        moment = datetime.fromisoformat(event["time"])
        if event["kind"] == REBOOT_KIND:
            event["incident_id"] = new_incident()
            reboots.append((moment, event["incident_id"]))
        elif event["kind"] == SHUTDOWN_KIND:
            candidates = [
                (abs((moment - reboot_time).total_seconds()), incident_id)
                for reboot_time, incident_id in reboots
            ]
            best = min(candidates) if candidates else None
            if best is not None and best[0] < INCIDENT_WINDOW_SECONDS:
                event["incident_id"] = best[1]
            else:
                event["incident_id"] = new_incident()
        else:
            event["incident_id"] = new_incident()


def _link_dumps(dumps: list[dict], events: list[dict]) -> list[dict]:
    reboot_params = {}
    for event in events:
        if event["kind"] == REBOOT_KIND and event.get("params"):
            reboot_params[event["incident_id"]] = [
                normalize_hex(p) for p in event["params"]
            ]
    linked = []
    for dump in dumps:
        entry = {
            key: dump[key] for key in DUMP_FIELDS if dump.get(key) is not None
        }
        params = dump.get("params")
        if isinstance(params, list) and len(params) == 4:
            wanted = [normalize_hex(p) for p in params]
            for incident_id, reboot in reboot_params.items():
                if wanted == reboot:
                    entry["incident_id"] = incident_id
                    break
        linked.append(entry)
    return linked


def normalize(
    events: list[dict],
    dumps: list[dict] | None = None,
    *,
    os_name: str = "windows",
    collected_at: str | None = None,
    playbooks_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> NormalizeResult:
    """Normalize raw events and dumps into validated evidence."""
    playbooks = load_playbooks(playbooks_dir)
    normalized = []
    noise = 0
    for event in events:
        found = None
        for playbook in playbooks:
            for entry in playbook.get("evidence", []):
                if _matches(entry, event):
                    found = (playbook["id"], entry)
                    break
            if found is not None:
                break
        if found is None:
            noise += 1
            continue
        playbook_id, entry = found
        fields = event.get("fields", {}) or {}
        item: dict = {
            "time": event["time"],
            "source": event["source"],
            "event_id": event["event_id"],
            "kind": entry["id"],
            "playbook": playbook_id,
            "code": _event_code(fields),
            "fields": (
                {k: fields[k] for k in entry["fields"] if k in fields}
                if "fields" in entry else dict(fields)
            ),
        }
        params = _event_params(fields)
        if params is not None:
            item["params"] = params
        normalized.append(item)
    _assign_incidents(normalized)
    evidence = {
        "os": os_name,
        "collected_at": collected_at or datetime.now(timezone.utc).isoformat(),
        "events": normalized,
        "dumps": _link_dumps(list(dumps or []), normalized),
    }
    with open(schema_path or DEFAULT_SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    validate(instance=evidence, schema=schema, format_checker=FormatChecker())
    return NormalizeResult(evidence=evidence, noise=noise)
