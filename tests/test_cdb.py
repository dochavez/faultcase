"""Local cdb analysis: discovery, stubbed runs and read-only copies."""

import os
import shutil
import subprocess
from pathlib import Path

from faultcase.adapters.windows import cdb
from faultcase.adapters.windows.windbg import parse_windbg

REAL_CASE = Path(__file__).resolve().parent.parent / "fixtures" / "real_case"
SAMPLE_OUTPUT = (
    (REAL_CASE / "windbg" / "071726-15718-01.txt").read_text(encoding="utf-8")
    + "\nSTACK_TEXT: CANARY_BLOB_SHOULD_NOT_LEAK\n"
)
DUMP_FIELDS = {
    "bugcheck_code", "params", "image_name", "symbol_name",
    "failure_bucket_id", "failure_id_hash", "process_name", "driver_timestamp",
}


def _completed(stdout=SAMPLE_OUTPUT):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_find_cdb_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\tools\\cdb.exe")
    assert cdb.find_cdb() == Path("C:\\tools\\cdb.exe")


def test_find_cdb_in_kit_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    exe = tmp_path / "cdb.exe"
    exe.write_bytes(b"fake")
    monkeypatch.setattr(cdb, "_candidate_paths", lambda: [exe])
    assert cdb.find_cdb() == exe


def test_find_cdb_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(cdb, "_candidate_paths", lambda: [tmp_path / "cdb.exe"])
    assert cdb.find_cdb() is None


def test_find_cdb_only_on_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert cdb.find_cdb() is None


def test_run_cdb_command_line(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["timeout"] = kwargs["timeout"]
        assert kwargs["capture_output"] is True
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    dump = tmp_path / "x.dmp"
    dump.write_bytes(b"fake")
    out = cdb.run_cdb(dump, cdb_path=tmp_path / "cdb.exe", symbols_dir=tmp_path / "sym")
    assert out == SAMPLE_OUTPUT
    assert seen["argv"] == [
        str(tmp_path / "cdb.exe"), "-z", str(dump),
        "-y", f"srv*{tmp_path / 'sym'}*{cdb.SYMBOLS_SERVER}",
        "-c", "!analyze -v; lmvm nvlddmkm; q",
    ]
    assert seen["timeout"] == 300
    assert (tmp_path / "sym").is_dir()


def test_run_cdb_without_cdb_raises(monkeypatch):
    monkeypatch.setattr(cdb, "find_cdb", lambda: None)
    try:
        cdb.run_cdb("x.dmp")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def test_analyze_dump_returns_only_parsed_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed())
    result = cdb.analyze_dump_file(tmp_path / "x.dmp", cdb_path=tmp_path / "cdb.exe")
    assert result["image_name"] == "nvlddmkm.sys"
    assert result["driver_timestamp"] == "2026-03-04"
    assert set(result) == DUMP_FIELDS
    assert "CANARY_BLOB_SHOULD_NOT_LEAK" not in str(result)


def test_collect_copies_without_modifying_original(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed())
    source = tmp_path / "src"
    source.mkdir()
    original = source / "a.dmp"
    original.write_bytes(b"fake-dump-bytes")
    before = (original.stat().st_mtime_ns, original.read_bytes())
    records = cdb.collect_minidumps(
        source_dir=source, cdb_path=tmp_path / "cdb.exe"
    )
    assert len(records) == 1
    assert records[0]["file"] == "a.dmp"
    assert records[0]["dump"]["image_name"] == "nvlddmkm.sys"
    assert records[0]["summary"] == SAMPLE_OUTPUT
    assert records[0]["error"] is None
    assert (original.stat().st_mtime_ns, original.read_bytes()) == before


def test_collect_handles_timeout_per_dump(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.dmp").write_bytes(b"fake")
    records = cdb.collect_minidumps(
        source_dir=source, cdb_path=tmp_path / "cdb.exe"
    )
    assert records[0]["dump"] is None
    assert "timed out" in records[0]["error"]


def test_collect_without_dumps_returns_empty_list(tmp_path):
    records = cdb.collect_minidumps(
        source_dir=tmp_path / "empty", cdb_path=tmp_path / "cdb.exe"
    )
    assert records == []


def test_collect_without_cdb_returns_fatal_record(monkeypatch, tmp_path):
    monkeypatch.setattr(cdb, "find_cdb", lambda: None)
    records = cdb.collect_minidumps(source_dir=tmp_path)
    assert len(records) == 1
    assert records[0]["file"] is None
    assert "cdb.exe" in records[0]["error"]


def test_sample_output_matches_fixture_parser():
    assert cdb.parse_windbg_text(SAMPLE_OUTPUT) == parse_windbg(
        REAL_CASE / "windbg" / "071726-15718-01.txt"
    )
