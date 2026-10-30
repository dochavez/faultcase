# Build plan with Muse Code (Oct 30 → Nov 4, 2026)

**Deadline:** Wednesday, November 4, 9:00 PM ET (8:00 PM Central America). Internal target: submit by 5:00 PM local.

**How to work with Muse Code:** one prompt per block, always with a done criterion ("make sure pytest passes"). Review every diff before accepting it and commit at the end of each block.

---

## Day 0 · Friday Oct 30: setup

### 0.1 Muse Code on Windows
Muse Code runs natively in PowerShell. Stay on native Windows: the project needs PowerShell, Event Viewer and `cdb.exe`, which only exist there. Use WSL only if something breaks.

Check: Git, Python 3.11 (`py -3.11 --version`) and Muse Code.

### 0.2 Repository
1. On github.com → **New repository** → name `faultcase`, public, no README (the kit includes one).
2. In PowerShell:
   ```powershell
   cd $HOME\Documents
   # unzip faultcase-kit.zip here; you get the faultcase folder
   cd faultcase
   git init -b main
   git add .
   git commit -m "Initial FaultCase kit"
   git remote add origin https://github.com/<your-user>/faultcase.git
   git push -u origin main
   ```

### 0.3 API keys (all three)
1. **Meta Model API:** Meta developer console → create an API key. Check which Muse Spark version the hackathon assigned.
2. **Baseten:** app.baseten.co → Settings → API Keys. Model: `meta-models/muse-spark-open-1026` (the hackathon key only works with this exact model).
3. **Fireworks:** app.fireworks.ai → API Keys → Create API Key (copy it immediately; it is shown only once). Confirm the hackathon credits under Billing. Model: `accounts/fireworks/models/muse-spark-open`, unless the hackathon gives you a specific one.
4. `copy .env.example .env` and fill in the keys. `.env` is gitignored: never push it.

### 0.4 Smoke test for all three providers
First Muse Code prompt:
> "Read MUSE_CODE.md. Create `scripts/smoke_test.py` that loads `.env`, reads `config/providers.yaml` and makes a minimal call to each provider (meta, baseten, fireworks) with the `openai` client, asking it to reply only 'ok'. Print provider, model, latency and tokens. If one fails, print the full error and continue with the others. Run it and show me the result."

**Don't continue until all three respond.**

### 0.5 Export your real evidence
Event Viewer → Action → **Import Custom View...** → `filters/device-diagnostics.xml` → **Save All Events in Custom View As...** → `fixtures/real_case/failures.evtx`. Note how many events appear.

---

## Day 1 · Saturday Oct 31: ingestion and rules (no models)

> "Read MUSE_CODE.md and schemas/evidence.schema.json. Create `faultcase/ingest/evtx.py` using python-evtx: read an .evtx and extract per event: time, log, provider, EventID and all EventData fields as a dict. Create `faultcase/ingest/windbg.py` that parses `!analyze -v` and `lmvm` output (see fixtures/real_case/windbg/) into the `dumps` fields of the schema. Create `faultcase/normalize.py` that assigns each event its `kind` and `playbook` from playbooks/*.yaml (match on event_id + provider_contains) and groups 41 and 6008 events less than 60 s apart under one `incident_id`. Add tests with the fixtures. pytest must pass."

> "Create `faultcase/redact.py`: remove the Windows user name, computer name (DESKTOP-xxxx), serial number, MAC addresses and C:\Users\<name> paths. Test that no redacted text contains the test user name or 'DESKTOP-'."

> "Create `faultcase/rules.py`: apply each playbook's `patterns` and produce deterministic findings (counts, dates, decimal→hex codes, modules, driver timestamps). Create `tests/test_real_case.py` that builds the evidence from events_41.json + windbg/*.txt and checks EVERYTHING in fixtures/real_case/expected.json except verdict and confidence (those come from the model). pytest must pass."

Commit when done.

---

