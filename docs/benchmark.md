# Provider benchmark

Generated: 2026-11-01T23:31:07.659293+00:00 · runs per case: 3 · failed runs: 0

Config: case_writing=single/medium, evidence_analysis=second_opinion/medium · hedge_after=25s
baseten=meta-models/muse-spark-open-1026 · fireworks=accounts/fireworks/models/muse-spark-open · meta=muse-spark-1.1

Correctness: real-case final verdict must be in expected.json acceptable_verdicts; every other verdict matches when it contains an expected keyword (case-insensitive). Costs use the example prices in config/providers.yaml.

## By provider and role

| Provider | Role | Calls ok/total | Correct | p50 ms | p95 ms | Prompt | Compl | Cached | Est. cost | Fallbacks | Hedge wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseten | evidence_analysis | 12/12 | 100% (12/12) | 19728 | 26194 | 22998 | 32767 | 12928 | $0.2887 | 0 | 0 |
| fireworks | evidence_analysis | 12/12 | 100% (12/12) | 14718 | 23649 | 22986 | 19019 | 16192 | $0.1738 | 0 | 0 |
| meta | case_writing | 12/12 | 100% (12/12) | 12296 | 17566 | 24351 | 47280 | 13644 | $0.6097 | 0 | 0 |

## Second-opinion agreement

Agreement rate: 100% (agreed runs / runs with two opinions).

| Case | Runs | Agreed | Disagreed | Single opinion |
| --- | --- | --- | --- | --- |
| disk_failure | 3 | 3 | 0 | 0 |
| healthy | 3 | 3 | 0 | 0 |
| real_case | 3 | 3 | 0 | 0 |
| single_crash | 3 | 3 | 0 | 0 |

## Totals

Runs: 12 · hedges: 0 · estimated cost: $1.0722.

## Notes

- Agreement requires the same verdict enum and the same confidence level; mismatches lower confidence one level and add a hypothesis finding to the case.
- Keyword lists include synonyms observed in model output (e.g. inconclusive); see fixtures/synthetic/*.json.
