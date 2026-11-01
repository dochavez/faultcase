"""The committed demo case must list every incident date in both reports."""

import json
from pathlib import Path

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
     / "demo_case.json").read_text(encoding="utf-8")
)
DATES = [
    "2026-04-22", "2026-04-30", "2026-07-17",
    "2026-07-21", "2026-07-24", "2026-10-23",
]


def test_demo_bodies_contain_all_incident_dates():
    for lang in ("en", "es"):
        report = DEMO_CASE[lang]["case"]["manufacturer_report"]
        for key in ("body_en", "body_es"):
            for day in DATES:
                assert day in report[key], (lang, key, day)