## Day 2 · Sunday Nov 1: router and agent (Meta models)

> "Create `faultcase/router.py`: read config/providers.yaml, create one openai client per provider and expose `call(role, messages, response_schema)`. For each provider in the route: try, validate the output against the JSON schema, retry once if invalid, and on failure move to the next one. Log provider, model, latency, tokens and whether a fallback happened to `logs/usage.jsonl`. Tests with a fake client that simulates a Baseten failure and checks that Fireworks answers."

> "Create `faultcase/agent.py` with `build_case(evidence, ui_language) -> dict`: (1) rules.py computes findings; (2) redact.py cleans them; (3) router role `evidence_analysis` with prompts/evidence_analysis.md; (4) router role `case_writing` with prompts/case_writer.md, validated against schemas/case.schema.json; (5) insert {{SERIAL}} only at the end and only locally. Add a live test (@pytest.mark.live) on the real case that checks verdict, minimum confidence and that none of the `must_not_claim` statements appear."

Run `pytest -m live` once with your keys and save the output: it's material for the video.

---

## Day 3 · Monday Nov 2: the web app (3 screens)

> "Create `faultcase/app.py` (FastAPI + Jinja2 + HTMX) with 3 screens and an English/Spanish language toggle: 1) Collect: 4-step illustrated guide to export the .evtx with filters/device-diagnostics.xml (button to download the filter), upload form (.evtx and optional msinfo32 .txt, max 20 MB), and a 'Try a sample case' button; 2) Diagnosis: simple incident timeline, verdict, confidence and findings labeled fact/hypothesis, plus 'healthy components'; 3) Action: copyable EN/ES manufacturer report, checklist and a button to download an evidence ZIP. Footer: 'Built with Muse Spark Open'. Protect uploads with INVITE_CODE. Demo mode uses fixtures/real_case. Clean, accessible design that works on mobile."

> "Create `modal_app.py` to deploy the app on Modal with the secrets META_API_KEY, BASETEN_API_KEY, BASETEN_MODEL, FIREWORKS_API_KEY and INVITE_CODE. Give me the exact commands to create the secrets and deploy."

Deploy and test demo mode from your phone.

---

## Day 4 · Tuesday Nov 3: local mode + user testing

> "Create `faultcase/local/cdb.py`: on Windows only, if cdb.exe is found, run `cdb -z <dump> -y srv*%LOCALAPPDATA%\symbols*https://msdl.microsoft.com/download/symbols -c \"!analyze -v; lmvm nvlddmkm; q\"` and pass the output to ingest/windbg.py. On screen 1, only when the app runs locally on Windows, add the option 'Also analyze my memory dumps'. .dmp files are never sent to any model."

Test with 3 to 5 people (ideally non-technical). Watch them without helping. Record where they get stuck, time to diagnosis and the answer to "Did you understand what's wrong with your computer? (1 to 5)". Fix the worst issue.

---

## Day 5 · Wednesday Nov 4: video and submission

- **Morning:** feature freeze. Fixes only.
- **Video (2 to 3 min):**
  1. The problem (20 s): blue-screen photos, "6 reboots on a new laptop".
  2. What it took by hand (20 s): a night with Event Viewer and WinDbg.
  3. Demo (90 s): export → upload → diagnosis → case ready.
  4. How it works (30 s): deterministic rules + Muse Spark Open (Baseten/Fireworks) for evidence + Muse Spark (Meta Model API) for the case + built with Muse Code. Privacy: read-only, .dmp never leaves the machine.
  5. Roadmap (10 s): more playbooks, macOS/Linux as adapters.
- **Submit by 5:00 PM local.** Check the platform for exactly what is required: repo link, video, demo URL, description.

---

## If something slips (cut order)
1. Cut first: local mode with cdb (use the WinDbg fixtures in the video).
2. Then: msinfo32.
3. Never cut: .evtx ingestion, rules, agent, the 3 screens, demo mode.
