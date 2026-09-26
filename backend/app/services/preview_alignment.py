"""Build stable page anchors for the source-PDF/Markdown preview pair."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any


PAGE_MARKER_PATTERN = re.compile(r"<!--\s*docvortex-page:\s*(\d+)\s*-->")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_DECORATION_PATTERN = re.compile(r"[`*_#>~|]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _flatten_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flatten_content(item) for item in value)
    if isinstance(value, dict):
        return _flatten_content(value.get("content", ""))
    return ""


def _normalize_for_search(value: str) -> str:
    """Normalize MinerU block text and Markdown into the same search space."""
    value = html.unescape(value)
    value = _HTML_TAG_PATTERN.sub(" ", value)
    value = _IMAGE_PATTERN.sub(" ", value)
    value = _LINK_PATTERN.sub(r"\1", value)
    value = _MARKDOWN_DECORATION_PATTERN.sub(" ", value)
    value = value.replace(r"\*", " ").replace(r"\_", " ")
    return _WHITESPACE_PATTERN.sub(" ", value).strip().casefold()


def _normalized_with_positions(value: str) -> tuple[str, list[int]]:
    """Return normalized text and the source index of each normalized character.

    The mapping lets us find a block in normalized Markdown and then place the
    resulting page anchor at a safe raw line boundary.
    """
    normalized_chars: list[str] = []
    raw_positions: list[int] = []
    in_tag = False
    pending_space = False

    for index, char in enumerate(value):
        if char == "<":
            in_tag = True
            pending_space = True
            continue
        if in_tag:
            if char == ">":
                in_tag = False
            continue
        # Markdown table pipes and emphasis markers are formatting, not word
        # boundaries. Skip them before flushing pending whitespace so a table
        # such as ``a | b`` normalizes to the same text as MinerU's content
        # list instead of acquiring duplicate spaces around ``|``.
        if char in "`*_#>~|":
            continue
        if char.isspace():
            pending_space = True
            continue
        if pending_space and normalized_chars:
            normalized_chars.append(" ")
            raw_positions.append(index)
        pending_space = False
        normalized_chars.append(char.casefold())
        raw_positions.extend([index] * len(char.casefold()))

    while normalized_chars and normalized_chars[-1] == " ":
        normalized_chars.pop()
        raw_positions.pop()
    return "".join(normalized_chars), raw_positions


def _block_candidates(page: dict[str, Any]) -> list[str]:
    preferred_types = {"doc_title", "paragraph_title", "text", "ref_text", "equation", "table"}
    blocks = page.get("blocks") or []
    preferred = [block for block in blocks if block.get("type") in preferred_types]
    others = [block for block in blocks if block not in preferred]
    candidates: list[str] = []
    for block in preferred + others:
        raw_content = _flatten_content(block.get("content", ""))
        if block.get("type") == "table":
            # Full table strings are fragile across MinerU versions because
            # empty cells and separator rows may be normalized differently.
            # Match the header/data rows independently first, then retain the
            # full table as a fallback for more distinctive tables.
            table_rows_added = 0
            for line in raw_content.splitlines():
                if not line.strip() or set(line.replace("|", "").replace(" ", "")) <= {"-", ":"}:
                    continue
                row = _normalize_for_search(line)
                if len(row) >= 8:
                    candidates.append(row[:160])
                    table_rows_added += 1
                if table_rows_added >= 3:
                    break
        text = _normalize_for_search(raw_content)
        if len(text) < 8:
            continue
        # A short prefix is more resilient to Markdown formatting differences
        # and is enough to uniquely identify the page in document order.
        candidates.append(text[:160])
    return candidates


def build_page_markers(markdown_text: str, content_list: dict[str, Any]) -> list[dict[str, int]]:
    """Return 1-based page markers with UTF-8 byte offsets into Markdown."""
    normalized, positions = _normalized_with_positions(markdown_text)
    pages = content_list.get("pages") if isinstance(content_list, dict) else None
    if not isinstance(pages, list) or not pages:
        return []

    markers: list[dict[str, int]] = []
    search_from = 0
    for page_index, page in enumerate(pages):
        raw_index: int | None = None
        found_index: int | None = None
        for candidate in _block_candidates(page):
            found = normalized.find(candidate, search_from)
            if found < 0:
                continue
            raw_index = positions[found]
            found_index = found
            break

        # A page containing only figures/tables may have no searchable text,
        # but MinerU keeps the physical page number in generated image names.
        if raw_index is None:
            raw_search_from = positions[search_from] if search_from < len(positions) else len(markdown_text)
            image_index = markdown_text.find(f"images/page_{page_index + 1}_", raw_search_from)
            if image_index >= 0:
                raw_index = image_index

        if raw_index is None:
            if markers:
                # Image/table-only pages may have no searchable text. Keep the
                # page order monotonic and place the anchor at the next line.
                raw_index = min(len(markdown_text), markers[-1]["_raw_index"] + 1)
            else:
                raw_index = 0

        line_start = markdown_text.rfind("\n", 0, raw_index) + 1
        byte_offset = len(markdown_text[:line_start].encode("utf-8"))
        if markers and byte_offset <= markers[-1]["offset"]:
            byte_offset = markers[-1]["offset"]
        markers.append({"page": page_index + 1, "offset": byte_offset, "_raw_index": line_start})
        if found_index is not None:
            search_from = found_index + 1

    for marker in markers:
        marker.pop("_raw_index", None)
    return markers


def build_page_map_file(output_dir: str, markdown_text: str) -> str | None:
    """Build a persisted map from a parsed output directory, if available."""
    root = Path(output_dir)
    candidates = sorted(
        path
        for path in root.rglob("*.json")
        if path.name.endswith("_content_list.json") or path.name == "content_list.json"
    )
    for path in candidates:
        try:
            content_list = json.loads(path.read_text(encoding="utf-8"))
            markers = build_page_markers(markdown_text, content_list)
        except (OSError, ValueError, TypeError):
            continue
        if markers:
            map_path = root / "_preview" / "page_map.json"
            map_path.parent.mkdir(parents=True, exist_ok=True)
            map_path.write_text(json.dumps({"version": 1, "markers": markers}), encoding="utf-8")
            return str(map_path)
    return None
