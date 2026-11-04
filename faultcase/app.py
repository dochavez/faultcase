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
import os
import re
import tempfile
import threading
import time
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
from faultcase.adapters.windows import battery_report, cdb, msinfo, wmi
from faultcase import agent as agent_module
from faultcase.agent import build_case, explain_case, fix_plan
from faultcase.demo import DEMO_CASE_PATH, DEMO_DEVICE, build_demo_evidence
from faultcase.demo import load_demo_summaries
from faultcase.i18n import INCIDENT_LABELS, STRINGS, get_lang
from faultcase.normalize import normalize
from faultcase import redact
from faultcase.router import RouterError
from faultcase.rules import apply_rules
from faultcase.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_MSINFO_BYTES = 5 * 1024 * 1024
MAX_BATTERY_BYTES = 5 * 1024 * 1024


_DEVICE_KEYS = (
    "manufacturer", "model", "machine_type", "system_sku",
    "bios_version", "bios_date", "os_name", "os_version",
    "purchase_date", "serial",
)


def _build_device(
    msinfo_data: dict | None,
    manual: dict[str, str],
    wmi_data: dict | None = None,
) -> dict:
    """Assemble the device object with per-field sources, redacted.

    msinfo data wins for the fields it provides, manual fields fill the
    gaps, live WMI data fills what is left (serial included). Only
    non-empty values are kept. Sources: "windows_system_information",
    "user_entered" or "local_wmi".
    """
    layers = []
    if msinfo_data:
        layers.append((msinfo_data, "windows_system_information"))
    layers.append(
        (
            {
                "manufacturer": manual.get("manufacturer"),
                "model": manual.get("model"),
                "purchase_date": manual.get("purchase"),
            },
            "user_entered",
        )
    )
    if wmi_data:
        layers.append((wmi_data, "local_wmi"))
    device: dict = {}
    sources: dict[str, str] = {}
    for data, source in layers:
        for key in _DEVICE_KEYS:
            value = data.get(key)
            if isinstance(value, str):
                value = value.strip()
            if value and key not in device:
                device[key] = value
                sources[key] = source
        gpus = [g for g in (data.get("gpus") or []) if g.get("name")]
        if gpus and "gpus" not in device:
            device["gpus"] = gpus
            sources["gpus"] = source
    if device.get("gpus"):
        device["gpu"] = device["gpus"][0]["name"]
        sources["gpu"] = sources["gpus"]
        if device["gpus"][0].get("driver_version"):
            device["gpu_driver_version"] = device["gpus"][0]["driver_version"]
            sources["gpu_driver_version"] = sources["gpus"]
    if sources:
        device["sources"] = sources
    return redact.redact_obj(device)

settings = load_settings()

LOCAL_DUMPS_AVAILABLE = cdb.find_cdb() is not None
LOCAL_WMI_AVAILABLE = wmi.is_available()
LOCAL_BATTERY_AVAILABLE = battery_report.is_available()

app = FastAPI(title="FaultCase")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

CASES: dict[str, dict] = {}


# Changes whenever style.css changes, so browsers never keep a stale copy.
ASSET_VERSION = str(int((ROOT / "static" / "style.css").stat().st_mtime))

# Without an invite code the public site protects API credits with a
# simple per-visitor and global limit on live analyses (in memory: the
# Modal deployment runs a single container).
UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "6"))
UPLOADS_PER_DAY = int(os.environ.get("UPLOADS_PER_DAY", "60"))
_UPLOADS: list[tuple[float, str]] = []
_UPLOADS_LOCK = threading.Lock()


def _client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _take_upload_slot(client: str) -> bool:
    """Record one live analysis; False when a limit is reached."""
    now = time.time()
    with _UPLOADS_LOCK:
        _UPLOADS[:] = [(t, c) for t, c in _UPLOADS if now - t < 86400]
        mine = sum(1 for t, c in _UPLOADS if c == client and now - t < 3600)
        if mine >= UPLOADS_PER_HOUR or len(_UPLOADS) >= UPLOADS_PER_DAY:
            return False
        _UPLOADS.append((now, client))
        return True


