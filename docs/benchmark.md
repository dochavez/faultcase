# Provider benchmark

Generated: 2026-11-01T22:07:25.558258+00:00 · runs per case: 3 · failed runs: 0

Config: case_writing=single/medium, evidence_analysis=second_opinion/high · hedge_after=25s
baseten=meta-models/muse-spark-open-1026 · fireworks=accounts/fireworks/models/muse-spark-open · meta=muse-spark-1.1

Correctness: real-case final verdict must be in expected.json acceptable_verdicts; every other verdict matches when it contains an expected keyword (case-insensitive). Costs use the example prices in config/providers.yaml.

## By provider and role

| Provider | Role | Calls ok/total | Correct | p50 ms | p95 ms | Prompt | Compl | Cached | Est. cost | Fallbacks | Hedge wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseten | evidence_analysis | 10/15 | 100% (10/10) | 10704 | 22680 | 28502 | 188523 | 18048 | $1.5381 | 0 | 0 |
| fireworks | evidence_analysis | 12/12 | 100% (12/12) | 23054 | 31802 | 22194 | 30266 | 15040 | $0.2640 | 0 | 0 |
| meta | case_writing | 12/12 | 100% (12/12) | 11218 | 13489 | 25516 | 44753 | 10233 | $0.5906 | 0 | 0 |

## Second-opinion agreement

Agreement rate: 0% (agreed runs / runs with two opinions).

| Case | Runs | Agreed | Disagreed | Single opinion |
| --- | --- | --- | --- | --- |
| disk_failure | 3 | 0 | 2 | 1 |
| healthy | 3 | 0 | 3 | 0 |
| real_case | 3 | 0 | 2 | 1 |
| single_crash | 3 | 0 | 3 | 0 |

## Totals

Runs: 12 · hedges: 0 · estimated cost: $2.3927.

## Notes

- Agreement is an exact case-insensitive match on free-text verdicts, so textually different but equivalent verdicts count as disagreement (by design the case then gets lower confidence plus a hypothesis finding).
- Keyword lists include synonyms observed in model output (e.g. inconclusive); see fixtures/synthetic/*.json.
- baseten/evidence_analysis: 5 failed attempt(s) out of 15 (retried once each, then the other opinion was used).
- All 5 baseten failures returned exactly 32768 completion tokens: the
  model hit the completion cap with reasoning_effort high and the JSON
  came back truncated. 3 recovered on retry, 2 runs continued with the
  Fireworks opinion only. Follow-up: raise the completion limit or use
  medium effort for Baseten.
