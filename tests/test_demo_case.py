"""The committed demo case must list every incident date in both reports."""

import json
import re
from pathlib import Path

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
     / "demo_case.json").read_text(encoding="utf-8")
)
DATES = [
    "2026-04-22", "2026-04-30", "2026-07-17",
    "2026-07-21", "2026-07-24", "2026-10-23",
]
ALLOWED_CAPS_WORDS = {
    "DPC_WATCHDOG_VIOLATION",
    "VIDEO_TDR_FAILURE",
    "NO_BLUE_SCREEN",
    "NVIDIA",
    "GPU",
    "CPU",
    "BIOS",
    "WHEA",
    "UEFI",
    "VRAM",
    "PSU",
    "ISR",
    "DDU",
    "TDR",
}


def _bodies():
    for lang in ("en", "es"):
        report = DEMO_CASE[lang]["case"]["manufacturer_report"]
        for key in ("body_en", "body_es"):
            yield lang, key, report[key]


def test_demo_bodies_contain_all_incident_dates():
    for lang, key, body in _bodies():
        for day in DATES:
            assert day in body, (lang, key, day)


def test_demo_bodies_have_only_affected_component_sections():
    for lang, key, body in _bodies():
        if key == "body_en":
            assert "Stability:" in body
            for section in ("Wi-Fi:", "USB:", "Battery:", "Storage:",
                            "Temperature:", "Software:"):
                assert section not in body, (lang, key, section)
        else:
            assert "Estabilidad:" in body
            for section in ("Wi-Fi:", "USB:", "Batería:", "Almacenamiento:",
                            "Temperatura:", "Software:"):
                assert section not in body, (lang, key, section)


def test_demo_bodies_use_plain_professional_language():
    for lang, key, body in _bodies():
        text = body.replace("{{SERIAL}}", "")
        assert not re.search(
            r"after (\w+ )?driver updates?\b", text, re.IGNORECASE
        ), (lang, key)
        for word in set(re.findall(r"\b[A-Z][A-Z0-9_]{1,}\b", text)):
            assert word in ALLOWED_CAPS_WORDS, (lang, key, word)