def _ctx(lang: str, **extra) -> dict:
    return {
        "lang": lang, "t": STRINGS[lang],
        "invite_required": bool(settings.invite_code),
        "asset_version": ASSET_VERSION, **extra,
    }


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _error(request: Request, lang: str, message: str, page: str = "collect.html"):
    if _is_htmx(request):
        return templates.TemplateResponse(
            request, "error_box.html", _ctx(lang, message=message)
        )
    ctx = _ctx(lang, error=message, message=message,
               local_dumps=LOCAL_DUMPS_AVAILABLE,
               local_wmi=LOCAL_WMI_AVAILABLE,
               local_battery=LOCAL_BATTERY_AVAILABLE)
    return templates.TemplateResponse(request, page, ctx, status_code=400)


def _store_case(
    findings: dict,
    built: dict,
    summaries: dict[str, str],
    local_dumps: dict | None = None,
    is_demo: bool = False,
    timezone: str = "UTC",
    manufacturer: str | None = None,
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
        "manufacturer": manufacturer,
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
        request, "collect.html",
        _ctx(lang, local_dumps=LOCAL_DUMPS_AVAILABLE,
             local_wmi=LOCAL_WMI_AVAILABLE,
             local_battery=LOCAL_BATTERY_AVAILABLE),
    )


@app.get("/filter/device-diagnostics.xml")
def download_filter():
    return FileResponse(
        ROOT / "filters" / "device-diagnostics.xml",
        media_type="application/xml",
        filename="device-diagnostics.xml",
    )


class _PipelineError(Exception):
    """A user-facing error from the upload pipeline (already translated)."""


JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
JOB_STAGES = ("reading", "rules", "analysis", "writing")
# How long the upload request waits for a job before switching to polling.
JOB_INLINE_WAIT_SECONDS = 1.5


def _run_pipeline(job: dict) -> str:
    """Parse, normalize, analyze and store one upload. Returns the case URL.

    Runs in a worker thread; ``job["stage"]`` is updated for the progress
    page. Raises _PipelineError with a translated message on bad input.
    """
    lang = job["lang"]
    t = STRINGS[lang]
    tz = job["tz"]

    def stage(name: str) -> None:
        job["stage"] = name

    stage("reading")
    try:
        raw_events = _parse_upload(job["content"])
    except Exception:
        raise _PipelineError(t["err_parse"])
    msinfo_data = None
    if job.get("msinfo_bytes") is not None:
        try:
            msinfo_data = msinfo.parse_msinfo_bytes(job["msinfo_bytes"])
        except Exception:
            raise _PipelineError(t["err_msinfo"])
        if not any(v for k, v in msinfo_data.items() if k != "gpus") \
                and not msinfo_data.get("gpus"):
            raise _PipelineError(t["err_msinfo"])
    wmi_data = None
    if job["local_wmi"] and LOCAL_WMI_AVAILABLE:
        try:
            wmi_data = wmi.read_device_info()
        except Exception as exc:
            raise _PipelineError(f"{t['err_wmi']} ({exc})")
    battery_data = None
    if job.get("battery_bytes") is not None:
        try:
            battery_data = battery_report.parse_battery_report_bytes(job["battery_bytes"])
        except Exception:
            raise _PipelineError(t["err_battery"])
        if battery_data.get("wear_percent") is None \
                and not battery_data.get("capacity_history"):
            raise _PipelineError(t["err_battery"])
    elif job["local_battery"] and LOCAL_BATTERY_AVAILABLE:
        try:
            battery_data = battery_report.generate_local_report()
        except Exception as exc:
            raise _PipelineError(f"{t['err_battery_gen']} ({exc})")
    device = _build_device(msinfo_data, job["manual"], wmi_data)
    dump_inputs: list[dict] = []
    summaries: dict[str, str] = {}
    local_stats: dict | None = None
    if job["local_dumps"] and LOCAL_DUMPS_AVAILABLE:
        records = cdb.collect_minidumps()
        fatal = next((r for r in records if r["file"] is None), None)
        if fatal is not None:
            raise _PipelineError(f"{t['err_minidump']} ({fatal['error']})")
        ok = failed = 0
        for record in records:
            if record["dump"] is not None:
                dump_inputs.append({"file": record["file"], **record["dump"]})
                summaries[record["file"] + ".txt"] = record["summary"] or ""
                ok += 1
            else:
                failed += 1
        local_stats = {"ok": ok, "failed": failed}
    stage("rules")
    evidence = normalize(raw_events, dump_inputs).evidence
    if battery_data:
        evidence["battery"] = battery_data
    if not evidence["events"]:
        raise _PipelineError(t["err_no_events"])
    if not _take_upload_slot(job["client"]):
        raise _PipelineError(t["err_rate_limit"])
    stage("analysis")
    agent_module.PROGRESS.hook = stage
    try:
        built = build_case(evidence, lang, device or None, tz)
    except (RouterError, ValueError) as exc:
        raise _PipelineError(f"{t['err_agent']}: {exc}")
    finally:
        agent_module.PROGRESS.hook = None
    findings = apply_rules(evidence, tz=tz)
    case_id = _store_case(
        findings, built, summaries, local_stats, timezone=tz,
        manufacturer=(device or {}).get("manufacturer"),
    )
    return f"/case/{case_id}?lang={lang}"


