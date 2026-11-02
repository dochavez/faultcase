"""Benchmark providers across roles and cases (live API calls).

Usage: python scripts/benchmark.py [--runs 3]

Runs build_case on the real case plus the synthetic cases in
fixtures/synthetic/, then writes docs/benchmark.json and
docs/benchmark.md and prints the tables. Only verdicts and metrics are
stored: never API keys or personal data.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from math import ceil, floor
from pathlib import Path

import yaml
from jsonschema import validate

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from faultcase.agent import build_case  # noqa: E402
from faultcase.demo import DEMO_DEVICE  # noqa: E402
from faultcase.router import DEFAULT_USAGE_PATH, Router  # noqa: E402
from tests.helpers import REAL_CASE, build_real_case_evidence  # noqa: E402

SYNTHETIC_DIR = ROOT / "fixtures" / "synthetic"
SYNTHETIC_DEVICE = {
    "manufacturer": "Example",
    "model": "Synthetic Laptop",
    "purchase_date": "2026-01",
}
REAL_KEYWORDS = ["crash", "display", "driver", "fault", "hardware", "nvlddmkm"]


def percentile(data, pct):
    ordered = sorted(data)
    if not ordered:
        return None
    rank = (len(ordered) - 1) * pct / 100
    low, high = floor(rank), ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def verdict_ok(verdict, keywords):
    text = (verdict or "").lower()
    return any(keyword in text for keyword in keywords)


def load_cases():
    with open(ROOT / "config" / "providers.yaml", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    expected = json.loads((REAL_CASE / "expected.json").read_text(encoding="utf-8"))
    schema_path = ROOT / "schemas" / "evidence.schema.json"
    evidence_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    cases = [{
        "id": "real_case",
        "description": "Real case: 6 incidents, NVIDIA display crashes.",
        "timezone": "America/Managua",
        "device": DEMO_DEVICE,
        "evidence": build_real_case_evidence(),
        "keywords": REAL_KEYWORDS,
        "acceptable_final": expected["acceptable_verdicts"],
    }]
    for path in sorted(SYNTHETIC_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        validate(instance=case["evidence"], schema=evidence_schema)
        cases.append({
            "id": path.stem,
            "description": case["description"],
            "timezone": case["timezone"],
            "device": SYNTHETIC_DEVICE,
            "evidence": case["evidence"],
            "keywords": case["expected_verdict_contains"],
            "acceptable_final": case.get("acceptable_final"),
        })
    return config, cases


def run_benchmark(cases, runs):
    records = []
    for number in range(1, runs + 1):
        for case in cases:
            print(f"run {number}/{runs}: {case['id']} ...", flush=True)
            try:
                result = build_case(
                    case["evidence"], ui_language="en",
                    device=case["device"], timezone=case["timezone"],
                )
            except Exception as exc:  # noqa: BLE001 - recorded, run continues
                print(f"  FAILED: {type(exc).__name__}: {exc}", flush=True)
                records.append({
                    "case": case["id"], "run": number,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            opinions = []
            for opinion in result["metadata"].get("analysis_opinions", []):
                opinions.append({
                    "provider": opinion["provider"],
                    "success": opinion["success"],
                    "verdict": opinion.get("verdict"),
                    "correct": (
                        verdict_ok(opinion.get("verdict"), case["keywords"])
                        if opinion["success"] else False
                    ),
                })
            final = result["case"]["verdict"]
            if case["acceptable_final"] is not None:
                final_ok = final in case["acceptable_final"]
            else:
                final_ok = verdict_ok(final, case["keywords"])
            record = {
                "case": case["id"], "run": number,
                "final_verdict": final,
                "final_correct": final_ok,
                "final_provider": result["metadata"]["providers_used"][1],
                "agreement": result["metadata"].get("second_opinion_agreement"),
                "opinions": opinions,
            }
            records.append(record)
            print(
                f"  final={final} correct={final_ok} "
                f"agreement={record['agreement']}", flush=True,
            )
    return records


def read_new_usage(offset):
    if not DEFAULT_USAGE_PATH.exists():
        return []
    with open(DEFAULT_USAGE_PATH, encoding="utf-8") as fh:
        fh.seek(offset)
        return [json.loads(line) for line in fh if line.strip()]


def summarize(records, usage_lines, config):
    prices = {
        name: (
            float(spec.get("price_per_1k_input") or 0),
            float(spec.get("price_per_1k_output") or 0),
            float(spec.get("price_per_1k_cached") or 0),
        )
        for name, spec in config.get("providers", {}).items()
    }
    cells: dict = {}

    def cell(provider, role):
        return cells.setdefault((provider, role), {
            "calls_ok": 0, "calls_total": 0, "latencies": [],
            "prompt": 0, "completion": 0, "cached": 0, "cost": 0.0,
            "fallbacks": 0, "hedge_wins": 0, "correct": 0, "judged": 0,
        })

    for line in usage_lines:
        if line.get("event") == "hedge":
            cell(line["winner"], line["role"])["hedge_wins"] += 1
            continue
        provider, role = line["provider"], line["role"]
        stats = cell(provider, role)
        stats["calls_total"] += 1
        prompt = line.get("prompt_tokens", 0)
        completion = line.get("completion_tokens", 0)
        cached = line.get("cached_tokens", 0)
        stats["prompt"] += prompt
        stats["completion"] += completion
        stats["cached"] += cached
        price_in, price_out, price_cached = prices.get(provider, (0, 0, 0))
        stats["cost"] += (
            (prompt - cached) / 1000 * price_in
            + cached / 1000 * price_cached
            + completion / 1000 * price_out
        )
        if line.get("success"):
            stats["calls_ok"] += 1
            stats["latencies"].append(line.get("latency_ms", 0))
            if line.get("fallback_used"):
                stats["fallbacks"] += 1
    for record in records:
        if "error" in record:
            continue
        for opinion in record["opinions"]:
            if not opinion["success"]:
                continue
            stats = cell(opinion["provider"], "evidence_analysis")
            stats["judged"] += 1
            stats["correct"] += 1 if opinion["correct"] else 0
        stats = cell(record["final_provider"], "case_writing")
        stats["judged"] += 1
        stats["correct"] += 1 if record["final_correct"] else 0
    summary = []
    for (provider, role), stats in sorted(cells.items()):
        latencies = stats.pop("latencies")
        judged = stats.pop("judged")
        correct = stats.pop("correct")
        summary.append({
            "provider": provider, "role": role,
            "calls_ok": stats["calls_ok"], "calls_total": stats["calls_total"],
            "correct": correct, "judged": judged,
            "accuracy": (correct / judged) if judged else None,
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
            "prompt_tokens": stats["prompt"],
            "completion_tokens": stats["completion"],
            "cached_tokens": stats["cached"],
            "estimated_cost_usd": round(stats["cost"], 4),
            "fallbacks": stats["fallbacks"],
            "hedge_wins": stats["hedge_wins"],
        })
    agreement: dict = {}
    for record in records:
        if "error" in record:
            continue
        entry = agreement.setdefault(
            record["case"], {"runs": 0, "agreed": 0, "disagreed": 0, "single": 0}
        )
        entry["runs"] += 1
        value = record.get("agreement")
        if value is True:
            entry["agreed"] += 1
        elif value is False:
            entry["disagreed"] += 1
        else:
            entry["single"] += 1
    agreed = sum(entry["agreed"] for entry in agreement.values())
    disagreed = sum(entry["disagreed"] for entry in agreement.values())
    return {
        "by_provider_role": summary,
        "agreement_by_case": [
            {"case": case, **entry} for case, entry in sorted(agreement.items())
        ],
        "second_opinion_agreement_rate": (
            agreed / (agreed + disagreed) if agreed + disagreed else None
        ),
        "totals": {
            "runs": len(records),
            "failed_runs": sum(1 for record in records if "error" in record),
            "hedges": sum(
                1 for line in usage_lines if line.get("event") == "hedge"
            ),
            "estimated_cost_usd": round(
                sum(row["estimated_cost_usd"] for row in summary), 4
            ),
        },
    }


def _ms(value):
    return str(int(round(value))) if value is not None else "--"


def _pct(value):
    return f"{value:.0%}" if value is not None else "--"


def render_markdown(data):
    lines = [
        "# Provider benchmark",
        "",
        f"Generated: {data['generated_at']} · "
        f"runs per case: {data['runs_per_case']} · "
        f"failed runs: {data['summary']['totals']['failed_runs']}",
        "",
        "Config: "
        + ", ".join(
            f"{role}={opts.get('analysis_mode', 'single')}/"
            f"{opts.get('reasoning_effort', 'unset')}"
            for role, opts in sorted(data["config"]["roles"].items())
        )
        + f" · hedge_after={data['config']['hedge_after_seconds']}s",
        " · ".join(
            f"{name}={model}"
            for name, model in sorted(data["config"]["models"].items())
        ),
        "",
        "Correctness: real-case final verdict must be in expected.json "
        "acceptable_verdicts; every other verdict matches when it contains "
        "an expected keyword (case-insensitive). Costs use the example "
        "prices in config/providers.yaml.",
        "",
        "## By provider and role",
        "",
        "| Provider | Role | Calls ok/total | Correct | p50 ms | p95 ms | "
        "Prompt | Compl | Cached | Est. cost | Fallbacks | Hedge wins |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- |",
    ]
    for row in data["summary"]["by_provider_role"]:
        lines.append(
            f"| {row['provider']} | {row['role']} | "
            f"{row['calls_ok']}/{row['calls_total']} | "
            f"{_pct(row['accuracy'])} ({row['correct']}/{row['judged']}) | "
            f"{_ms(row['latency_p50_ms'])} | {_ms(row['latency_p95_ms'])} | "
            f"{row['prompt_tokens']} | {row['completion_tokens']} | "
            f"{row['cached_tokens']} | ${row['estimated_cost_usd']:.4f} | "
            f"{row['fallbacks']} | {row['hedge_wins']} |"
        )
    rate = data["summary"]["second_opinion_agreement_rate"]
    lines += [
        "",
        "## Second-opinion agreement",
        "",
        f"Agreement rate: {_pct(rate)} "
        "(agreed runs / runs with two opinions).",
        "",
        "| Case | Runs | Agreed | Disagreed | Single opinion |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in data["summary"]["agreement_by_case"]:
        lines.append(
            f"| {entry['case']} | {entry['runs']} | {entry['agreed']} | "
            f"{entry['disagreed']} | {entry['single']} |"
        )
    totals = data["summary"]["totals"]
    lines += [
        "",
        "## Totals",
        "",
        f"Runs: {totals['runs']} · hedges: {totals['hedges']} · "
        f"estimated cost: ${totals['estimated_cost_usd']:.4f}.",
        "",
        "## Notes",
        "",
        "- Agreement requires the same verdict enum and the same "
        "confidence level; mismatches lower confidence one level and add "
        "a hypothesis finding to the case.",
        "- Keyword lists include synonyms observed in model output "
        "(e.g. inconclusive); see fixtures/synthetic/*.json.",
    ]
    for row in data["summary"]["by_provider_role"]:
        failed = row["calls_total"] - row["calls_ok"]
        if failed:
            lines.append(
                f"- {row['provider']}/{row['role']}: {failed} failed "
                f"attempt(s) out of {row['calls_total']} "
                "(retried once each, then the other opinion was used)."
            )
    lines.append("")
    return "\n".join(lines)


def rescore(records, cases):
    """Recompute correctness of stored records (no model calls)."""
    by_id = {case["id"]: case for case in cases}
    for record in records:
        if "error" in record:
            continue
        case = by_id[record["case"]]
        for opinion in record["opinions"]:
            opinion["correct"] = (
                verdict_ok(opinion.get("verdict"), case["keywords"])
                if opinion["success"] else False
            )
        if case["acceptable_final"] is not None:
            record["final_correct"] = (
                record["final_verdict"] in case["acceptable_final"]
            )
        else:
            record["final_correct"] = verdict_ok(
                record["final_verdict"], case["keywords"]
            )
    return records


def refresh_accuracy(data):
    """Recompute per-row correct/judged/accuracy from stored records."""
    counts: dict = {}
    for record in data["records"]:
        if "error" in record:
            continue
        for opinion in record["opinions"]:
            if not opinion["success"]:
                continue
            key = (opinion["provider"], "evidence_analysis")
            entry = counts.setdefault(key, [0, 0])
            entry[1] += 1
            entry[0] += 1 if opinion["correct"] else 0
        key = (record["final_provider"], "case_writing")
        entry = counts.setdefault(key, [0, 0])
        entry[1] += 1
        entry[0] += 1 if record["final_correct"] else 0
    for row in data["summary"]["by_provider_role"]:
        correct, judged = counts.get((row["provider"], row["role"]), (0, 0))
        row["correct"] = correct
        row["judged"] = judged
        row["accuracy"] = (correct / judged) if judged else None
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", default=str(ROOT / "docs" / "benchmark.json"))
    parser.add_argument("--md", default=str(ROOT / "docs" / "benchmark.md"))
    parser.add_argument(
        "--rescore", action="store_true",
        help="recompute correctness from stored verdicts without model calls",
    )
    args = parser.parse_args()
    config, cases = load_cases()
    if args.rescore:
        data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        data["records"] = rescore(data["records"], cases)
        data = refresh_accuracy(data)
        Path(args.json).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        markdown = render_markdown(data)
        Path(args.md).write_text(markdown, encoding="utf-8")
        print(markdown)
        return
    router = Router(config=config)
    offset = (
        DEFAULT_USAGE_PATH.stat().st_size if DEFAULT_USAGE_PATH.exists() else 0
    )
    records = run_benchmark(cases, args.runs)
    summary = summarize(records, read_new_usage(offset), config)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_case": args.runs,
        "config": {
            "roles": config.get("roles", {}),
            "hedge_after_seconds": config.get("settings", {}).get(
                "hedge_after_seconds", 25
            ),
            "models": {
                name: spec["model"] for name, spec in router._providers.items()
            },
        },
        "cases": [
            {"id": case["id"], "description": case["description"]}
            for case in cases
        ],
        "records": records,
        "summary": summary,
    }
    Path(args.json).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(data)
    Path(args.md).write_text(markdown, encoding="utf-8")
    print()
    print(markdown)
    print(f"wrote {args.json}")
    print(f"wrote {args.md}")
    if summary["totals"]["failed_runs"] >= len(records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
