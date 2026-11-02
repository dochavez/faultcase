# Provider benchmark

Generated: 2026-11-02T00:45:44.395881+00:00 · runs per case: 3 · failed runs: 0

Config: case_writing=single/medium, evidence_analysis=second_opinion/medium · hedge_after=25s
baseten=meta-models/muse-spark-open-1026 · fireworks=accounts/fireworks/models/muse-spark-open · meta=muse-spark-1.1

Correctness: final verdicts match against the case's acceptable list when present (real case: expected.json acceptable_verdicts), else against expected keywords (case-insensitive). Costs use the example prices in config/providers.yaml.

## By provider and role

| Provider | Role | Calls ok/total | Correct | p50 ms | p95 ms | Prompt | Compl | Cached | Est. cost | Fallbacks | Hedge wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseten | evidence_analysis | 21/21 | 100% (21/21) | 19975 | 26104 | 46611 | 59619 | 28928 | $0.5268 | 0 | 0 |
| fireworks | evidence_analysis | 21/21 | 100% (21/21) | 16465 | 31516 | 46590 | 36432 | 32128 | $0.3364 | 0 | 0 |
| meta | case_writing | 21/21 | 100% (21/21) | 12347 | 16926 | 50314 | 80466 | 26467 | $1.0570 | 0 | 0 |

## Second-opinion agreement

Agreement rate: 71% (agreed runs / runs with two opinions).

| Case | Runs | Agreed | Disagreed | Single opinion |
| --- | --- | --- | --- | --- |
| battery | 3 | 3 | 0 | 0 |
| disk_failure | 3 | 3 | 0 | 0 |
| healthy | 3 | 1 | 2 | 0 |
| real_case | 3 | 2 | 1 | 0 |
| single_crash | 3 | 3 | 0 | 0 |
| usb | 3 | 1 | 2 | 0 |
| wifi | 3 | 2 | 1 | 0 |

## Totals

Runs: 21 · hedges: 0 · estimated cost: $1.9202.

## Notes

- Agreement requires the same verdict enum and the same confidence level; mismatches lower confidence one level and add a hypothesis finding to the case.
- Keyword lists include synonyms observed in model output (e.g. inconclusive); see fixtures/synthetic/*.json.
