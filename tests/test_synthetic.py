"""Synthetic benchmark fixtures: valid evidence with known incident counts."""

import json
from pathlib import Path

from jsonschema import validate

from faultcase import rules

SYNTHETIC = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"
EVIDENCE_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "evidence.schema.json")
    .read_text(encoding="utf-8")
)

EXPECTED_INCIDENTS = {
    "healthy": 0,
    "disk_failure": 3,
    "single_crash": 1,
}


def _load(name):
    return json.loads((SYNTHETIC / f"{name}.json").read_text(encoding="utf-8"))


def test_synthetic_fixtures_validate_and_match_counts():
    assert sorted(p.stem for p in SYNTHETIC.glob("*.json")) == sorted(
        EXPECTED_INCIDENTS
    )
    for name, total in EXPECTED_INCIDENTS.items():
        case = _load(name)
        validate(instance=case["evidence"], schema=EVIDENCE_SCHEMA)
        findings = rules.apply_rules(case["evidence"], tz=case["timezone"])
        assert findings["summary"]["total_incidents"] == total
        assert case["expected_verdict_contains"]


def test_disk_fixture_reports_bad_blocks():
    case = _load("disk_failure")
    findings = rules.apply_rules(case["evidence"], tz=case["timezone"])
    assert ("disk", "bad_block") in [
        (p["playbook"], p["id"]) for p in findings["patterns"]
    ]
