"""Shared builders for agent tests (helpers only, not collected by pytest)."""

import re
from pathlib import Path

from faultcase import normalize
from faultcase.adapters.windows import fixture_events, windbg

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"

DENIAL_WORDS = re.compile(
    r"\bnot\b|\bn['’]t\b|\bnever\b|\bno\b|\bwithout\b|\bcannot\b|\bcan['’]t\b"
)


def cross_machine_defect_claim(text: str) -> str | None:
    """Return a sentence claiming the same defect as other machines, if any.

    Sentences that deny the claim ("not proof of the same defect as other
    machines") are correct and do not count.
    """
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        low = sentence.lower()
        if (
            "other machine" in low
            and re.search(r"same (underlying )?defect", low)
            and not DENIAL_WORDS.search(low)
        ):
            return sentence
    return None


def build_real_case_evidence() -> dict:
    """Normalize the real case fixtures (events_41.json + windbg/*.txt)."""
    events = fixture_events.load_fixture_events()
    for event in list(events):
        related = event["fields"].get("related_6008")
        if related:
            events.append({
                "time": related,
                "log": "System",
                "source": "EventLog",
                "event_id": 6008,
                "fields": {},
            })
    dumps = []
    for path in sorted((REAL_CASE / "windbg").glob("*.txt")):
        dumps.append({"file": path.name, **windbg.parse_windbg(path)})
    return normalize.normalize(events, dumps).evidence
