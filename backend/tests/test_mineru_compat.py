from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services.mineru_compat import (
    build_mineru_command,
    extract_mineru_zip,
    normalize_mineru_tier,
)


def test_legacy_backend_names_map_to_mineru_4_tiers():
    assert normalize_mineru_tier("pipeline") == "basic"
    assert normalize_mineru_tier("hybrid-auto-engine") == "standard"
    assert normalize_mineru_tier("vlm-auto-engine") == "advanced"
    assert normalize_mineru_tier("standard") == "standard"


def test_builds_official_mineru_4_command():
    command = build_mineru_command(
        "/tmp/input.pdf",
        "/tmp/output",
        backend="pipeline",
        is_ocr=False,
        page_ranges="1-3,8",
        image_analysis=False,
        api_url="http://mineru-api:8000",
        api_key="secret",
        python_executable="python3",
    )

    assert command[:5] == ["python3", "-m", "mineru.kit.main", "parse", "/tmp/input.pdf"]
    assert "--tier" in command and command[command.index("--tier") + 1] == "basic"
    assert "--ocr-mode" in command and command[command.index("--ocr-mode") + 1] == "txt"
    assert "--pages" in command and command[command.index("--pages") + 1] == "1-3,8"
    assert "--remote-url" in command and command[command.index("--remote-url") + 1] == "http://mineru-api:8000"
    assert "--api-key" in command and command[command.index("--api-key") + 1] == "secret"
    assert "--disable-image-analysis" in command
    assert command[1:3] == ["-m", "mineru.kit.main"]
    assert "-b" not in command


def test_office_documents_use_flash_tier_even_with_legacy_pipeline_default():
    command = build_mineru_command(
        "/tmp/input.docx",
        "/tmp/output",
        backend="pipeline",
    )

    assert command[command.index("--tier") + 1] == "flash"


def test_extracts_and_normalizes_mineru_4_zip(tmp_path: Path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    archive = output_dir / "report.zip"
    with ZipFile(archive, "w") as result_zip:
        result_zip.writestr("markdown.md", "# Report")
        result_zip.writestr("middle_json.json", '{"schema_version":"2.0"}')
        result_zip.writestr("structured_content.json", '{"content": []}')
        result_zip.writestr("images/figure.png", b"png")

    extract_mineru_zip(str(output_dir), "report")

    assert not archive.exists()
    assert (output_dir / "report.md").read_text() == "# Report"
    assert (output_dir / "report_middle.json").exists()
    assert (output_dir / "report_content_list.json").exists()
    assert (output_dir / "images/figure.png").read_bytes() == b"png"


def test_rejects_unsafe_result_zip(tmp_path: Path):
    archive = tmp_path / "result.zip"
    with ZipFile(archive, "w") as result_zip:
        result_zip.writestr("../escaped.txt", "no")

    with pytest.raises(RuntimeError, match="Unsafe path"):
        extract_mineru_zip(str(tmp_path), "result")
