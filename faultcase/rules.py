"""Deterministic rules engine: apply playbooks to normalized evidence.

Computes per-incident facts (dates, decimal-to-hex codes, power transitions,
linked dumps), evaluates each playbook's patterns and lists healthy
components. Pure Python: this module never calls a model. Every pattern is
labeled "fact" or "hypothesis"; power_transition is always a hypothesis.
"""

from __future__ import annotations

import re
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
            # Label key: the stop code when Windows logged one, otherwise the
            # kind of event (6008 alone = shutdown without a crash code).
            "label_key": hex(code) if isinstance(code, int) else main.get("kind"),
            "explanation": info.get("explanation"),
            "power_transition": any(_sleep_in_progress(e) for e in reboots),
            "dump_module": dump.get("image_name"),
            "driver_timestamp": dump.get("driver_timestamp"),
            "params": main.get("params"),
        })
    return sorted(incidents, key=lambda i: i["date"])


GPU_RESET_KINDS = ("gpu_driver_reset", "tdr_recovered")


def _gpu_reset_patterns(events: list[dict]) -> list[dict]:
    """Display driver resets that did not crash the machine."""
    resets = sorted(
        e["time"][:10] for e in events if e.get("kind") in GPU_RESET_KINDS
    )
    if not resets:
        return []
    nvidia = sum(1 for e in events if e.get("kind") == "gpu_driver_reset")
    detail = (
        f"{len(resets)} display driver resets without a reboot, "
        f"{resets[0]}..{resets[-1]}"
    )
    if nvidia:
        detail += f" ({nvidia} logged by the NVIDIA driver as 'TDR occurred')"
    return [{
        "id": "gpu_resets", "playbook": STABILITY, "verdict": "fact",
        "detail": detail,
    }]


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
USB = "usb"
BATTERY = "battery"
WIFI_DROP_KINDS = ("wifi_disconnected", "wifi_connect_failed")
WIFI_DRIVER_KINDS = ("wifi_driver_error", "wifi_driver_warning")
RESUME_AFTER_SECONDS = 600

# Playbooks with dedicated pattern functions (skipped by the generic counter).
DEDICATED_PATTERNS = {WIFI, USB}

DISK = "disk"
SOFTWARE = "software"
HARDWARE = "hardware"
THERMAL = "thermal"
RESUME_KIND = "resume_from_sleep"
COMPONENT_ORDER = [
    STABILITY, DISK, HARDWARE, THERMAL, WIFI, USB, BATTERY, SOFTWARE,
]
# Windows levels: 1 critical, 2 error, 3 warning, 4/0/5 information.
INFO_LEVELS = (0, 4, 5)
# Virtual devices (Hyper-V, software-enumerated) fail to start on healthy
# machines all the time; they are not physical USB faults.
BENIGN_USB_DEVICE_PREFIXES = ("ROOT\\", "SWD\\")
# User-mode driver framework reflector: logs 219 at boot on healthy PCs.
BENIGN_USB_DRIVERS = ("wudfrd",)
# Successful updates are context, never a problem.
CONTEXT_KINDS = {"update_ok"}
# WLAN 8003 reason codes started by the user or Windows (new connection,
# adapter turned off or put to sleep, temporary disconnect request).
BENIGN_WIFI_DISCONNECT_REASONS = {"3", "11", "13"}
# WLAN 8002: no connectable access point visible (out of range), cancelled.
BENIGN_WIFI_CONNECT_REASONS = {"229396", "229377"}
DISK_DEVICE = re.compile(r"Harddisk(\d+)", re.IGNORECASE)
DISK_OBJECT = re.compile(r"\\DR(\d+)\b")
# Wi-Fi is a problem (not just worth a look) from this many drops in a day.
WIFI_PROBLEM_DROPS_PER_DAY = 10


def _is_usb_device(device_id: str) -> bool:
    upper = device_id.upper()
    return upper.startswith("USB") or "VID_" in upper


def disk_location(event: dict) -> tuple[str | None, bool]:
    """(label, is_system_disk) for the device a disk event names.

    ``Harddisk0`` / ``DR0`` is the system disk. Higher numbers are other
    disks; a growing ``DRn`` usually means a removable drive that was
    plugged in again. Unknown devices count as the system disk.
    """
    for value in (event.get("fields") or {}).values():
        text = str(value)
        match = DISK_DEVICE.search(text)
        if match:
            number = int(match.group(1))
            return f"disk {number}", number == 0
        match = DISK_OBJECT.search(text)
        if match:
            number = int(match.group(1))
            return f"device DR{number}", number == 0
    return None, True


