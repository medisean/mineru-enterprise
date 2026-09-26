from app.services.file_validation import validate_file_magic
from app.services.mineru_compat import build_mineru_command, normalize_mineru_tier


def test_official_file_signatures_include_legacy_office_and_html():
    ole_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
    html_header = b"<!doctype html><html><body>"

    assert validate_file_magic(ole_header, "doc")
    assert validate_file_magic(ole_header, "ppt")
    assert validate_file_magic(ole_header, "xls")
    assert validate_file_magic(html_header, "html")


def test_official_html_and_legacy_office_models_use_flash_tier():
    assert normalize_mineru_tier("MinerU-HTML") == "flash"
    for filename in ("report.doc", "slides.ppt", "table.xls", "page.html"):
        command = build_mineru_command(filename, "/tmp/output", backend="pipeline")
        assert command[command.index("--tier") + 1] == "flash"
