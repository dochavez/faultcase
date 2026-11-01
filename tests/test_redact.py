"""Redaction removes personal data and leaves the rest untouched."""

from faultcase import redact


def test_redact_text_removes_personal_data():
    sample = (
        "Crash dump at C:\\Users\\janedoe\\AppData\\Local\\Temp\\crash.dmp "
        "from DESKTOP-KLM4FSL with MAC 00:1A:2B:3C:4D:5E, "
        "report to janedoe@example.com, SerialNumber: PF3AB12C"
    )
    out = redact.redact_text(sample)
    for secret in (
        "janedoe", "DESKTOP-KLM4FSL", "00:1A:2B:3C:4D:5E",
        "janedoe@example.com", "PF3AB12C",
    ):
        assert secret not in out
    for placeholder in ("<USER>", "<COMPUTER>", "<MAC>", "<EMAIL>", "<SERIAL>"):
        assert placeholder in out
    assert "Crash dump at" in out


def test_redact_obj_walks_json_like_objects():
    obj = {
        "path": "C:\\Users\\janedoe\\x",
        "tags": ["nvlddmkm.sys", "DESKTOP-X1"],
        "count": 3,
        "nothing": None,
        "nested": {"mac": "AA-BB-CC-DD-EE-FF"},
    }
    assert redact.redact_obj(obj) == {
        "path": "C:\\Users\\<USER>\\x",
        "tags": ["nvlddmkm.sys", "<COMPUTER>"],
        "count": 3,
        "nothing": None,
        "nested": {"mac": "<MAC>"},
    }