def _job_worker(job: dict) -> None:
    try:
        job["url"] = _run_pipeline(job)
        job["state"] = "done"
    except _PipelineError as exc:
        job["error"], job["state"] = str(exc), "error"
    except Exception as exc:  # never leave the page polling forever
        job["error"] = f"{STRINGS[job['lang']]['err_agent']}: {type(exc).__name__}"
        job["state"] = "error"
    finally:
        for key in ("content", "msinfo_bytes", "battery_bytes"):
            job.pop(key, None)  # uploaded bytes are freed right away


def _start_job(job: dict) -> str:
    job_id = uuid.uuid4().hex[:16]
    job.update({"state": "running", "stage": "reading", "started": time.time()})
    with JOBS_LOCK:
        for old in [k for k, v in JOBS.items() if time.time() - v["started"] > 3600]:
            JOBS.pop(old, None)
        JOBS[job_id] = job
    worker = threading.Thread(target=_job_worker, args=(job,), daemon=True)
    job["thread"] = worker
    worker.start()
    return job_id


def _job_response(request: Request, job_id: str, job: dict | None, lang: str):
    """HTMX answer for a job: redirect when done, error box, or progress."""
    if job is None:
        return templates.TemplateResponse(
            request, "error_box.html", _ctx(lang, message=STRINGS[lang]["err_case_gone"])
        )
    if job["state"] == "done":
        return Response(status_code=200, headers={"HX-Redirect": job["url"]})
    if job["state"] == "error":
        return templates.TemplateResponse(
            request, "error_box.html", _ctx(lang, message=job["error"])
        )
    current = JOB_STAGES.index(job.get("stage", "reading"))
    return templates.TemplateResponse(
        request, "job_status.html",
        _ctx(lang, job_id=job_id, current=current,
             elapsed=int(time.time() - job["started"])),
    )


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    msinfo_file: UploadFile | None = File(None),
    battery_file: UploadFile | None = File(None),
    invite_code: str = Form(""),
    lang: str = Form("en"),
    local_dumps: str = Form(""),
    tz: str = Form("UTC"),
    dev_manufacturer: str = Form(""),
    dev_model: str = Form(""),
    dev_purchase: str = Form(""),
    local_wmi: str = Form(""),
    local_battery: str = Form(""),
):
    """Validate and read the files, then analyze them as a background job.

    HTMX requests get either the finished result (fast cases) or a progress
    fragment that polls /job/{id}: no single HTTP request has to stay open
    for the whole analysis (Modal cuts web requests after ~150 s).
    """
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
    msinfo_bytes = None
    if msinfo_file is not None and msinfo_file.filename:
        if not msinfo_file.filename.lower().endswith(".txt"):
            return _error(request, lang, t["err_msinfo_type"])
        msinfo_bytes = await msinfo_file.read(MAX_MSINFO_BYTES + 1)
        if len(msinfo_bytes) > MAX_MSINFO_BYTES:
            return _error(request, lang, t["err_msinfo_big"])
    battery_bytes = None
    if battery_file is not None and battery_file.filename:
        if not battery_file.filename.lower().endswith((".html", ".htm")):
            return _error(request, lang, t["err_battery_type"])
        battery_bytes = await battery_file.read(MAX_BATTERY_BYTES + 1)
        if len(battery_bytes) > MAX_BATTERY_BYTES:
            return _error(request, lang, t["err_battery_big"])
    job = {
        "lang": lang, "tz": tz, "client": _client_id(request),
        "content": content, "msinfo_bytes": msinfo_bytes,
        "battery_bytes": battery_bytes,
        "local_dumps": bool(local_dumps), "local_wmi": bool(local_wmi),
        "local_battery": bool(local_battery),
        "manual": {"manufacturer": dev_manufacturer, "model": dev_model,
                   "purchase": dev_purchase},
    }
    if not _is_htmx(request):
        # No JavaScript: run inline and answer when done.
        try:
            url = await run_in_threadpool(_run_pipeline, job)
        except _PipelineError as exc:
            return _error(request, lang, str(exc))
        return RedirectResponse(url, status_code=303)
    job_id = _start_job(job)
    await run_in_threadpool(job["thread"].join, JOB_INLINE_WAIT_SECONDS)
    return _job_response(request, job_id, job, lang)


