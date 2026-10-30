# FaultCase

**From fault to case.** FaultCase turns repeated crashes and failures on a Windows laptop into a warranty case ready to send to the manufacturer, without the user having to understand a single error code.

> Built with Muse Spark Open

## The problem

When a new laptop keeps rebooting on its own, the problem usually falls between three companies: Microsoft (the OS), the GPU vendor (the driver) and the laptop manufacturer (the warranty). Each one sees only its own piece. The user ends up with blurry phone photos of a blue screen and a support team asking for data they don't know where to find.

This project was born from a real case: a Lenovo laptop bought in January 2026 with 6 unexpected reboots in 6 months. All 4 that left a memory dump point to the NVIDIA driver (`nvlddmkm.sys`), across at least two different driver builds. Reaching that conclusion by hand took a full night with Event Viewer and WinDbg. FaultCase does it in minutes.

## What it does

1. **Collect**: the user exports a file Windows already has (a filtered event log), guided step by step. Nothing to install.
2. **Diagnose**: an agent separates signal from noise, classifies every failure, finds the pattern and rates how confident the diagnosis is.
3. **Act**: it produces the case for the manufacturer (English/Spanish), a pre-claim checklist and an evidence package.

It is not a chatbot and not an image analyzer: it is a three-screen flow that ends in a concrete action.

## Meta models

| Role | Model | Provider |
|---|---|---|
| Writing the case and explaining it to the user | Muse Spark | Meta Model API |
| Technical evidence analysis (privacy, open weights) | Muse Spark Open | Baseten |
| Automatic fallback and tests | Muse Spark Open | Fireworks AI |
| Building the project | Muse Code | Terminal |

## Architecture

```
Browser ──► Web app (FastAPI on Modal)
              ├─ .evtx / msinfo32 parsers ─► normalized evidence (no personal data)
              ├─ Rules engine (playbooks/*.yaml)
              └─ Model router (config/providers.yaml)
                    ├─ Meta Model API · Muse Spark
                    ├─ Baseten        · Muse Spark Open
                    └─ Fireworks AI   · Muse Spark Open
Local mode (Windows): + minidump analysis with cdb.exe
```

Design principles: read-only, deterministic rules for counts and patterns, models only for interpretation and writing, every fact labeled as `fact` or `hypothesis`, raw memory dumps never leave the user's machine.

## Setup (Windows)

```powershell
git clone https://github.com/<your-user>/faultcase.git
cd faultcase
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in your API keys
uvicorn faultcase.app:app --reload
```

## License

Code: MIT. Muse Spark Open is used under the Muse Model License, which requires displaying "Built with Muse Spark Open" in the product.
