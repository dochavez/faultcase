"""msinfo32 export parser: English and Spanish, encodings, privacy."""

from pathlib import Path

from faultcase.adapters.windows import msinfo

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "msinfo"


def test_english_export():
    result = msinfo.parse_msinfo(FIXTURES / "en.txt")
    assert result["manufacturer"] == "LENOVO"
    assert result["model"] == "Legion Pro 7 16IAX10H"
    assert result["system_sku"] == "LENOVO_MT_83F5_BU_Think_FM_Legion Pro 7 16IAX10H"
    assert result["machine_type"] == "83F5"
    assert result["bios_version"] == "LENOVO N3FCN12W"
    assert result["bios_date"] == "4/1/2026"
    assert result["os_name"] == "Microsoft Windows 11 Pro"
    assert result["os_version"] == "10.0.26100 Build 26100"
    assert result["gpus"] == [
        {
            "name": "NVIDIA GeForce RTX 5090 Laptop GPU",
            "driver_version": "32.0.15.6636",
            "driver_date": "2/14/2026",
        },
        {
            "name": "Intel(R) Graphics",
            "driver_version": "32.0.101.1234",
            "driver_date": "1/15/2026",
        },
    ]


def test_spanish_export():
    result = msinfo.parse_msinfo(FIXTURES / "es.txt")
    assert result["manufacturer"] == "LENOVO"
    assert result["model"] == "Legion Pro 7 16IAX10H"
    assert result["machine_type"] == "83F5"
    assert result["bios_version"] == "LENOVO N3FCN12W"
    assert result["bios_date"] == "01/04/2026"
    assert result["os_name"] == "Microsoft Windows 11 Pro"
    assert result["gpus"][0]["name"] == "NVIDIA GeForce RTX 5090 Laptop GPU"
    assert result["gpus"][0]["driver_version"] == "32.0.15.6636"
    assert result["gpus"][0]["driver_date"] == "14/02/2026"
    assert len(result["gpus"]) == 2


def test_user_and_computer_names_never_extracted():
    for name in ("en.txt", "es.txt"):
        result = msinfo.parse_msinfo(FIXTURES / name)
        assert "FAKE123" not in str(result)
        assert "fakeuser" not in str(result)
        assert "usuarioprueba" not in str(result)


def test_utf16_with_bom(tmp_path):
    raw = (FIXTURES / "en.txt").read_bytes().decode("utf-8")
    encoded = raw.encode("utf-16")
    assert encoded.startswith(b"\xff\xfe")
    path = tmp_path / "export.txt"
    path.write_bytes(encoded)
    assert msinfo.parse_msinfo(path)["machine_type"] == "83F5"


def test_decode_sniffs_bom():
    assert msinfo.decode_msinfo_bytes("OS Name\tX".encode("utf-16")) == "OS Name\tX"
    assert msinfo.decode_msinfo_bytes("OS Name\tX".encode("utf-8-sig")) == "OS Name\tX"
    assert msinfo.decode_msinfo_bytes(b"OS Name\tX") == "OS Name\tX"


def test_missing_fields_are_null():
    result = msinfo.parse_msinfo_text("[System Summary]\n\nOS Name\tWindows\n")
    assert result["os_name"] == "Windows"
    assert result["manufacturer"] is None
    assert result["model"] is None
    assert result["machine_type"] is None
    assert result["bios_version"] is None
    assert result["gpus"] == []


def test_machine_type_from_short_model_name():
    text = "[System Summary]\n\nSystem Model\t83F5\n"
    assert msinfo.parse_msinfo_text(text)["machine_type"] == "83F5"
    text = "[System Summary]\n\nSystem Model\tLegion Pro 7 16IAX10H\n"
    assert msinfo.parse_msinfo_text(text)["machine_type"] is None