def benign_reason(event: dict) -> str | None:
    """Return why an event is known noise (not counted), or None."""
    playbook = event.get("playbook")
    kind = event.get("kind")
    fields = event.get("fields") or {}
    level = event.get("level")
    if kind in CONTEXT_KINDS:
        return "context"
    if playbook == USB:
        device = str(
            fields.get("DeviceInstanceId") or fields.get("DriverName") or ""
        ).upper()
        if device.startswith(BENIGN_USB_DEVICE_PREFIXES):
            return "virtual_device"
        name = str(fields.get("FailureName") or "").lower()
        if any(driver in name for driver in BENIGN_USB_DRIVERS):
            return "benign_driver"
        # Kernel-PnP logs every device class (PCI, ACPI...); only USB
        # devices belong to this component.
        if device and not _is_usb_device(device):
            return "not_usb"
    if playbook == WIFI:
        if kind == "wifi_driver_warning":
            # Intel Netwtw/Netwaw 6062 is logged constantly on healthy PCs.
            return "known_noise"
        reason = str(fields.get("ReasonCode", "")).strip()
        if kind == "wifi_disconnected" and reason in BENIGN_WIFI_DISCONNECT_REASONS:
            return "user_or_system"
        if kind == "wifi_connect_failed" and reason in BENIGN_WIFI_CONNECT_REASONS:
            return "out_of_range"
    if playbook == DISK and "shadowcopy" in str(fields.get("DeviceName", "")).lower():
        # Corruption reported on a Volume Shadow Copy snapshot, not the disk.
        return "shadow_copy"
    if level in INFO_LEVELS and (
        (playbook == DISK and kind == "volume_needs_repair")
        or (playbook == WIFI and kind in WIFI_DRIVER_KINDS)
    ):
        return "informational"
    return None


def _component_statuses(
    playbook_ids: list, counted: list[dict], incidents: list[dict],
    patterns: list[dict], evidence: dict, ignored: Counter,
) -> list[dict]:
    """One status per component: problem, attention, ok or no_data."""
    order = COMPONENT_ORDER + sorted(
        p for p in playbook_ids if p not in COMPONENT_ORDER
    )
    components = []
    for pid in order:
        if pid not in playbook_ids:
            continue
        events = [
            e for e in counted
            if e.get("playbook") == pid and e.get("kind") != RESUME_KIND
        ]
        kinds = {e.get("kind") for e in events}
        ids = {p["id"] for p in patterns if p.get("playbook") == pid}
        count = len(events)
        if pid == STABILITY:
            count = len(incidents)
            status = "problem" if count >= 2 else "attention" if count else "ok"
        elif pid == BATTERY:
            battery = evidence.get("battery") or {}
            wear = battery.get("wear_percent")
            count = len(ids - {"battery_wear", "battery_no_data"})
            if not battery or "battery_no_data" in ids:
                status = "no_data"
            elif ids & {"battery_early_wear", "battery_rapid_decline"}:
                status = "problem"
            elif isinstance(wear, (int, float)) and wear >= 20:
                status = "attention"
            else:
                status = "ok"
        elif pid == WIFI:
            per_day = Counter(
                e["time"][:10] for e in events if e.get("kind") in WIFI_DROP_KINDS
            )
            worst = max(per_day.values(), default=0)
            status = (
                "problem" if worst >= WIFI_PROBLEM_DROPS_PER_DAY
                else "attention" if count else "ok"
            )
        elif pid == USB:
            status = (
                "problem" if "usb_same_device_repeats" in ids
                else "attention" if count else "ok"
            )
        elif pid == HARDWARE:
            serious = kinds & {"whea_fatal", "whea_memory"}
            status = (
                "problem" if serious or count >= 3
                else "attention" if count else "ok"
            )
        elif pid == DISK:
            serious = [
                e for e in events
                if e.get("kind") in {"bad_block", "paging_error", "ntfs_corruption"}
                and disk_location(e)[1]
            ]
            status = "problem" if serious else "attention" if count else "ok"
        elif pid == THERMAL:
            status = (
                "problem" if count >= 10 else "attention" if count else "ok"
            )
        else:
            # Software crashes are worth a look but are not warranty faults.
            status = "attention" if count else "ok"
        components.append({
            "id": pid, "status": status, "count": count,
            "ignored": ignored.get(pid, 0),
        })
    return components


