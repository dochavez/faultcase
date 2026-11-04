"""One-click fixes for LOCAL Windows mode only (FaultCase running on the PC).

A short allowlist of safe, reversible settings. The commands are fixed in
this file: Muse only chooses WHICH action fits a step, it never writes or
runs a command. Every apply first saves the previous value to a backup
file, so each action can be undone. Nothing here runs on the web version
(Modal/Render run Linux, where ``is_available()`` is False).

Actions:
- sleep_off: set sleep after "never" (AC and battery) to test whether
  crashes come from sleep/wake. Undo restores the previous timeouts.
- small_dumps: make Windows keep a small memory dump on each crash
  (CrashDumpEnabled = 3). Needs administrator rights.
- wifi_power_saving_off: stop Windows turning the Wi-Fi adapter off to
  save power. Needs administrator rights.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ACTIONS = ("sleep_off", "small_dumps", "wifi_power_saving_off")
TIMEOUT_SECONDS = 30
CRASH_KEY = r"HKLM\SYSTEM\CurrentControlSet\Control\CrashControl"
WIFI_ADAPTER = (
    "$a = Get-NetAdapter -Physical | Where-Object { $_.PhysicalMediaType -match '802.11' }"
    " | Select-Object -First 1; if (-not $a) { throw 'no Wi-Fi adapter' }; "
)


class FixError(Exception):
    """A fix could not be applied or undone (message is user-facing code)."""


def is_available() -> bool:
    return os.name == "nt"


def backup_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "FaultCase" / "fix-backup.json"


def _load() -> dict:
    try:
        return json.loads(backup_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = backup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _run(args: list[str]) -> str:
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FixError("failed") from exc
    if done.returncode != 0:
        text = (done.stderr or done.stdout or "").lower()
        if "access" in text and "denied" in text or "acceso denegado" in text \
                or "administrator" in text or "administrador" in text:
            raise FixError("needs_admin")
        raise FixError("failed")
    return done.stdout or ""


def _ps(script: str) -> str:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


# --- sleep_off -------------------------------------------------------------

def _sleep_timeouts() -> tuple[int, int]:
    out = _run(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"])
    values = re.findall(r"0x([0-9a-fA-F]{8})\b", out)
    if len(values) < 2:
        raise FixError("failed")
    # The last two hex values are the current AC and DC settings (seconds).
    return int(values[-2], 16), int(values[-1], 16)


def _set_sleep(ac_minutes: int, dc_minutes: int) -> None:
    _run(["powercfg", "/change", "standby-timeout-ac", str(ac_minutes)])
    _run(["powercfg", "/change", "standby-timeout-dc", str(dc_minutes)])


# --- small_dumps -----------------------------------------------------------

def _crash_dump_value() -> int:
    out = _run(["reg", "query", CRASH_KEY, "/v", "CrashDumpEnabled"])
    match = re.search(r"CrashDumpEnabled\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    if not match:
        raise FixError("failed")
    return int(match.group(1), 16)


def _set_crash_dump(value: int) -> None:
    _run(["reg", "add", CRASH_KEY, "/v", "CrashDumpEnabled", "/t", "REG_DWORD",
          "/d", str(int(value)), "/f"])


# --- wifi_power_saving_off -------------------------------------------------

def _wifi_state() -> str:
    out = _ps(WIFI_ADAPTER + "(Get-NetAdapterPowerManagement -Name $a.Name).AllowComputerToTurnOffDevice")
    state = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if state not in ("Enabled", "Disabled", "Unsupported"):
        raise FixError("failed")
    return state


def _set_wifi(state: str) -> None:
    if state not in ("Enabled", "Disabled"):
        raise FixError("failed")
    _ps(WIFI_ADAPTER + f"Set-NetAdapterPowerManagement -Name $a.Name -AllowComputerToTurnOffDevice {state}")


# --- public API ------------------------------------------------------------

def status() -> dict:
    """Which actions have a saved backup (i.e. were applied and can be undone)."""
    data = _load()
    return {action: action in data for action in ACTIONS}


def apply(action: str) -> None:
    if action not in ACTIONS:
        raise FixError("unknown")
    if not is_available():
        raise FixError("not_local")
    data = _load()
    if action == "sleep_off":
        previous = data.get(action) or dict(zip(("ac", "dc"), _sleep_timeouts()))
        _set_sleep(0, 0)
    elif action == "small_dumps":
        previous = data.get(action) or {"value": _crash_dump_value()}
        _set_crash_dump(3)
    else:
        previous = data.get(action) or {"state": _wifi_state()}
        if previous.get("state") == "Unsupported":
            raise FixError("unsupported")
        _set_wifi("Disabled")
    data[action] = previous
    _save(data)


def undo(action: str) -> None:
    if action not in ACTIONS:
        raise FixError("unknown")
    if not is_available():
        raise FixError("not_local")
    data = _load()
    previous = data.get(action)
    if previous is None:
        raise FixError("nothing_to_undo")
    if action == "sleep_off":
        _set_sleep(int(previous["ac"]) // 60, int(previous["dc"]) // 60)
    elif action == "small_dumps":
        _set_crash_dump(int(previous["value"]))
    else:
        _set_wifi(previous["state"])
    data.pop(action, None)
    _save(data)
