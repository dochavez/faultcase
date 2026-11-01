# FaultCase

**From fault to case.** FaultCase turns repeated crashes on a Windows laptop into a warranty case ready to send to the manufacturer.

> Built with Muse Spark Open

**Live demo:** `[DEMO URL — added after Modal deploy]`

**Screenshots:** `[to be added: Collect → Diagnosis → Action]`

## The problem

When a new laptop keeps rebooting on its own, the problem falls between three companies: Microsoft (the OS), the GPU vendor (the driver) and the laptop manufacturer (the warranty). Each one sees only its own piece. The user ends up with blurry phone photos of a blue screen and a support team asking for data they don't know where to find.

This project was born from a real case: a Lenovo laptop bought in January 2026 with 6 unexpected reboots in 6 months. All 4 that left a memory dump point to the NVIDIA driver (`nvlddmkm.sys`), across two different driver builds — while two more freezes left no dump at all. Reaching that conclusion by hand took a full night with Event Viewer and WinDbg. FaultCase does it in minutes, and ships that real anonymized case as its one-click demo.

## Try it in 1 minute

Open the demo URL above and click **Try a sample case** — no account, no invite code, instant and free (the demo case is precomputed).

Or run it locally. Prerequisites: Python 3.11 and a clone of this repo.

**Windows (PowerShell):**

```powershell
git clone https://github.com/dochavez/faultcase.git
cd faultcase
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in your API keys (only needed for new diagnoses, not for the demo)
uvicorn faultcase.app:app --reload
```

**macOS / Linux:**

```bash
git clone https://github.com/dochavez/faultcase.git
cd faultcase
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys (only needed for new diagnoses, not for the demo)
uvicorn faultcase.app:app --reload
```

Then open http://127.0.0.1:8000 and click **Try a sample case**.

## Analyze your own Windows laptop

1. Open this app and click **Download device-diagnostics.xml** (step 1 on the Collect screen).
2. On your laptop, open Event Viewer → Action → **Import Custom View…** → select the downloaded file.
3. Action → **Save All Events in Custom View As…** → save the `.evtx` file.
4. Back in the app, upload the `.evtx` (max 20 MB) with your invite code — optionally ticking **Also analyze my memory dumps** if you have `cdb.exe` and administrator rights.
5. Read the diagnosis, then open the Action screen for the manufacturer report (English/Spanish), the pre-claim checklist and the evidence package.

## How the Meta models are used

| Role | Model | Provider |
|---|---|---|
| Technical evidence analysis | Muse Spark Open | Baseten, with Fireworks AI fallback |
| Writing the case and explaining it to the user | Muse Spark | Meta Model API |
| Building the project | Muse Code | Terminal |

Deterministic Python computes every count, date, code and pattern; the models only interpret and write, and every conclusion is labeled `fact` or `hypothesis`.

## Architecture

```
Browser ──► Web app (FastAPI + Jinja2 + HTMX, EN/ES)
              ├─ Collect: guide + .evtx upload (+ local minidumps on Windows)
              ├─ .evtx / WinDbg parsers ─► normalized evidence (personal data redacted)
              ├─ Rules engine (playbooks/*.yaml) ─► incidents, patterns, healthy parts
              └─ Model router (config/providers.yaml)
                    ├─ Baseten    · Muse Spark Open  (evidence analysis)
                    ├─ Fireworks  · Muse Spark Open  (fallback)
                    └─ Meta       · Muse Spark       (case writing)
```

Deployment: Modal (`modal_app.py`) with secrets for the API keys.

## Privacy guarantees

- Read-only: the product never modifies the user's system.
- Nothing reaches a model without going through `redact.py` (user names, computer names, serials, MACs, emails, personal paths).
- Raw `.evtx` uploads live only in memory and a temp folder, deleted right after parsing.
- `.dmp` memory dumps are analyzed locally with `cdb.exe` and never leave the machine — nor do they enter the evidence ZIP.
- The serial number is inserted locally at the very end; models only ever see the `{{SERIAL}}` placeholder.

## Run the tests

```bash
pytest            # full suite, no network and no API keys needed
pytest -m live    # builds the real case with real models (needs API keys in .env)
```

## Project layout

```
faultcase/                 # Python package
  adapters/windows/        # evtx.py, windbg.py, fixture_events.py, cdb.py (local only)
  app.py                   # FastAPI, 3 screens + /demo
  agent.py                 # findings → analysis → case
  normalize.py             # raw events → schemas/evidence.schema.json
  redact.py                # personal-data removal
  rules.py                 # playbooks → deterministic findings
  router.py                # providers with fallback + usage log
  demo.py / i18n.py        # precomputed demo, EN/ES strings
templates/ static/         # Jinja2 pages, CSS
config/ filters/ playbooks/ prompts/ schemas/
fixtures/real_case/        # real anonymized case + precomputed demo_case.json
scripts/                   # smoke_test.py, build_demo_case.py
tests/                     # pytest suite (live tests need keys)
modal_app.py               # Modal deployment
```

## Roadmap

- More playbooks (battery, Wi-Fi, USB devices).
- Linux and macOS adapters (the adapter layout is ready for them).
- Optional msinfo32 import: richer device data in the manufacturer report.

## License

Code: MIT. Muse Spark Open is used under the Muse Model License, which requires displaying "Built with Muse Spark Open" in the product.
