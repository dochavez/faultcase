"""Local CIM device reading with stubbed PowerShell (no system calls)."""

import json
import shutil
import subprocess

import pytest

from faultcase.adapters.windows import wmi

CIM_JSON = json.dumps({
    "manufacturer": "LENOVO",
    "model": "Legion Pro 7 16IAX10H",
    "machine_type": "83F5",
    "bios_manufacturer": "LENOVO",
    "bios_smbios": ["N3FCN12W"],
    "bios_date": "2026-04-01",
    "serial": "FAKESERIAL123",
    "gpus": [
        {
            "name": "NVIDIA GeForce RTX 5090 Laptop GPU",
            "driver_version": "32.0.15.6636",
            "driver_date": "2026-02-14",
        }
    ],
})


def _completed(stdout=CIM_JSON, returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def test_read_device_info(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["timeout"] = kwargs["timeout"]
        assert "Get-CimInstance" in argv[-1]
        assert "Set-" not in argv[-1] and "Remove-" not in argv[-1]
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\powershell.exe")
    result = wmi.read_device_info()
    assert seen["argv"][0] == "C:\\powershell.exe"
    assert seen["timeout"] == 20
    assert result["manufacturer"] == "LENOVO"
    assert result["model"] == "Legion Pro 7 16IAX10H"
    assert result["machine_type"] == "83F5"
    assert result["bios_version"] == "LENOVO N3FCN12W"
    assert result["bios_date"] == "2026-04-01"
    assert result["serial"] == "FAKESERIAL123"
    assert result["gpus"][0]["driver_version"] == "32.0.15.6636"
    assert "User Name" not in seen["argv"][-1]
    assert "CSName" not in seen["argv"][-1]


def test_long_machine_type_is_rejected(monkeypatch):
    payload = json.loads(CIM_JSON)
    payload["machine_type"] = "HP EliteBook 840"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(payload))
    )
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\powershell.exe")
    assert wmi.read_device_info()["machine_type"] is None


def test_bad_dates_become_null(monkeypatch):
    payload = json.loads(CIM_JSON)
    payload["bios_date"] = "not a date"
    payload["gpus"][0]["driver_date"] = "2026/02/14"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(payload))
    )
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\powershell.exe")
    result = wmi.read_device_info()
    assert result["bios_date"] is None
    assert result["gpus"][0]["driver_date"] is None


def test_timeout_propagates(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\powershell.exe")
    with pytest.raises(subprocess.TimeoutExpired):
        wmi.read_device_info()


def test_failing_query_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed("", returncode=1)
    )
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\powershell.exe")
    with pytest.raises(RuntimeError, match="CIM query failed"):
        wmi.read_device_info()


def test_unavailable_without_powershell(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert wmi.is_available() is False