def _resume_times(events: list[dict]) -> list:
    return sorted(
        datetime.fromisoformat(e["time"])
        for e in events if e.get("kind") == "resume_from_sleep"
    )


def _soon_after_resume(events: list[dict], resumes: list) -> list[dict]:
    return [
        event for event in events
        if any(
            0 <= (datetime.fromisoformat(event["time"]) - woke).total_seconds()
            <= RESUME_AFTER_SECONDS
            for woke in resumes
        )
    ]


def _device_key(value: object) -> str:
    """Group device IDs by model part, dropping the per-machine suffix."""
    text = str(value or "")
    head, sep, _tail = text.rpartition("\\")
    return head if sep else text


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
    resumes = _resume_times(events)
    if resumes and drops:
        hits = _soon_after_resume(drops, resumes)
        if hits:
            patterns.append({
                "id": "wifi_after_resume",
                "playbook": WIFI,
                "verdict": "hypothesis",
                "detail": f"{len(hits)}/{len(drops)} Wi-Fi disconnections within "
                          "10 minutes after resume from sleep",
            })
    return patterns


def _usb_patterns(events: list[dict]) -> list[dict]:
    usb = [e for e in events if e.get("playbook") == USB]
    if not usb:
        return []
    patterns = []
    failed = [e for e in usb if e.get("kind") == "usb_device_failed"]
    drivers = [e for e in usb if e.get("kind") == "usb_driver_failed"]
    patterns.append({
        "id": "usb_events",
        "playbook": USB,
        "verdict": "fact",
        "detail": f"{len(failed)} device start failures, "
                  f"{len(drivers)} drivers failed to load",
    })
    by_device: dict = {}
    for event in failed:
        key = _device_key(event.get("fields", {}).get("DeviceInstanceId"))
        by_device.setdefault(key or "unknown device", []).append(event)
    for key in sorted(by_device, key=lambda k: (-len(by_device[k]), k)):
        group = by_device[key]
        if len(group) < 2:
            continue
        problems = sorted({
            str(e.get("fields", {}).get("Problem"))
            for e in group if e.get("fields", {}).get("Problem") is not None
        })
        detail = f"Device {key} failed {len(group)} times"
        if problems:
            detail += f" (problem {', '.join(problems)})"
        patterns.append({
            "id": "usb_same_device_repeats",
            "playbook": USB,
            "verdict": "fact",
            "detail": detail,
        })
    if drivers:
        names = sorted({
            str(e.get("fields", {}).get("FailureName", "unknown driver"))
            for e in drivers
        })
        patterns.append({
            "id": "usb_driver_failed",
            "playbook": USB,
            "verdict": "fact",
            "detail": f"{len(drivers)} drivers failed to load "
                      f"({', '.join(names)})",
        })
    resumes = _resume_times(events)
    failures = failed + drivers
    if resumes and failures:
        hits = _soon_after_resume(failures, resumes)
        if hits:
            patterns.append({
                "id": "usb_after_resume",
                "playbook": USB,
                "verdict": "hypothesis",
                "detail": f"{len(hits)}/{len(failures)} USB failures within "
                          "10 minutes after resume from sleep",
            })
    return patterns


def _battery_age_months(battery: dict) -> float | None:
    manufacture = battery.get("manufacture_date")
    report = battery.get("report_date")
    if manufacture and report:
        try:
            days = (
                date.fromisoformat(report) - date.fromisoformat(manufacture)
            ).days
            if days >= 0:
                return days / 30.44
        except ValueError:
            pass
    starts = [
        h["period_start"] for h in battery.get("capacity_history", [])
        if h.get("period_start")
    ]
    if not starts:
        return None
    ends = [
        h["period_end"] for h in battery.get("capacity_history", [])
        if h.get("period_end")
    ] or starts
    try:
        days = (date.fromisoformat(max(ends)) - date.fromisoformat(min(starts))).days
    except ValueError:
        return None
    return days / 30.44 if days >= 0 else None


