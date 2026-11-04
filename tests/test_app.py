"""Web app tests with stubbed agent (no network, no models)."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultcase import app as app_module
from faultcase.adapters.windows import battery_report as battery_report_module
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


def _stub_build_case(evidence, ui_language="en", device=None, timezone=None):
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


def test_collect_posts_browser_timezone():
    response = client.get("/")
    assert 'name="tz"' in response.text
    assert "resolvedOptions" in response.text


def test_collect_has_msinfo_guide_and_manual_fields():
    response = client.get("/")
    assert "msinfo32" in response.text
    assert 'name="msinfo_file"' in response.text
    assert 'name="dev_manufacturer"' in response.text
    assert 'name="dev_model"' in response.text
    assert 'name="dev_purchase"' in response.text


def test_build_device_msinfo_wins_and_manual_fills_gaps():
    from faultcase.adapters.windows import msinfo

    parsed = msinfo.parse_msinfo(
        Path(__file__).resolve().parent.parent / "fixtures" / "msinfo" / "en.txt"
    )
    device = app_module._build_device(parsed, {
        "manufacturer": "BOGUS",
        "model": "",
        "purchase": "2026-01",
    })
    assert device["manufacturer"] == "LENOVO"
    assert device["model"] == "Legion Pro 7 16IAX10H"
    assert device["machine_type"] == "83F5"
    assert device["bios_version"] == "LENOVO N3FCN12W"
    assert device["gpu"] == "NVIDIA GeForce RTX 5090 Laptop GPU"
    assert device["purchase_date"] == "2026-01"
    assert device["sources"]["manufacturer"] == "windows_system_information"
    assert device["sources"]["purchase_date"] == "user_entered"
    assert "BOGUS" not in str(device)


def test_build_device_redacts_personal_data():
    device = app_module._build_device(None, {
        "manufacturer": "C:\\Users\\janedoe\\x",
        "model": "DESKTOP-X1",
        "purchase": "",
    })
    assert "janedoe" not in str(device)
    assert "DESKTOP-X1" not in str(device)
    assert device["sources"]["manufacturer"] == "user_entered"


def test_collect_wmi_option_hidden_without_support(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_WMI_AVAILABLE", False)
    response = client.get("/")
    assert "read its details automatically" not in response.text


def test_collect_wmi_option_shown_when_supported(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_WMI_AVAILABLE", True)
    response = client.get("/")
    assert "read its details automatically" in response.text


def test_upload_with_local_wmi_sends_device_to_agent(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    seen = {}

    def spy(evidence, ui_language="en", device=None, timezone=None):
        seen["device"] = device
        return _stub_build_case(evidence, ui_language, device, timezone)

    monkeypatch.setattr(app_module, "build_case", spy)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    monkeypatch.setattr(app_module, "LOCAL_WMI_AVAILABLE", True)
    monkeypatch.setattr(
        app_module.wmi,
        "read_device_info",
        lambda: {
            "manufacturer": "LENOVO", "model": "Legion Pro 7",
            "machine_type": "83F5", "system_sku": None,
            "bios_version": "N3FCN12W", "bios_date": "2026-04-01",
            "os_name": None, "os_version": None, "gpus": [],
            "serial": "WMI-SERIAL-1",
        },
    )
    response = client.post(
        "/upload",
        files={"file": ("failures.evtx", evtx_path.read_bytes())},
        data={"lang": "en", "local_wmi": "yes"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert seen["device"]["serial"] == "WMI-SERIAL-1"
    assert seen["device"]["sources"]["serial"] == "local_wmi"
    assert seen["device"]["sources"]["manufacturer"] == "local_wmi"


def test_upload_with_msinfo_sends_device_to_agent(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    msinfo_path = (
        Path(__file__).resolve().parent.parent / "fixtures" / "msinfo" / "en.txt"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    seen = {}

    def spy(evidence, ui_language="en", device=None, timezone=None):
        seen["device"] = device
        return _stub_build_case(evidence, ui_language, device, timezone)

    monkeypatch.setattr(app_module, "build_case", spy)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post(
        "/upload",
        files={
            "file": ("failures.evtx", evtx_path.read_bytes()),
            "msinfo_file": ("sysinfo.txt", msinfo_path.read_bytes()),
        },
        data={"lang": "en", "dev_purchase": "2026-01"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"].startswith("/case/")
    assert seen["device"]["machine_type"] == "83F5"
    assert seen["device"]["purchase_date"] == "2026-01"
    assert "FAKE123" not in str(seen["device"])
    assert "fakeuser" not in str(seen["device"])


def test_upload_with_battery_report_sends_numbers(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    battery_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "synthetic" / "battery_report.html"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    seen = {}

    def spy(evidence, ui_language="en", device=None, timezone=None):
        seen["battery"] = evidence.get("battery")
        return _stub_build_case(evidence, ui_language, device, timezone)

    monkeypatch.setattr(app_module, "build_case", spy)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post(
        "/upload",
        files={
            "file": ("failures.evtx", evtx_path.read_bytes()),
            "battery_file": ("battery-report.html", battery_path.read_bytes()),
        },
        data={"lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"].startswith("/case/")
    assert seen["battery"]["wear_percent"] == 35.0
    assert seen["battery"]["cycle_count"] == 231
    assert "FAKELAPTOP-123" not in str(seen["battery"])
    assert "SN-0000-SECRET" not in str(seen["battery"])


def test_upload_rejects_non_html_battery(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    response = client.post(
        "/upload",
        files={
            "file": ("failures.evtx", evtx_path.read_bytes()),
            "battery_file": ("battery-report.txt", b"not html"),
        },
        data={"lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert "must be an .html" in response.text


def test_upload_with_local_battery_generates_report(monkeypatch):
    evtx_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "failures.evtx"
    )
    if not evtx_path.exists():
        pytest.skip("failures.evtx not present")
    seen = {}

    def spy(evidence, ui_language="en", device=None, timezone=None):
        seen["battery"] = evidence.get("battery")
        return _stub_build_case(evidence, ui_language, device, timezone)

    monkeypatch.setattr(app_module, "build_case", spy)
    monkeypatch.setattr(app_module, "settings", OPEN_SETTINGS)
    monkeypatch.setattr(app_module, "LOCAL_BATTERY_AVAILABLE", True)
    monkeypatch.setattr(
        battery_report_module, "generate_local_report",
        lambda: {"wear_percent": 12.5, "capacity_history": []},
    )
    response = client.post(
        "/upload",
        files={"file": ("failures.evtx", evtx_path.read_bytes())},
        data={"lang": "en", "local_battery": "yes"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert seen["battery"]["wear_percent"] == 12.5


def test_filter_download():
    response = client.get("/filter/device-diagnostics.xml")
    assert response.status_code == 200
    assert "FaultCase - Device diagnostics" in response.text


def _demo_file():
    path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "real_case" / "demo_case.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_flow_uses_precomputed_file(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("demo must not call models")

    monkeypatch.setattr(app_module, "build_case", explode)
    response = client.post("/demo", data={"lang": "en"}, headers={"HX-Request": "true"})
    assert response.status_code == 200
    target = response.headers["HX-Redirect"]
    assert target.startswith("/case/")
    base = target.split("?")[0]
    file_case = _demo_file()["en"]["case"]

    diagnosis = client.get(target)
    assert diagnosis.status_code == 200
    assert EN["v_" + file_case["verdict"]] in diagnosis.text
    assert "Regenerate live" in diagnosis.text
    assert "/action?lang=en" in diagnosis.text

    action = client.get(base + "/action?lang=en")
    assert action.status_code == 200
    assert file_case["manufacturer_report"]["body_en"][:60] in action.text

    archive = client.get(base + "/evidence.zip")
    assert archive.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert "findings.json" in names
    assert "report_en.txt" in names and "report_es.txt" in names
    assert any(n.startswith("windbg/") for n in names)
    assert not any(n.endswith(".evtx") or n.endswith(".dmp") for n in names)


def test_group_by_component_orders_and_keeps_unknowns():
    items = [
        {"playbook": "wifi", "detail": "w"},
        {"playbook": "stability", "detail": "s"},
        {"playbook": "future", "detail": "f"},
    ]
    groups = app_module._group_by_component(items)
    assert [pid for pid, _ in groups] == ["stability", "wifi", "future"]
    assert groups[0][1] == [{"playbook": "stability", "detail": "s"}]


def test_diagnosis_groups_findings_by_component():
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    diagnosis = client.get(target)
    assert "<h4>Stability</h4>" in diagnosis.text
    assert "4 dumps with nvlddmkm.sys" in diagnosis.text
    assert "<h4>Storage</h4>" in diagnosis.text
    assert "No disk errors were logged." in diagnosis.text


def test_timeline_plain_language_labels():
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    diagnosis = client.get(target)
    assert "Blue screen: display driver" in diagnosis.text
    assert "Blue screen: driver timeout" in diagnosis.text
    assert "Freeze without blue screen" in diagnosis.text


def test_timeline_labels_spanish():
    target = client.post(
        "/demo", data={"lang": "es"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    page = client.get(target)
    assert "Pantallazo azul: controlador de vídeo" in page.text
    assert "Congelamiento sin pantallazo azul" in page.text


def test_demo_missing_file_shows_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module, "DEMO_CASE_PATH", tmp_path / "no-such-file.json"
    )
    response = client.post("/demo", data={"lang": "en"}, headers={"HX-Request": "true"})
    assert "Run scripts/build_demo_case.py" in response.text


def test_regenerate_live_with_valid_invite(monkeypatch):
    locked = Settings(
        meta_api_key=None, baseten_api_key=None, fireworks_api_key=None,
        baseten_model="m", invite_code="secret",
    )
    monkeypatch.setattr(app_module, "settings", locked)
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    base = target.split("?")[0]
    monkeypatch.setattr(app_module, "build_case", _stub_build_case)
    response = client.post(
        base + "/regenerate",
        data={"invite_code": "secret", "lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == target
    diagnosis = client.get(target)
    assert "Likely driver fault" in diagnosis.text


def test_regenerate_rejects_wrong_invite(monkeypatch):
    locked = Settings(
        meta_api_key=None, baseten_api_key=None, fireworks_api_key=None,
        baseten_model="m", invite_code="secret",
    )
    monkeypatch.setattr(app_module, "settings", locked)
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    response = client.post(
        target.split("?")[0] + "/regenerate",
        data={"invite_code": "wrong", "lang": "en"},
        headers={"HX-Request": "true"},
    )
    assert "Wrong invite code" in response.text


def test_regenerate_non_demo_case_returns_404():
    app_module.CASES["notademo"] = {"is_demo": False}
    try:
        response = client.post(
            "/case/notademo/regenerate",
            data={"invite_code": "x", "lang": "en"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 404
    finally:
        del app_module.CASES["notademo"]


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


def test_serial_field_is_browser_only():
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    page = client.get(target.split("?")[0] + "/action?lang=en")
    assert 'id="serial"' in page.text
    assert "Download .txt" in page.text
    assert "<form" not in page.text
    source = (
        Path(__file__).resolve().parent.parent / "templates" / "action.html"
    ).read_text(encoding="utf-8")
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
    assert "{{SERIAL}}" in source


def test_serial_canary_never_reaches_server():
    canary = "CANARY-SN-987654"
    target = client.post(
        "/demo",
        data={"lang": "en", "serial": canary},
        headers={"HX-Request": "true"},
    ).headers["HX-Redirect"]
    base = target.split("?")[0]
    assert canary not in client.get(target).text
    assert canary not in client.get(base + "/action?lang=en").text


def test_expired_case_shows_friendly_page():
    diagnosis = client.get("/case/doesnotexist")
    assert diagnosis.status_code == 200
    assert "has expired" in diagnosis.text
    action = client.get("/case/doesnotexist/action")
    assert action.status_code == 200
    assert "has expired" in action.text
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


def test_diagnosis_is_visual_and_bilingual():
    for lang, title, status in (
        ("en", "Unexpected restarts per month", "Problem"),
        ("es", "Reinicios inesperados por mes", "Problema"),
    ):
        target = client.post(
            "/demo", data={"lang": lang}, headers={"HX-Request": "true"}
        ).headers["HX-Redirect"]
        page = client.get(target).text
        assert title in page
        assert "<svg" in page and 'class="chart-bar"' in page
        assert 'class="health-card status-problem"' in page
        assert status in page
        assert "<details" in page
        assert "None None" not in page
        # The primary action is inside the top verdict card.
        top = page.split('class="verdict-card', 1)[1].split("</section>", 1)[0]
        assert "/action?lang=" + lang in top


def test_monthly_chart_fills_empty_months():
    chart = app_module._monthly_chart(
        [{"date": "2026-01-05"}, {"date": "2026-01-20"}, {"date": "2026-04-02"}], "en"
    )
    assert [b["value"] for b in chart["bars"]] == [2, 0, 0, 1]
    assert chart["bars"][0]["label"] == "Jan 26"
    assert app_module._monthly_chart([], "en") is None


def test_components_fallback_for_old_findings():
    old = {"incidents": [{}, {}], "patterns": [], "healthy": [{"playbook": "disk"}]}
    status = {c["id"]: c["status"] for c in app_module._components(old)}
    assert status["stability"] == "problem"
    assert status["disk"] == "ok"
    assert status["battery"] == "no_data"


def test_collect_marks_required_and_localizes_file_buttons():
    page = client.get("/?lang=en").text
    assert "Required" in page and "Optional" in page
    assert "Choose file" in page
    es = client.get("/?lang=es").text
    assert "Obligatorio" in es and "Elegir archivo" in es


def test_action_explains_next_steps_with_manufacturer_link():
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    case_id = target.split("/case/")[1].split("?")[0]
    page = client.get(f"/case/{case_id}/action?lang=en").text
    assert "What to do next" in page
    assert 'href="https://support.lenovo.com"' in page
    assert "public forums" in page


def test_support_site_matching():
    assert app_module._support_site("LENOVO")[1] == "https://support.lenovo.com"
    assert app_module._support_site("HP Inc.")[1] == "https://support.hp.com"
    assert app_module._support_site("Shipping Co")[1] is None
    assert app_module._support_site(None) == (None, None)


def test_ai_component_notes_are_shown_in_order():
    target = client.post(
        "/demo", data={"lang": "en"}, headers={"HX-Request": "true"}
    ).headers["HX-Redirect"]
    case_id = target.split("/case/")[1].split("?")[0]
    stored = app_module.CASES[case_id]
    stored["case"] = dict(stored["case"], component_notes=[
        {"component": "wifi", "text": "Wi-Fi note."},
        {"component": "stability", "text": "Stability note."},
    ])
    page = client.get(target).text
    assert "What this means for you" in page
    assert page.index("Stability note.") < page.index("Wi-Fi note.")
