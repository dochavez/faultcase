# FaultCase — rules for Muse Code

Read this whole file before every task.

## What the project is
A web tool that turns repeated failures on a Windows laptop into a warranty case. Three-screen flow: Collect → Diagnosis → Action. It is NOT a chatbot and does NOT analyze images. All code, comments, docs and commit messages are in English. The product UI supports English and Spanish.

## Stack
- Python 3.11, FastAPI, Pydantic v2, Jinja2 + HTMX (no heavy JS frameworks).
- `python-evtx` to read `.evtx` files (works on Linux, no Windows needed).
- `openai` client (OpenAI-compatible) for all three providers.
- `pytest` for tests. Deployment on Modal.
- Development happens on native Windows (PowerShell). Use `pathlib`, never hardcoded `/` paths.

## Layout
```
faultcase/                 # Python package
  adapters/windows/        # evtx.py, windbg.py, fixture_events.py, msinfo.py, cdb.py (local only)
  app.py                   # FastAPI, 3 screens + /demo
  agent.py                 # findings → analysis (Baseten/Fireworks) → case (Meta)
  normalize.py             # maps everything to schemas/evidence.schema.json
  redact.py                # removes user name, computer name, serial, MAC, personal paths
  rules.py                 # applies playbooks/*.yaml and produces findings
  router.py                # picks a provider per role with fallback (config/providers.yaml)
  demo.py / i18n.py        # precomputed demo builders, EN/ES strings
templates/ static/         # Jinja2 pages, CSS
config/ filters/ playbooks/ prompts/ schemas/ fixtures/ tests/
scripts/                   # smoke_test.py, build_demo_case.py
modal_app.py               # Modal deployment
```

## Mandatory rules
1. **Privacy**: no data reaches a model without going through `redact.py`. `.dmp` files never leave the machine. A test enforces this.
2. **Read-only**: the product never modifies the user's system.
3. **Deterministic logic first**: counts, dates, codes and patterns are computed in Python by `rules.py`. Models interpret and write; they never count or invent data.
4. **Structured output**: every model response is validated against `schemas/case.schema.json`. On failure, retry once, then move to the next provider.
5. **Honesty**: always separate `fact` from `hypothesis`. The same FAILURE_BUCKET_ID / FAILURE_ID_HASH means the same failure *category*; it does NOT prove the same defect as other machines.
6. **No legal advice**: the product prepares evidence and drafts; the user decides and sends.
7. **API keys** only in environment variables (`.env`), never in code or the frontend.
8. Show "Built with Muse Spark Open" in the footer of every screen.

## Providers
See `config/providers.yaml`. All three are OpenAI-compatible:
- Meta Model API: `https://api.meta.ai/v1`, key `META_API_KEY`.
- Baseten: `https://inference.baseten.co/v1`, key `BASETEN_API_KEY`, model `meta-models/muse-spark-open-1026` (the hackathon key only works with this exact model).
- Fireworks: `https://api.fireworks.ai/inference/v1`, key `FIREWORKS_API_KEY`, model `accounts/fireworks/models/muse-spark-open`.

## Tests
- `pytest` must pass before any task is considered done.
- `fixtures/real_case/` holds a real case; `fixtures/real_case/expected.json` defines the conclusions the system MUST reach. Never edit `expected.json` to make tests pass.
- Tests that call real models are marked `@pytest.mark.live` and skipped by default.

## Event provider names
Playbooks use partial matching (`provider_contains`). Verify them against a real `.evtx` before relying on them.
