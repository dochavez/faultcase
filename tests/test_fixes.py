"""Local one-click fixes: allowlist, backup and undo, request guards."""

import pytest
from fastapi.testclient import TestClient

from faultcase import app as app_module
from faultcase.adapters.windows import fixes


@pytest.fixture
def fake_windows(monkeypatch, tmp_path):
    """Pretend to be Windows; record commands instead of running them."""
    state = {"ac": 900, "dc": 600, "dump": 7, "wifi": "Enabled", "calls": []}
    monkeypatch.setattr(fixes, "is_available", lambda: True)
    monkeypatch.setattr(fixes, "backup_path", lambda: tmp_path / "fix-backup.json")

    def run(args):
        state["calls"].append(args)
        if args[:2] == ["powercfg", "/query"]:
            return ("Minimum 0x00000000\nMaximum 0xffffffff\n"
                    f"Current AC Power Setting Index: 0x{state['ac']:08x}\n"
                    f"Current DC Power Setting Index: 0x{state['dc']:08x}\n")
        if args[:2] == ["powercfg", "/change"]:
            key = "ac" if args[2].endswith("-ac") else "dc"
            state[key] = int(args[3]) * 60
            return ""
        if args[:2] == ["reg", "query"]:
            return f"    CrashDumpEnabled    REG_DWORD    0x{state['dump']:x}\n"
        if args[:2] == ["reg", "add"]:
            state["dump"] = int(args[args.index("/d") + 1])
            return ""
        if args[0] == "powershell":
            script = args[-1]
            if "Set-NetAdapterPowerManagement" in script:
                state["wifi"] = script.rsplit(" ", 1)[-1]
                return ""
            return state["wifi"] + "\n"
        raise AssertionError(args)

    monkeypatch.setattr(fixes, "_run", run)
    return state


def test_sleep_off_apply_and_undo_restores_previous(fake_windows):
    fixes.apply("sleep_off")
    assert (fake_windows["ac"], fake_windows["dc"]) == (0, 0)
    assert fixes.status()["sleep_off"] is True
    fixes.undo("sleep_off")
    assert (fake_windows["ac"], fake_windows["dc"]) == (900, 600)
    assert fixes.status()["sleep_off"] is False


def test_small_dumps_and_wifi_round_trip(fake_windows):
    fixes.apply("small_dumps")
    fixes.apply("wifi_power_saving_off")
    assert fake_windows["dump"] == 3 and fake_windows["wifi"] == "Disabled"
    fixes.undo("small_dumps")
    fixes.undo("wifi_power_saving_off")
    assert fake_windows["dump"] == 7 and fake_windows["wifi"] == "Enabled"


def test_applying_twice_keeps_the_original_backup(fake_windows):
    fixes.apply("sleep_off")
    fixes.apply("sleep_off")
    fixes.undo("sleep_off")
    assert fake_windows["ac"] == 900


def test_only_allowlisted_actions(fake_windows):
    with pytest.raises(fixes.FixError):
        fixes.apply("format_disk")
    with pytest.raises(fixes.FixError):
        fixes.undo("sleep_off")  # nothing applied yet


def test_not_available_off_windows(monkeypatch):
    monkeypatch.setattr(fixes, "is_available", lambda: False)
    with pytest.raises(fixes.FixError):
        fixes.apply("sleep_off")


class _Client:
    host = "127.0.0.1"


def _local_client(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_FIXES_AVAILABLE", True)
    monkeypatch.setattr(app_module, "_is_local_request",
                        lambda request: request.headers.get("origin") in (None, "http://127.0.0.1:8765"))
    return TestClient(app_module.app)


def test_endpoint_requires_token_and_local_origin(monkeypatch, fake_windows):
    client = _local_client(monkeypatch)
    url = "/local/fix/sleep_off"
    assert client.post(url, data={"op": "apply", "token": "wrong"}).status_code == 403
    assert client.post(url, data={"op": "apply", "token": app_module.FIX_TOKEN},
                       headers={"origin": "https://evil.example"}).status_code == 403
    ok = client.post(url, data={"op": "apply", "token": app_module.FIX_TOKEN, "lang": "en"})
    assert ok.status_code == 200 and "Undo" in ok.text
    assert fake_windows["ac"] == 0
    undone = client.post(url, data={"op": "undo", "token": app_module.FIX_TOKEN, "lang": "es"})
    assert "Aplicar en este equipo" in undone.text and fake_windows["ac"] == 900


def test_endpoint_is_off_on_the_web(monkeypatch):
    monkeypatch.setattr(app_module, "LOCAL_FIXES_AVAILABLE", False)
    client = TestClient(app_module.app)
    assert client.post("/local/fix/sleep_off", data={"token": "x"}).status_code == 404


def test_local_origin_check():
    class R:
        def __init__(self, host, origin=None):
            self.client = type("C", (), {"host": host})()
            self.headers = {"origin": origin} if origin else {}
    assert app_module._is_local_request(R("127.0.0.1"))
    assert app_module._is_local_request(R("127.0.0.1", "http://localhost:8765"))
    assert not app_module._is_local_request(R("127.0.0.1", "https://evil.example"))
    assert not app_module._is_local_request(R("203.0.113.5"))