@app.get("/job/{job_id}")
def job_status(request: Request, job_id: str):
    lang = get_lang(request.query_params.get("lang"))
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    return _job_response(request, job_id, job, lang)


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
        manufacturer=DEMO_DEVICE.get("manufacturer"),
    )
    # Precomputed explanations: the sample case never spends credits.
    CASES[case_id]["explanations"] = {
        code: data[code]["explanation"]
        for code in ("en", "es")
        if isinstance(data.get(code), dict) and data[code].get("explanation")
    }
    CASES[case_id]["fix_plans"] = {
        code: data[code]["fix_plan"]
        for code in ("en", "es")
        if isinstance(data.get(code), dict) and data[code].get("fix_plan")
    }
    url = f"/case/{case_id}?lang={lang}"
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.post("/case/{case_id}/explain")
async def explain(request: Request, case_id: str, lang: str = Form("en")):
    """On-demand plain-language explanation by Muse Spark (cached per case)."""
    lang = get_lang(lang)
    t = STRINGS[lang]
    stored = _get_case(case_id)
    if stored is None:
        if not _is_htmx(request):
            return _expired(request, lang)
        # Swap a small notice into the section, never a whole page.
        return templates.TemplateResponse(
            request, "explain_section.html",
            _ctx(lang, case_id=case_id, explanation=None, status_by_component={},
                 expired=True),
        )
    cache = stored.setdefault("explanations", {})
    error = None
    if lang not in cache:
        if not _take_upload_slot(_client_id(request)):
            error = t["err_rate_limit"]
        else:
            try:
                result = await run_in_threadpool(
                    explain_case, stored["findings"], stored["case"], lang
                )
                result["model"] = MODEL_NAMES.get(result.get("provider"), "Muse Spark")
                cache[lang] = result
            except (RouterError, ValueError) as exc:
                error = f"{t['err_explain']}: {exc}"
    if lang in cache:
        stored.setdefault("revealed", set()).add(lang)
    if not _is_htmx(request):
        return RedirectResponse(f"/case/{case_id}?lang={lang}", status_code=303)
    return templates.TemplateResponse(
        request, "explain_section.html",
        _ctx(lang, case_id=case_id, **_explain_ctx(stored, lang, explain_error=error)),
    )


