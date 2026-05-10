"""
Helpers for MinerU official-compatible result packaging.
"""
from __future__ import annotations

import html
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Iterable


EXTRA_FORMATS = {"html", "docx", "latex"}
ZIP_EXPORT_DIR = "_exports"
FULL_ZIP_NAME = "full.zip"


def normalize_extra_formats(*values) -> list[str]:
    """Normalize official API extra format fields to supported export names."""
    formats: list[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            candidates = re.split(r"[,;\s]+", value)
        elif isinstance(value, Iterable):
            candidates = list(value)
        else:
            candidates = [value]
        for candidate in candidates:
            name = str(candidate).strip().lower().lstrip(".")
            if name == "tex":
                name = "latex"
            if name in EXTRA_FORMATS and name not in formats:
                formats.append(name)
    return formats


def render_extra_format_files(markdown_text: str, markdown_path: str, formats: list[str]) -> list[tuple[str, str]]:
    """Render lightweight extra files from MinerU Markdown output."""
    if not formats:
        return []

    source = Path(markdown_path)
    output_files: list[tuple[str, str]] = []
    for fmt in formats:
        if fmt == "html":
            out = source.with_suffix(".html")
            out.write_text(_markdown_to_html(markdown_text, source.stem), encoding="utf-8")
            output_files.append((str(out), "text/html"))
        elif fmt == "latex":
            out = source.with_suffix(".tex")
            out.write_text(_markdown_to_latex(markdown_text), encoding="utf-8")
            output_files.append((str(out), "application/x-latex"))
        elif fmt == "docx":
            out = source.with_suffix(".docx")
            _write_basic_docx(out, markdown_text)
            output_files.append((
                str(out),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ))
    return output_files


def build_result_zip_bytes(
    storage_service,
    output_prefix: str,
    *,
    original_key: str | None = None,
    original_filename: str | None = None,
) -> bytes:
    """Build a zip from all result objects under an output prefix."""
    objects = storage_service.list_objects(output_prefix or "")
    prefix = (output_prefix or "").rstrip("/") + "/"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for obj in objects:
            key = obj["key"]
            rel = key.replace(prefix, "", 1)
            if not rel or rel.startswith(f"{ZIP_EXPORT_DIR}/"):
                continue
            zf.writestr(rel, storage_service.download_bytes(key))

        if original_key and original_filename:
            zf.writestr(original_filename, storage_service.download_bytes(original_key))

    buffer.seek(0)
    return buffer.read()


def ensure_full_result_zip(storage_service, output_prefix: str) -> str | None:
    """Ensure an official-style full result zip exists and return its S3 key."""
    if not output_prefix:
        return None
    zip_key = f"{output_prefix.rstrip('/')}/{ZIP_EXPORT_DIR}/{FULL_ZIP_NAME}"
    for obj in storage_service.list_objects(f"{output_prefix.rstrip('/')}/{ZIP_EXPORT_DIR}/"):
        if obj["key"] == zip_key:
            return zip_key

    data = build_result_zip_bytes(storage_service, output_prefix)
    storage_service.upload_bytes(zip_key, data, "application/zip")
    return zip_key


def _markdown_to_html(markdown_text: str, title: str) -> str:
    body = []
    in_code = False
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            body.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(line))
            continue
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip()
            body.append(f"<h{level}>{html.escape(content)}</h{level}>")
        elif stripped:
            body.append(f"<p>{html.escape(line)}</p>")
        else:
            body.append("")

    if in_code:
        body.append("</code></pre>")

    safe_title = html.escape(title)
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\">"
        f"<title>{safe_title}</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "line-height:1.65;max-width:960px;margin:40px auto;padding:0 24px;}"
        "pre{background:#f6f8fa;padding:16px;overflow:auto;}img{max-width:100%;}</style>"
        "</head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


def _markdown_to_latex(markdown_text: str) -> str:
    escaped = markdown_text.replace("\\end{verbatim}", "\\textbackslash{}end\\{verbatim\\}")
    return (
        "\\documentclass{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage{geometry}\n"
        "\\geometry{margin=1in}\n"
        "\\begin{document}\n"
        "\\begin{verbatim}\n"
        f"{escaped}\n"
        "\\end{verbatim}\n"
        "\\end{document}\n"
    )


def _write_basic_docx(path: Path, markdown_text: str) -> None:
    paragraphs = "\n".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(line)}</w:t></w:r></w:p>"
        for line in markdown_text.splitlines()
    )
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        f"<w:body>{paragraphs}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/>"
        "</Relationships>"
    )

    os.makedirs(path.parent, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
