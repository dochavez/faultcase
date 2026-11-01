"""Three-screen web app: Collect -> Diagnosis -> Action.

Collect (/): guide to export the Windows event log, filter download,
.evtx upload (invite code required) and a no-code demo button.
Diagnosis (/case/{id}): timeline, verdict, confidence, labeled findings,
healthy components and one call to action. Action (/case/{id}/action):
manufacturer report in English/Spanish, checklist and evidence ZIP.
Uploaded files live only in memory and a temp folder, deleted right after.
"""

from __future__ import annotations

import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from faultcase.adapters.windows import evtx as evtx_adapter
from faultcase.adapters.windows import fixture_events, windbg
from faultcase.agent import build_case
from faultcase.i18n import STRINGS, get_lang
from faultcase.normalize import normalize
from faultcase.router import RouterError
from faultcase.rules import apply_rules
from faultcase.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

settings = load_settings()

app = FastAPI(title="FaultCase")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

CASES: dict[str, dict] = {}


def _ctx(lang: str, **extra) -> dict:
    return {"lang": lang, "t": STRINGS[lang], **extra}


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _error(request: Request, lang: str, message: str):
    if _is_htmx(request):
        return templates.TemplateResponse(
            request, "error_box.html", _ctx(lang, message=message)
        )
    return templates.TemplateResponse(
        request, "collect.html", _ctx(lang, error=message, message=message),
        status_code=400,
    )


def _store_case(findings: dict, built: dict, summaries: dict[str, str]) -> str:
    case_id = uuid.uuid4().hex[:12]
    CASES[case_id] = {
        "findings": findings,
        "case": built["case"],
        "metadata": built["metadata"],
        "summaries": summaries,
    }
    return case_id


def _parse_upload(content: bytes) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.evtx"
        path.write_bytes(content)
        return evtx_adapter.parse_evtx(path).events


def _demo_evidence() -> tuple[dict, dict[str, str]]:
    real = ROOT / "fixtures" / "real_case"
    events = fixture_events.load_fixture_events(real / "events_41.json")
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
    summaries = {}
    for path in sorted((real / "windbg").glob("*.txt")):
        summaries[path.name] = path.read_text(encoding="utf-8")
        dumps.append({
            "file": path.name.replace(".txt", ".dmp"),
            **windbg.parse_windbg(path),
        })
    return normalize(events, dumps).evidence, summaries


@app.get("/", response_class=HTMLResponse)
def collect(request: Request):
    lang = get_lang(request.query_params.get("lang"))
    return templates.TemplateResponse(request, "collect.html", _ctx(lang))


@app.get("/filter/device-diagnostics.xml")
def download_filter():
    return FileResponse(
        ROOT / "filters" / "device-diagnostics.xml",
        media_type="application/xml",
        filename="device-diagnostics.xml",
    )


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    invite_code: str = Form(""),
    lang: str = Form("en"),
):
    lang = get_lang(lang)
    t = STRINGS[lang]
    if settings.invite_code and invite_code.strip() != settings.invite_code:
        return _error(request, lang, t["err_invite"])
    name = (file.filename or "").lower()
    if not name.endswith(".evtx"):
        return _error(request, lang, t["err_file_type"])
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return _error(request, lang, t["err_too_big"])
    if not content:
        return _error(request, lang, t["err_empty"])
    try:
        raw_events = _parse_upload(content)
    except Exception:
        return _error(request, lang, t["err_parse"])
    evidence = normalize(raw_events, []).evidence
    if not evidence["events"]:
        return _error(request, lang, t["err_no_events"])
    try:
        built = build_case(evidence, ui_language=lang, device=None)
    except (RouterError, ValueError) as exc:
        return _error(request, lang, f"{t['err_agent']}: {exc}")
    findings = apply_rules(evidence)
    case_id = _store_case(findings, built, {})
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.post("/demo")
async def demo(request: Request, lang: str = Form("en")):
    lang = get_lang(lang)
    t = STRINGS[lang]
    evidence, summaries = _demo_evidence()
    device = {"manufacturer": "Lenovo", "gpu": "NVIDIA", "purchase_date": "2026-01"}
    try:
        built = build_case(evidence, ui_language=lang, device=device)
    except (RouterError, ValueError) as exc:
        return _error(request, lang, f"{t['err_agent']}: {exc}")
    findings = apply_rules(evidence)
    case_id = _store_case(findings, built, summaries)
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def _get_case(case_id: str) -> dict | None:
    return CASES.get(case_id)


@app.get("/case/{case_id}", response_class=HTMLResponse)
def diagnosis(request: Request, case_id: str):
    lang = get_lang(request.query_params.get("lang"))
    stored = _get_case(case_id)
    if stored is None:
        return templates.TemplateResponse(
            request, "error.html",
            _ctx(lang, message=STRINGS[lang]["err_not_found"]),
            status_code=404,
        )
    case = stored["case"]
    healthy = case.get("healthy_components") or [
        entry["note"] for entry in stored["findings"]["healthy"]
    ]
    return templates.TemplateResponse(
        request, "diagnosis.html",
        _ctx(lang, case_id=case_id, case=case,
             incidents=stored["findings"]["incidents"],
             healthy=healthy, metadata=stored["metadata"]),
    )


@app.get("/case/{case_id}/action", response_class=HTMLResponse)
def action(request: Request, case_id: str):
    lang = get_lang(request.query_params.get("lang"))
    stored = _get_case(case_id)
    if stored is None:
        return templates.TemplateResponse(
            request, "error.html",
            _ctx(lang, message=STRINGS[lang]["err_not_found"]),
            status_code=404,
        )
    return templates.TemplateResponse(
        request, "action.html",
        _ctx(lang, case_id=case_id, case=stored["case"]),
    )


@app.get("/case/{case_id}/evidence.zip")
def evidence_zip(case_id: str):
    stored = _get_case(case_id)
    if stored is None:
        return Response(status_code=404)
    report = stored["case"]["manufacturer_report"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("findings.json", json.dumps(stored["findings"], indent=2))
        archive.writestr(
            "report_en.txt", f"{report.get('subject', '')}\n\n{report['body_en']}"
        )
        archive.writestr(
            "report_es.txt", f"{report.get('subject', '')}\n\n{report['body_es']}"
        )
        for name, text in stored["summaries"].items():
            archive.writestr(f"windbg/{name}", text)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=evidence-{case_id}.zip"},
    )
