"""Build the precomputed demo case (calls live models for en and es).

Usage: python scripts/build_demo_case.py [--timezone America/Managua] [--fix-only]
Writes fixtures/real_case/demo_case.json. Rerun after prompt or model
changes so /demo serves fresh output.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faultcase import rules  # noqa: E402
from faultcase.agent import build_case, explain_case, fix_plan  # noqa: E402
from faultcase.demo import (  # noqa: E402
    DEMO_CASE_PATH,
    DEMO_DEVICE,
    DEMO_TIMEZONE,
    build_demo_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timezone", default=DEMO_TIMEZONE)
    parser.add_argument(
        "--fix-only", action="store_true",
        help="keep the existing case and explanation; only add fix plans",
    )
    args = parser.parse_args()
    if args.fix_only:
        data = json.loads(DEMO_CASE_PATH.read_text(encoding="utf-8"))
        for lang in ("en", "es"):
            print(f"fix plan {lang} ...", flush=True)
            plan = fix_plan(data["findings"], data[lang]["case"], lang,
                            DEMO_DEVICE.get("manufacturer"))
            plan["model"] = "Muse Spark" if plan["provider"] == "meta" else "Muse Spark Open"
            data[lang]["fix_plan"] = plan
        DEMO_CASE_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {DEMO_CASE_PATH}")
        return
    evidence, _summaries = build_demo_evidence()
    data: dict = {
        "timezone": args.timezone,
        "findings": rules.apply_rules(evidence, tz=args.timezone),
    }
    for lang in ("en", "es"):
        print(f"building {lang} ...", flush=True)
        result = build_case(
            evidence, ui_language=lang, device=DEMO_DEVICE,
            timezone=args.timezone,
        )
        data[lang] = {"case": result["case"], "metadata": result["metadata"]}
        print(f"explaining {lang} ...", flush=True)
        explanation = explain_case(data["findings"], result["case"], lang)
        explanation["model"] = (
            "Muse Spark" if explanation["provider"] == "meta" else "Muse Spark Open"
        )
        data[lang]["explanation"] = explanation
        print(f"fix plan {lang} ...", flush=True)
        plan = fix_plan(data["findings"], result["case"], lang,
                        DEMO_DEVICE.get("manufacturer"))
        plan["model"] = "Muse Spark" if plan["provider"] == "meta" else "Muse Spark Open"
        data[lang]["fix_plan"] = plan
    DEMO_CASE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {DEMO_CASE_PATH}")


if __name__ == "__main__":
    main()
