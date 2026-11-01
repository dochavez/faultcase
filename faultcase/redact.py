"""Remove personal data before anything reaches a model.

Replaces Windows user names in paths, computer names, serial numbers, MAC
addresses and email addresses with placeholders. Serial numbers are only
redacted when labeled (``SerialNumber: ...``); unlabeled bare values that
merely look like serials are left alone to avoid destroying real evidence.
"""

from __future__ import annotations

import re

USER_PATH_RE = re.compile(r"(?i)([A-Za-z]:[\\/]Users[\\/])[^\\/:\s\"']+")
COMPUTER_RE = re.compile(r"\b(DESKTOP|LAPTOP)-[A-Za-z0-9]+\b", re.IGNORECASE)
SERIAL_RE = re.compile(
    r"(Serial\s*(?:Number|No\.?)?\s*[:=]\s*)([A-Za-z0-9][A-Za-z0-9-]*)",
    re.IGNORECASE,
)
MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact_text(text: str) -> str:
    """Redact personal data in a string, replacing it with placeholders."""
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = MAC_RE.sub("<MAC>", text)
    text = SERIAL_RE.sub(r"\1<SERIAL>", text)
    text = COMPUTER_RE.sub("<COMPUTER>", text)
    text = USER_PATH_RE.sub(r"\1<USER>", text)
    return text


def redact_obj(obj: object) -> object:
    """Recursively redact personal data in any JSON-like object."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {redact_obj(key): redact_obj(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(value) for value in obj)
    return obj
