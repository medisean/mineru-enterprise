"""MinerU 4.x compatibility helpers for the Enterprise worker."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


MINERU_TIER_ALIASES = {
    "pipeline": "basic",
    "vlm": "advanced",
    "vlm-engine": "advanced",
    "vlm-auto-engine": "advanced",
    "vlm-http-client": "advanced",
    "hybrid": "standard",
    "hybrid-engine": "standard",
    "hybrid-auto-engine": "standard",
}
MINERU_TIERS = {"flash", "basic", "standard", "advanced"}


def normalize_mineru_tier(backend: str, default_backend: str = "pipeline") -> str:
    """Map a legacy backend name or current tier to a MinerU 4.x tier."""
    value = (backend or default_backend or "pipeline").strip().lower()
    value = MINERU_TIER_ALIASES.get(value, value)
    if value not in MINERU_TIERS:
        raise ValueError(
            f"Unsupported MinerU backend/tier '{backend}'. "
            "Use pipeline/basic, hybrid/standard, or vlm/advanced."
        )
    return value


def _parse_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_mineru_command(
    input_path: str,
    output_dir: str,
    *,
    backend: str,
    default_backend: str = "pipeline",
    is_ocr: bool | None = None,
    page_ranges: str | None = None,
    image_analysis: bool = False,
    api_url: str | None = None,
    api_key: str | None = None,
    parse_options: dict | None = None,
    python_executable: str | None = None,
) -> list[str]:
    """Build the official 4.x ``mineru-kit parse`` command."""
    options = parse_options or {}
    tier = normalize_mineru_tier(str(options.get("tier") or backend or ""), default_backend)
    ocr_mode = options.get("ocr-mode", options.get("ocr_mode"))
    if ocr_mode is None:
        ocr_mode = "ocr" if is_ocr is True else "txt" if is_ocr is False else "auto"
    ocr_mode = str(ocr_mode).strip().lower()
    if ocr_mode not in {"auto", "txt", "ocr"}:
        raise ValueError(f"Unsupported MinerU OCR mode '{ocr_mode}'")

    pages = options.get("pages", options.get("page-range", page_ranges))
    remote_url = options.get("remote-url", options.get("remote_url")) or api_url
    key = options.get("api-key", options.get("api_key")) or api_key
    disable_image_analysis = options.get("disable-image-analysis", options.get("disable_image_analysis"))
    if disable_image_analysis is None:
        disable_image_analysis = not image_analysis
    else:
        disable_image_analysis = _parse_bool(disable_image_analysis, not image_analysis)

    command = [
        python_executable or sys.executable,
        "-m",
        "mineru.kit.main",
        "parse",
        input_path,
        "--output",
        output_dir,
        "--format",
        "zip",
        "--tier",
        tier,
        "--ocr-mode",
        ocr_mode,
    ]
    if pages:
        command.extend(["--pages", str(pages)])
    if disable_image_analysis:
        command.append("--disable-image-analysis")
    if remote_url:
        command.extend(["--remote-url", str(remote_url)])
    if key:
        command.extend(["--api-key", str(key)])
    return command


def extract_mineru_zip(output_dir: str, source_stem: str) -> None:
    """Expand a MinerU 4.x result zip and preserve Enterprise result names."""
    root = Path(output_dir).resolve()
    archives = sorted(path for path in root.glob("*.zip") if path.is_file())
    if not archives:
        raise RuntimeError("MinerU completed without producing a zip result")
    archive = archives[0]
    with zipfile.ZipFile(archive) as result_zip:
        for member in result_zip.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"Unsafe path in MinerU result archive: {member.filename}")
        result_zip.extractall(root)
    archive.unlink()

    names = {
        "markdown.md": f"{source_stem}.md",
        "middle_json.json": f"{source_stem}_middle.json",
        "structured_content.json": f"{source_stem}_content_list.json",
        "model_output.json": f"{source_stem}_model.json",
    }
    for old_name, new_name in names.items():
        old_path = root / old_name
        new_path = root / new_name
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
