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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from faultcase.adapters.windows import evtx as evtx_adapter
from faultcase.adapters.windows import cdb
from faultcase.agent import build_case
from faultcase.demo import DEMO_CASE_PATH, DEMO_DEVICE, build_demo_evidence
from faultcase.demo import load_demo_summaries
from faultcase.i18n import STRINGS, get_lang
from faultcase.normalize import normalize
from faultcase.router import RouterError
from faultcase.rules import apply_rules
from faultcase.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

settings = load_settings()

LOCAL_DUMPS_AVAILABLE = cdb.find_cdb() is not None

app = FastAPI(title="FaultCase")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

CASES: dict[str, dict] = {}


def _ctx(lang: str, **extra) -> dict:
    return {"lang": lang, "t": STRINGS[lang], **extra}


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _error(request: Request, lang: str, message: str, page: str = "collect.html"):
    if _is_htmx(request):
        return templates.TemplateResponse(
            request, "error_box.html", _ctx(lang, message=message)
        )
    ctx = _ctx(lang, error=message, message=message,
               local_dumps=LOCAL_DUMPS_AVAILABLE)
    return templates.TemplateResponse(request, page, ctx, status_code=400)


def _store_case(
    findings: dict,
    built: dict,
    summaries: dict[str, str],
    local_dumps: dict | None = None,
    is_demo: bool = False,
    timezone: str = "UTC",
) -> str:
    case_id = uuid.uuid4().hex[:12]
    CASES[case_id] = {
        "findings": findings,
        "case": built["case"],
        "metadata": built["metadata"],
        "summaries": summaries,
        "local_dumps": local_dumps,
        "is_demo": is_demo,
        "timezone": timezone,
    }
    return case_id


def _parse_upload(content: bytes) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.evtx"
        path.write_bytes(content)
        return evtx_adapter.parse_evtx(path).events


@app.get("/", response_class=HTMLResponse)
def collect(request: Request):
    lang = get_lang(request.query_params.get("lang"))
    return templates.TemplateResponse(
        request, "collect.html", _ctx(lang, local_dumps=LOCAL_DUMPS_AVAILABLE)
    )


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
    local_dumps: str = Form(""),
    tz: str = Form("UTC"),
):
    lang = get_lang(lang)
    t = STRINGS[lang]
    tz = _safe_tz(tz)
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
    dump_inputs: list[dict] = []
    summaries: dict[str, str] = {}
    local_stats: dict | None = None
    if local_dumps and LOCAL_DUMPS_AVAILABLE:
        records = cdb.collect_minidumps()
        fatal = next((r for r in records if r["file"] is None), None)
        if fatal is not None:
            return _error(request, lang, f"{t['err_minidump']} ({fatal['error']})")
        ok = failed = 0
        for record in records:
            if record["dump"] is not None:
                dump_inputs.append({"file": record["file"], **record["dump"]})
                summaries[record["file"] + ".txt"] = record["summary"] or ""
                ok += 1
            else:
                failed += 1
        local_stats = {"ok": ok, "failed": failed}
    evidence = normalize(raw_events, dump_inputs).evidence
    if not evidence["events"]:
        return _error(request, lang, t["err_no_events"])
    try:
        built = await run_in_threadpool(build_case, evidence, lang, None, tz)
    except (RouterError, ValueError) as exc:
        return _error(request, lang, f"{t['err_agent']}: {exc}")
    findings = apply_rules(evidence, tz=tz)
    case_id = _store_case(findings, built, summaries, local_stats, timezone=tz)
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.post("/demo")
async def demo(request: Request, lang: str = Form("en")):
    lang = get_lang(lang)
    t = STRINGS[lang]
    if not DEMO_CASE_PATH.exists():
        return _error(request, lang, t["err_demo_missing"])
    data = json.loads(DEMO_CASE_PATH.read_text(encoding="utf-8"))
    entry = data[lang]
    case_id = _store_case(
        data["findings"],
        {"case": entry["case"], "metadata": entry["metadata"]},
        load_demo_summaries(),
        is_demo=True,
        timezone=data.get("timezone", "UTC"),
    )
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.post("/case/{case_id}/regenerate")
async def regenerate(
    request: Request,
    case_id: str,
    invite_code: str = Form(""),
    lang: str = Form("en"),
):
    lang = get_lang(lang)
    t = STRINGS[lang]
    stored = _get_case(case_id)
    if stored is None or not stored.get("is_demo"):
        return templates.TemplateResponse(
            request, "error.html",
            _ctx(lang, message=STRINGS[lang]["err_not_found"]),
            status_code=404,
        )
    if not settings.invite_code or invite_code.strip() != settings.invite_code:
        return _error(request, lang, t["err_invite"], page="error.html")
    evidence, summaries = build_demo_evidence()
    try:
        built = await run_in_threadpool(
            build_case, evidence, lang, DEMO_DEVICE, stored.get("timezone", "UTC")
        )
    except (RouterError, ValueError) as exc:
        return _error(request, lang, f"{t['err_agent']}: {exc}", page="error.html")
    stored["case"] = built["case"]
    stored["metadata"] = built["metadata"]
    stored["summaries"] = summaries
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def _get_case(case_id: str) -> dict | None:
    return CASES.get(case_id)


def _safe_tz(value: str | None) -> str:
    try:
        ZoneInfo(value or "UTC")
        return value or "UTC"
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return "UTC"


def _expired(request: Request, lang: str):
    return templates.TemplateResponse(
        request, "error.html",
        _ctx(lang, message=STRINGS[lang]["err_expired"]),
    )


@app.get("/case/{case_id}", response_class=HTMLResponse)
def diagnosis(request: Request, case_id: str):
    lang = get_lang(request.query_params.get("lang"))
    stored = _get_case(case_id)
    if stored is None:
        return _expired(request, lang)
    case = stored["case"]
    healthy = case.get("healthy_components") or [
        entry["note"] for entry in stored["findings"]["healthy"]
    ]
    return templates.TemplateResponse(
        request, "diagnosis.html",
        _ctx(lang, case_id=case_id, case=case,
             incidents=stored["findings"]["incidents"],
             healthy=healthy, metadata=stored["metadata"],
             local_dumps=stored.get("local_dumps"),
             is_demo=stored.get("is_demo", False),
             timezone=stored.get("timezone", "UTC")),
    )


@app.get("/case/{case_id}/action", response_class=HTMLResponse)
def action(request: Request, case_id: str):
    lang = get_lang(request.query_params.get("lang"))
    stored = _get_case(case_id)
    if stored is None:
        return _expired(request, lang)
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