@app.post("/case/{case_id}/fix")
async def fix(request: Request, case_id: str, lang: str = Form("en")):
    """On-demand self-help plan by Muse Spark, from the playbooks' safe fixes."""
    lang = get_lang(lang)
    t = STRINGS[lang]
    stored = _get_case(case_id)
    if stored is None:
        if not _is_htmx(request):
            return _expired(request, lang)
        return templates.TemplateResponse(
            request, "fix_section.html",
            _ctx(lang, case_id=case_id, fix=None, status_by_component={}, expired=True),
        )
    cache = stored.setdefault("fix_plans", {})
    error = None
    if lang not in cache:
        if not _take_upload_slot(_client_id(request)):
            error = t["err_rate_limit"]
        else:
            try:
                result = await run_in_threadpool(
                    fix_plan, stored["findings"], stored["case"], lang,
                    stored.get("manufacturer"),
                )
                result["model"] = MODEL_NAMES.get(result.get("provider"), "Muse Spark")
                cache[lang] = result
            except (RouterError, ValueError) as exc:
                error = f"{t['err_fix']}: {exc}"
    if lang in cache:
        stored.setdefault("fix_revealed", set()).add(lang)
    if not _is_htmx(request):
        return RedirectResponse(f"/case/{case_id}?lang={lang}#fix", status_code=303)
    return templates.TemplateResponse(
        request, "fix_section.html",
        _ctx(lang, case_id=case_id, **_explain_ctx(stored, lang, fix_error=error)),
    )


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
    stored["explanations"] = {}
    stored["fix_plans"] = {}
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


COMPONENT_ORDER = [
    "stability", "disk", "hardware", "thermal",
    "wifi", "usb", "battery", "software",
]


def _group_by_component(items: list) -> list:
    """Group rules items by playbook in canonical component order."""
    grouped: dict = {}
    for item in items:
        grouped.setdefault(item.get("playbook"), []).append(item)
    order = COMPONENT_ORDER + sorted(p for p in grouped if p not in COMPONENT_ORDER)
    return [(pid, grouped[pid]) for pid in order if pid in grouped]


STATUS_RANK = {"problem": 0, "attention": 1, "ok": 2, "no_data": 3}

# Official support entry points; matched by substring of the manufacturer.
SUPPORT_SITES = {
    "lenovo": ("Lenovo", "https://support.lenovo.com"),
    "hp": ("HP", "https://support.hp.com"),
    "hewlett": ("HP", "https://support.hp.com"),
    "dell": ("Dell", "https://www.dell.com/support"),
    "asus": ("ASUS", "https://www.asus.com/support/"),
    "acer": ("Acer", "https://www.acer.com/support"),
    "msi": ("MSI", "https://www.msi.com/support"),
    "micro-star": ("MSI", "https://www.msi.com/support"),
    "microsoft": ("Microsoft", "https://support.microsoft.com/surface"),
    "samsung": ("Samsung", "https://www.samsung.com/support/"),
    "apple": ("Apple", "https://support.apple.com"),
}


def _support_site(manufacturer: str | None) -> tuple[str | None, str | None]:
    """(display name, support URL) for a manufacturer string, if known."""
    text = (manufacturer or "").lower()
    for key, (name, url) in SUPPORT_SITES.items():
        if key == "hp":
            if re.search(r"\bhp\b", text):
                return name, url
        elif key in text:
            return name, url
    return (manufacturer or None), None


MODEL_NAMES = {"meta": "Muse Spark", "baseten": "Muse Spark Open",
               "fireworks": "Muse Spark Open"}


def _explain_ctx(stored: dict, lang: str, **extra) -> dict:
    components = _components(stored["findings"])
    # Shown only after the user clicks, even when it is already cached
    # (the sample case ships it precomputed).
    revealed = lang in stored.get("revealed", set())
    fix_shown = lang in stored.get("fix_revealed", set())
    return dict(
        explanation=(stored.get("explanations") or {}).get(lang) if revealed else None,
        fix=(stored.get("fix_plans") or {}).get(lang) if fix_shown else None,
        status_by_component={c["id"]: c["status"] for c in components},
        **extra,
    )


