"""Read Windows event logs (.evtx) with python-evtx.

Each record becomes a raw event dict::

    {"time": ..., "log": ..., "source": ..., "event_id": ..., "fields": {...}}

``time`` is ISO 8601 with timezone, ``log`` is the channel (e.g. System),
``source`` is the provider name and ``fields`` holds all EventData entries.
Malformed records are skipped and counted, never raised.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from Evtx.Evtx import Evtx

NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


@dataclass
class EvtxResult:
    events: list[dict] = field(default_factory=list)
    skipped: int = 0


def _event_time(system: ET.Element) -> str:
    node = system.find(f"{NS}TimeCreated")
    if node is None or not node.get("SystemTime"):
        raise ValueError("record has no SystemTime")
    moment = datetime.fromisoformat(node.get("SystemTime"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def _event_data(root: ET.Element) -> dict:
    fields: dict = {}
    event_data = root.find(f"{NS}EventData")
    if event_data is None:
        return fields
    unnamed = 0
    for data in event_data.findall(f"{NS}Data"):
        value = data.text or ""
        name = data.get("Name")
        if name:
            fields[name] = value
        else:
            fields[f"Data{unnamed}"] = value
            unnamed += 1
    binary = event_data.find(f"{NS}Binary")
    if binary is not None and binary.text:
        fields["Binary"] = binary.text
    return fields


def parse_record_xml(xml: str) -> dict:
    """Parse one rendered record into a raw event dict.

    Raises ValueError if the record is malformed (bad XML or missing
    the required System fields).
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"record is not valid XML: {exc}") from exc
    system = root.find(f"{NS}System")
    if system is None:
        raise ValueError("record has no System element")
    provider = system.find(f"{NS}Provider")
    channel = system.find(f"{NS}Channel")
    event_id = system.find(f"{NS}EventID")
    if provider is None or not provider.get("Name"):
        raise ValueError("record has no provider name")
    if channel is None or not (channel.text or "").strip():
        raise ValueError("record has no channel")
    if event_id is None or not (event_id.text or "").strip():
        raise ValueError("record has no event ID")
    event = {
        "time": _event_time(system),
        "log": channel.text.strip(),
        "source": provider.get("Name"),
        "event_id": int(event_id.text.strip()),
        "fields": _event_data(root),
    }
    level = system.find(f"{NS}Level")
    if level is not None and (level.text or "").strip().isdigit():
        # 1 critical, 2 error, 3 warning, 4 or 0 information.
        event["level"] = int(level.text.strip())
    return event


def parse_evtx(path: str | Path) -> EvtxResult:
    """Parse an .evtx file, skipping malformed records and counting them."""
    result = EvtxResult()
    with Evtx(str(path)) as log:
        for record in log.records():
            try:
                result.events.append(parse_record_xml(record.xml()))
            except Exception:
                result.skipped += 1
    return result
