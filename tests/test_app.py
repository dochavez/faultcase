"""Web app tests with stubbed agent (no network, no models)."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultcase import app as app_module
from faultcase.app import app
from faultcase.i18n import EN, ES
from faultcase.settings import Settings

client = TestClient(app)

CASE = {
    "verdict": "likely_driver_fault",
    "confidence": "medium",
    "user_summary": "The display driver keeps failing.",
    "findings": [
        {"text": "nvlddmkm.sys failed twice.", "type": "fact"},
        {"text": "Power transitions may matter.", "type": "hypothesis"},
    ],
    "healthy_components": ["disk"],
    "checklist": [{"step": "Install the manufacturer driver.", "status": "pending"}],
    "manufacturer_report": {
        "subject": "Warranty case",
        "body_en": "English report body.",
        "body_es": "Cuerpo del informe.",
    },
}

OPEN_SETTINGS = Settings(
    meta_api_key=None, baseten_api_key=None, fireworks_api_key=None,
    baseten_model="m", invite_code=None,
)


def _stub_build_case(evidence, ui_language="en", device=None):
    return {
        "case": CASE,
        "metadata": {
            "providers_used": ["stub"],
            "total_latency_ms": 1500,
            "total_tokens": 10,
            "prompt_tokens": 6,
            "completion_tokens": 4,
        },
    }


def test_collect_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Built with Muse Spark Open" in response.text
    assert "Try a sample case" in response.text
    assert "device-diagnostics.xml" in response.text


def test_collect_page_spanish():
    response = client.get("/?lang=es")
    assert response.status_code == 200
    assert "Probar con un caso de ejemplo" in response.text


def test_i18n_key_parity():
    assert set(EN) == set(ES)


def test_filter_download():
    response = client.get("/filter/device-diagnostics.xml")
    assert response.status_code == 200
    assert "FaultCase - Device diagnostics" in response.text


def test_demo_flow_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "build_case", _stub_build_case)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post("/demo", data={"lang": "en"}, headers={"HX-Request": "true"})
    assert response.status_code == 200
    target = response.headers["HX-Redirect"]
    assert target.startswith("/case/")
    base = target.split("?")[0]

    diagnosis = client.get(target)
    assert diagnosis.status_code == 200
    assert "Likely driver fault" in diagnosis.text
    assert "Fact" in diagnosis.text and "Hypothesis" in diagnosis.text
    assert "/action?lang=en" in diagnosis.text

    action = client.get(base + "/action?lang=en")
    assert action.status_code == 200
    assert "English report body." in action.text
    assert "Cuerpo del informe." in action.text

    archive = client.get(base + "/evidence.zip")
    assert archive.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert "findings.json" in names
    assert "report_en.txt" in names and "report_es.txt" in names
    assert any(n.startswith("windbg/") for n in names)
    assert not any(n.endswith(".evtx") or n.endswith(".dmp") for n in names)


def test_upload_rejects_wrong_invite_code(monkeypatch):
    locked = Settings(
        meta_api_key=None, baseten_api_key=None, fireworks_api_key=None,
        baseten_model="m", invite_code="secret",
    )
    monkeypatch.setattr(app_module, "settings", locked)
    response = client.post(
        "/upload",
        files={"file": ("x.evtx", b"xxx")},
        data={"invite_code": "wrong", "lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Wrong invite code" in response.text


def test_upload_rejects_non_evtx(monkeypatch):
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post(
        "/upload",
        files={"file": ("x.txt", b"xxx")},
        data={"lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert "an .evtx file" in response.text


def test_upload_accepts_real_evtx(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    monkeypatch.setattr(app_module, "build_case", _stub_build_case)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post(
        "/upload",
        files={"file": ("failures.evtx", evtx_path.read_bytes())},
        data={"lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"].startswith("/case/")
    diagnosis = client.get(response.headers["HX-Redirect"])
    assert diagnosis.status_code == 200


def test_unknown_case_returns_404():
    assert client.get("/case/doesnotexist").status_code == 404
    assert client.get("/case/doesnotexist/evidence.zip").status_code == 404


def test_collect_hides_dumps_option_when_cdb_missing(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_DUMPS_AVAILABLE", False)
    response = client.get("/")
    assert response.status_code == 200
    assert "Also analyze my memory dumps" not in response.text


def test_collect_shows_dumps_option_when_available(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_DUMPS_AVAILABLE", True)
    response = client.get("/")
    assert response.status_code == 200
    assert "Also analyze my memory dumps" in response.text
    assert "administrator" in response.text


def test_upload_with_local_dumps(monkeypatch):
    from faultcase.adapters.windows.windbg import parse_windbg

    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "windbg" / "071726-15718-01.txt"
    )
    monkeypatch.setattr(app_module, "build_case", _stub_build_case)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    monkeypatch.setattr(app_module, "LOCAL_DUMPS_AVAILABLE", True)
    monkeypatch.setattr(
        app_module.cdb,
        "collect_minidumps",
        lambda: [{
            "file": "071726-15718-01.dmp",
            "dump": parse_windbg(fixture),
            "summary": "raw cdb text",
            "error": None,
        }],
    )
    response = client.post(
        "/upload",
        files={"file": ("failures.evtx", evtx_path.read_bytes())},
        data={"lang": "en", "local_dumps": "yes"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    base = response.headers["HX-Redirect"].split("?")[0]
    diagnosis = client.get(response.headers["HX-Redirect"])
    assert "nvlddmkm.sys" in diagnosis.text
    assert "Local memory dumps: 1 analyzed, 0 failed" in diagnosis.text
    archive = client.get(base + "/evidence.zip")
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert "windbg/071726-15718-01.dmp.txt" in names
