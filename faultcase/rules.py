"""Deterministic rules engine: apply playbooks to normalized evidence.

Computes per-incident facts (dates, decimal-to-hex codes, power transitions,
linked dumps), evaluates each playbook's patterns and lists healthy
components. Pure Python: this module never calls a model. Every pattern is
labeled "fact" or "hypothesis"; power_transition is always a hypothesis.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from faultcase.i18n import INCIDENT_LABELS
from faultcase.normalize import load_playbooks

STABILITY = "stability"
REBOOT_KIND = "unexpected_reboot"
REPETITION_MIN_INCIDENTS = 3
REPETITION_WINDOW_DAYS = 90


def _sleep_in_progress(event: dict) -> bool:
    try:
        return int(event.get("fields", {}).get("SleepInProgress", 0)) > 0
    except (TypeError, ValueError):
        return False


def _incident_date(time_str: str, tz: str | None) -> str:
    if not tz:
        return time_str[:10]
    return datetime.fromisoformat(time_str).astimezone(ZoneInfo(tz)).date().isoformat()


def _incident_time(time_str: str, tz: str | None) -> str:
    if not tz:
        return time_str[11:19]
    return datetime.fromisoformat(time_str).astimezone(ZoneInfo(tz)).time().isoformat(
        timespec="seconds"
    )


def _build_incidents(
    events: list[dict], dumps: list[dict], codes: dict, tz: str | None
) -> list[dict]:
    dumps_by_incident = {}
    for dump in sorted(dumps, key=lambda d: d.get("file") or ""):
        incident_id = dump.get("incident_id")
        if incident_id and incident_id not in dumps_by_incident:
            dumps_by_incident[incident_id] = dump
    grouped: dict = {}
    for event in events:
        if event.get("incident_id") is None:
            continue
        grouped.setdefault(event.get("incident_id"), []).append(event)
    incidents = []
    for incident_id in sorted(grouped):
        group = grouped[incident_id]
        reboots = [e for e in group if e.get("kind") == REBOOT_KIND]
        main = reboots[0] if reboots else min(group, key=lambda e: e["time"])
        code = main.get("code")
        info = codes.get(code, {}) if isinstance(code, int) else {}
        dump = dumps_by_incident.get(incident_id, {})
        incidents.append({
            "incident_id": incident_id,
            "date": _incident_date(main["time"], tz),
            "time": _incident_time(main["time"], tz),
            "code": code,
            "code_hex": hex(code) if isinstance(code, int) else None,
            "code_name": info.get("name"),
            "explanation": info.get("explanation"),
            "power_transition": any(_sleep_in_progress(e) for e in reboots),
            "dump_module": dump.get("image_name"),
            "driver_timestamp": dump.get("driver_timestamp"),
            "params": main.get("params"),
        })
    return sorted(incidents, key=lambda i: i["date"])


def _stability_patterns(incidents: list[dict], dumps: list[dict]) -> list[dict]:
    patterns = []
    dates = sorted(date.fromisoformat(i["date"]) for i in incidents)
    for index, start in enumerate(dates):
        inside = [d for d in dates[index:] if (d - start).days <= REPETITION_WINDOW_DAYS]
        if len(inside) >= REPETITION_MIN_INCIDENTS:
            patterns.append({
                "id": "repetition",
                "playbook": STABILITY,
                "verdict": "fact",
                "detail": f"{len(inside)} incidents within 90 days ({start}..{inside[-1]})",
            })
            break
    modules = [d.get("image_name") for d in dumps if d.get("image_name")]
    counts = Counter(modules)
    common = sorted(counts, key=lambda m: (-counts[m], m))[0] if counts else None
    if common is not None and counts[common] >= 2:
        patterns.append({
            "id": "same_module",
            "playbook": STABILITY,
            "verdict": "fact",
            "detail": f"{counts[common]} dumps with {common}",
        })
    timestamps = []
    for dump in sorted(dumps, key=lambda d: d.get("file") or ""):
        stamp = dump.get("driver_timestamp")
        if dump.get("image_name") == common and stamp and stamp not in timestamps:
            timestamps.append(stamp)
    if common is not None and len(timestamps) >= 2:
        patterns.append({
            "id": "persists_across_driver_versions",
            "playbook": STABILITY,
            "verdict": "fact",
            "detail": f"{common} failed with {len(timestamps)} driver timestamps: "
                      + ", ".join(timestamps),
        })
    transitions = sum(1 for i in incidents if i["power_transition"])
    if incidents and transitions / len(incidents) >= 0.5:
        patterns.append({
            "id": "power_transition",
            "playbook": STABILITY,
            "verdict": "hypothesis",
            "detail": f"{transitions}/{len(incidents)} incidents during a power transition",
        })
    return patterns


WIFI = "wifi"
WIFI_DROP_KINDS = ("wifi_disconnected", "wifi_connect_failed")
WIFI_DRIVER_KINDS = ("wifi_driver_error", "wifi_driver_warning")
RESUME_AFTER_SECONDS = 600

# Playbooks with dedicated pattern functions (skipped by the generic counter).
DEDICATED_PATTERNS = {WIFI}


def _wifi_patterns(events: list[dict]) -> list[dict]:
    wifi = [e for e in events if e.get("playbook") == WIFI]
    if not wifi:
        return []
    patterns = []
    drops = [e for e in wifi if e.get("kind") in WIFI_DROP_KINDS]
    driver = [e for e in wifi if e.get("kind") in WIFI_DRIVER_KINDS]
    patterns.append({
        "id": "wifi_events",
        "playbook": WIFI,
        "verdict": "fact",
        "detail": f"{len(drops)} Wi-Fi disconnections or failures, "
                  f"{len(driver)} driver warnings or errors",
    })
    by_day: dict = {}
    for event in drops:
        by_day.setdefault(event["time"][:10], 0)
        by_day[event["time"][:10]] += 1
    worst = max(by_day.items(), key=lambda kv: (kv[1], kv[0])) if by_day else None
    if worst is not None and worst[1] >= 3:
        patterns.append({
            "id": "wifi_frequent_disconnects",
            "playbook": WIFI,
            "verdict": "fact",
            "detail": f"{worst[1]} Wi-Fi disconnections on {worst[0]}",
        })
    if driver:
        ids = sorted({e["event_id"] for e in driver})
        patterns.append({
            "id": "wifi_driver_issues",
            "playbook": WIFI,
            "verdict": "fact",
            "detail": f"{len(driver)} Wi-Fi driver warnings or errors "
                      f"(events {', '.join(map(str, ids))})",
        })
    resumes = sorted(
        datetime.fromisoformat(e["time"])
        for e in events if e.get("kind") == "resume_from_sleep"
    )
    if resumes and drops:
        hits = [
            drop for drop in drops
            if any(
                0 <= (datetime.fromisoformat(drop["time"]) - woke).total_seconds()
                <= RESUME_AFTER_SECONDS
                for woke in resumes
            )
        ]
        if hits:
            patterns.append({
                "id": "wifi_after_resume",
                "playbook": WIFI,
                "verdict": "hypothesis",
                "detail": f"{len(hits)}/{len(drops)} Wi-Fi disconnections within "
                          "10 minutes after resume from sleep",
            })
    return patterns


def _other_playbook_patterns(events: list[dict]) -> list[dict]:
    grouped: dict = {}
    for event in events:
        playbook = event.get("playbook")
        if not playbook or playbook == STABILITY or playbook in DEDICATED_PATTERNS:
            continue
        grouped.setdefault((playbook, event.get("kind")), []).append(event["time"][:10])
    patterns = []
    for (playbook, kind), dates in sorted(grouped.items()):
        dates = sorted(dates)
        if len(dates) > 1:
            detail = f"{len(dates)} {kind} events, {dates[0]}..{dates[-1]}"
        else:
            detail = f"1 {kind} event on {dates[0]}"
        patterns.append({
            "id": kind, "playbook": playbook, "verdict": "fact", "detail": detail,
        })
    return patterns


def apply_rules(
    evidence: dict,
    playbooks_dir: str | Path | None = None,
    tz: str | None = None,
) -> dict:
    """Apply every playbook to normalized evidence and return findings.

    Incident dates are expressed in the ``tz`` IANA timezone; without one
    the event wall-clock date is kept as-is.
    """
    playbooks = {p["id"]: p for p in load_playbooks(playbooks_dir)}
    events = evidence.get("events", [])
    dumps = evidence.get("dumps", [])
    codes = (playbooks.get(STABILITY, {}).get("interpretation") or {}).get("codes", {})
    incidents = _build_incidents(events, dumps, codes, tz)
    patterns = (
        _stability_patterns(incidents, dumps)
        + _wifi_patterns(events)
        + _other_playbook_patterns(events)
    )
    matched = {e.get("playbook") for e in events}
    healthy = [
        {
            "playbook": playbook_id,
            "note": playbook.get("no_findings") or "No events matched this playbook.",
        }
        for playbook_id, playbook in sorted(playbooks.items())
        if playbook_id not in matched
    ]
    modules = [d.get("image_name") for d in dumps if d.get("image_name")]
    counts = Counter(modules)
    common = sorted(counts, key=lambda m: (-counts[m], m))[0] if counts else None
    timestamps = []
    for dump in sorted(dumps, key=lambda d: d.get("file") or ""):
        stamp = dump.get("driver_timestamp")
        if stamp and stamp not in timestamps:
            timestamps.append(stamp)
    dated = [i["driver_timestamp"] for i in incidents if i.get("driver_timestamp")]
    if len(dated) < 2:
        driver_change_direction = "unknown"
    elif dated[-1] > dated[0]:
        driver_change_direction = "newer"
    elif dated[-1] < dated[0]:
        driver_change_direction = "older"
    else:
        driver_change_direction = "unknown"
    dates = [i["date"] for i in incidents]
    if dates:
        days = (
            date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])
        ).days
        months_span = max(1, round(days / 30.44))
    else:
        months_span = 0
    return {
        "incidents": incidents,
        "patterns": patterns,
        "healthy": healthy,
        "common_module": common,
        "dumps_with_common_module": counts.get(common, 0) if common else 0,
        "distinct_driver_timestamps": timestamps,
        "summary": {
            "total_incidents": len(incidents),
            "incidents_with_dump": sum(1 for i in incidents if i["dump_module"]),
            "freezes_without_dump": sum(
                1 for i in incidents if i["code"] == 0 and not i["dump_module"]
            ),
            "first_incident_date": dates[0] if dates else None,
            "last_incident_date": dates[-1] if dates else None,
            "months_span": months_span,
            "driver_change_direction": driver_change_direction,
            "incidents": [
                {
                    "date": i["date"],
                    "time": i["time"],
                    "label": (
                        INCIDENT_LABELS.get(i.get("code_hex") or "", {}).get("en")
                        or i.get("code_name")
                        or i.get("code_hex")
                    ),
                    "code": i.get("code_hex"),
                    "has_dump": bool(i.get("dump_module")),
                    "dump_module": i.get("dump_module"),
                    "driver_timestamp": i.get("driver_timestamp"),
                }
                for i in incidents
            ],
        },
    }