def _battery_patterns(evidence: dict) -> list[dict]:
    battery = evidence.get("battery") or {}
    if not battery:
        return []
    wear = battery.get("wear_percent")
    design = battery.get("design_capacity_mwh")
    full = battery.get("full_charge_capacity_mwh")
    cycles = battery.get("cycle_count")
    history = [
        h for h in battery.get("capacity_history", [])
        if h.get("full_charge_mwh") is not None
    ]
    if wear is None and not history:
        return [{
            "id": "battery_no_data",
            "playbook": BATTERY,
            "verdict": "fact",
            "detail": "Battery report provided but has no usable capacity numbers",
        }]
    patterns = []
    months = _battery_age_months(battery)
    if wear is not None:
        detail = f"Battery wear {wear:g}%"
        if design is not None and full is not None:
            detail += f" ({full:,} of {design:,} mWh)"
        if cycles is not None:
            detail += f", {cycles} cycles"
        if months is not None:
            detail += f", after {months:.0f} months"
        patterns.append({
            "id": "battery_wear", "playbook": BATTERY, "verdict": "fact",
            "detail": detail,
        })
        if months is not None and months < 12 and wear > 20:
            patterns.append({
                "id": "battery_early_wear",
                "playbook": BATTERY,
                "verdict": "fact",
                "detail": f"Battery wear {wear:g}% within the first year "
                          f"({months:.0f} months)",
            })
    if len(history) >= 2:
        first = history[0]["full_charge_mwh"]
        last = history[-1]["full_charge_mwh"]
        span = None
        try:
            start = history[0].get("period_start") or ""
            end = history[-1].get("period_end") or history[-1].get("period_start") or ""
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            span = None
        if span is not None and span >= 30 and first > 0:
            drop = 100 * (first - last) / first
            if drop >= 15:
                patterns.append({
                    "id": "battery_rapid_decline",
                    "playbook": BATTERY,
                    "verdict": "fact",
                    "detail": f"Full charge fell {drop:.0f}% in {span} days "
                              f"({first:,} to {last:,} mWh)",
                })
    return patterns


def _other_playbook_patterns(events: list[dict]) -> list[dict]:
    grouped: dict = {}
    for event in events:
        playbook = event.get("playbook")
        if not playbook or playbook == STABILITY or playbook in DEDICATED_PATTERNS:
            continue
        label, system = (
            disk_location(event) if playbook == DISK else (None, True)
        )
        # Removable drives get a new DRn each time: group them together.
        if label and label.startswith("device DR") and not system:
            label = "a removable drive"
        key = (playbook, event.get("kind"), label or "", system)
        grouped.setdefault(key, []).append(event["time"][:10])
    patterns = []
    secondary = set()
    for (playbook, kind, disk, system), dates in sorted(grouped.items()):
        dates = sorted(dates)
        where = f" on {disk}" if disk else ""
        if len(dates) > 1:
            detail = f"{len(dates)} {kind} events{where}, {dates[0]}..{dates[-1]}"
        else:
            detail = f"1 {kind} event{where} on {dates[0]}"
        patterns.append({
            "id": kind, "playbook": playbook, "verdict": "fact", "detail": detail,
        })
        if not system:
            secondary.add((playbook, disk))
    for playbook, disk in sorted(secondary):
        patterns.append({
            "id": "secondary_disk", "playbook": playbook,
            "verdict": "hypothesis",
            "detail": (
                "These errors are on a removable drive, not on the system disk"
                if disk == "a removable drive" else
                f"{disk.capitalize()} is not the system disk; it is often an "
                "external or secondary drive"
            ),
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
    counted = [e for e in events if benign_reason(e) is None]
    ignored = Counter(
        e.get("playbook") for e in events if benign_reason(e) is not None
    )
    patterns = (
        _stability_patterns(incidents, dumps)
        + _gpu_reset_patterns(counted)
        + _wifi_patterns(counted)
        + _usb_patterns(counted)
        + _battery_patterns(evidence)
        + _other_playbook_patterns(counted)
    )
    matched = {e.get("playbook") for e in counted}
    if evidence.get("battery"):
        matched.add(BATTERY)
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
    components = _component_statuses(
        list(playbooks), counted, incidents, patterns, evidence, ignored
    )
    return {
        "incidents": incidents,
        "patterns": patterns,
        "healthy": healthy,
        "components": components,
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
                        INCIDENT_LABELS.get(i.get("label_key") or "", {}).get("en")
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
