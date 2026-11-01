"""Live test: build the real case with real models (needs API keys)."""

import json
import re
from pathlib import Path

import pytest

from faultcase import rules
from faultcase.agent import build_case
from tests.helpers import build_real_case_evidence, cross_machine_defect_claim

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
EXPECTED = json.loads((REAL_CASE / "expected.json").read_text(encoding="utf-8"))
CONFIDENCE = {"low": 0, "medium": 1, "high": 2}


@pytest.mark.live
def test_live_build_real_case():
    device = {
        "manufacturer": "Lenovo",
        "gpu": "NVIDIA",
        "purchase_date": "2026-01",
    }
    result = build_case(build_real_case_evidence(), ui_language="en", device=device)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    case = result["case"]
    assert case["verdict"] in EXPECTED["acceptable_verdicts"]
    assert CONFIDENCE[case["confidence"]] >= CONFIDENCE[EXPECTED["minimum_confidence"]]
    text = "\n".join(
        [case["user_summary"]]
        + [finding["text"] for finding in case["findings"]]
        + [case["manufacturer_report"]["body_en"],
           case["manufacturer_report"]["body_es"]]
    )
    assert cross_machine_defect_claim(text) is None
    assert "definitely hardware" not in text.lower()
    assert "definitely a hardware" not in text.lower()
    assert "confirmed hardware" not in text.lower()
    assert not re.search(r"0x[0-9a-fA-F]+", case["user_summary"])
    assert case["manufacturer_report"]["body_en"].strip()
    assert case["manufacturer_report"]["body_es"].strip()
    assert len(case["manufacturer_report"]["subject"]) >= 10
    summary = rules.apply_rules(build_real_case_evidence())["summary"]
    allowed = {str(summary["total_incidents"]), str(summary["months_span"])}
    found = re.findall(r"\d+", case["user_summary"])
    assert str(summary["total_incidents"]) in found
    assert set(found) <= allowed