def _components(findings: dict) -> list:
    """Component statuses, rebuilt from older findings that lack them."""
    if findings.get("components"):
        return findings["components"]
    flagged = {p.get("playbook") for p in findings.get("patterns", [])}
    healthy = {h.get("playbook") for h in findings.get("healthy", [])}
    components = []
    for pid in COMPONENT_ORDER:
        if pid == "stability":
            count = len(findings.get("incidents", []))
            status = "problem" if count >= 2 else "attention" if count else "ok"
        elif pid == "battery" and pid not in flagged:
            count, status = 0, "no_data"
        elif pid in flagged:
            count, status = 0, "attention"
        elif pid in healthy:
            count, status = 0, "ok"
        else:
            continue
        components.append({"id": pid, "status": status, "count": count, "ignored": 0})
    return components


def _monthly_chart(incidents: list, lang: str) -> dict | None:
    """Incidents per calendar month, first to last month inclusive.

    Returns bar geometry for a server-rendered inline SVG (no JavaScript)
    plus the same numbers as text for screen readers.
    """
    months = sorted({i["date"][:7] for i in incidents if i.get("date")})
    if not months:
        return None
    year, month = map(int, months[0].split("-"))
    last = months[-1]
    keys = []
    while True:
        key = f"{year:04d}-{month:02d}"
        keys.append(key)
        if key >= last or len(keys) >= 36:
            break
        month += 1
        if month > 12:
            year, month = year + 1, 1
    counts = {key: 0 for key in keys}
    for incident in incidents:
        key = (incident.get("date") or "")[:7]
        if key in counts:
            counts[key] += 1
    names = STRINGS[lang]["month_names"].split(",")
    top = max(counts.values()) or 1
    bar_w, gap, height = 36, 14, 120
    bars = []
    for index, key in enumerate(keys):
        value = counts[key]
        h = round(height * value / top)
        bars.append({
            "x": index * (bar_w + gap) + gap, "y": height - h + 20,
            "w": bar_w, "h": h, "value": value,
            "label": names[int(key[5:7]) - 1] + (
                " " + key[2:4] if index == 0 or key[5:7] == "01" else ""
            ),
        })
    return {
        "bars": bars, "width": len(keys) * (bar_w + gap) + gap,
        "height": height + 50, "baseline": height + 20,
    }


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
    findings = stored["findings"]
    pattern_groups = _group_by_component(findings["patterns"])
    healthy_groups = _group_by_component(findings["healthy"])
    components = _components(findings)
    patterns_by_component = dict(pattern_groups)
    worst = sorted(components, key=lambda c: STATUS_RANK.get(c["status"], 9))
    return templates.TemplateResponse(
        request, "diagnosis.html",
        _ctx(lang, case_id=case_id, case=case,
             incidents=findings["incidents"],
             summary=findings.get("summary", {}),
             components=components,
             patterns_by_component=patterns_by_component,
             main_component=worst[0] if worst and worst[0]["status"] == "problem" else None,
             chart=_monthly_chart(findings["incidents"], lang),
             **_explain_ctx(stored, lang),
             pattern_groups=pattern_groups, healthy_groups=healthy_groups,
             metadata=stored["metadata"],
             local_dumps=stored.get("local_dumps"),
             is_demo=stored.get("is_demo", False),
             timezone=stored.get("timezone", "UTC"),
             labels=INCIDENT_LABELS),
    )


@app.get("/case/{case_id}/action", response_class=HTMLResponse)
def action(request: Request, case_id: str):
    lang = get_lang(request.query_params.get("lang"))
    stored = _get_case(case_id)
    if stored is None:
        return _expired(request, lang)
    support_name, support_url = _support_site(stored.get("manufacturer"))
    return templates.TemplateResponse(
        request, "action.html",
        _ctx(lang, case_id=case_id, case=stored["case"],
             support_name=support_name, support_url=support_url),
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
