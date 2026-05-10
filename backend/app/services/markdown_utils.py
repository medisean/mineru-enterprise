"""
Markdown post-processing utilities.

Converts HTML tables embedded in MinerU office output to Markdown tables,
so the right panel renders cleanly without raw HTML.
"""

import re
from html.parser import HTMLParser
from io import StringIO


class _HTMLTableParser(HTMLParser):
    """Parse an HTML <table> and convert it to Markdown."""

    def __init__(self):
        super().__init__()
        self._rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell = StringIO()
        self._in_cell = False
        self._in_table = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "table":
            self._in_table = True
            self._depth = 0
            self._rows = []
        elif tag_lower == "tr" and self._in_table:
            self._current_row = []
        elif tag_lower in ("td", "th") and self._in_table:
            self._in_cell = True
            self._current_cell = StringIO()
            self._is_header = tag_lower == "th"

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "table" and self._in_table:
            self._in_table = False
        elif tag_lower == "tr" and self._in_table:
            if self._current_row:
                self._rows.append(self._current_row)
            self._current_row = []
        elif tag_lower in ("td", "th") and self._in_table:
            self._in_cell = False
            cell_text = self._current_cell.getvalue().strip()
            self._current_row.append(cell_text)

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell.write(data)

    def handle_entityref(self, name):
        entities = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}
        if self._in_cell:
            self._current_cell.write(entities.get(name, f"&{name};"))

    def handle_charref(self, name):
        if self._in_cell:
            try:
                if name.startswith("x"):
                    char = chr(int(name[1:], 16))
                else:
                    char = chr(int(name))
                self._current_cell.write(char)
            except (ValueError, OverflowError):
                self._current_cell.write(f"&#{name};")

    def to_markdown(self) -> str:
        if not self._rows:
            return ""
        # Determine max columns
        max_cols = max(len(row) for row in self._rows)
        # Pad rows
        for row in self._rows:
            while len(row) < max_cols:
                row.append("")
        # Calculate column widths
        col_widths = [3] * max_cols  # minimum width
        for row in self._rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))
        # Build markdown table
        lines = []
        for idx, row in enumerate(self._rows):
            padded = [cell.ljust(col_widths[i]) for i, cell in enumerate(row)]
            lines.append("| " + " | ".join(padded) + " |")
            # Add separator after header row (first row) if there are multiple rows
            if idx == 0 and len(self._rows) > 1:
                sep = ["-" * w for w in col_widths]
                lines.append("| " + " | ".join(sep) + " |")
        return "\n".join(lines)


def _html_table_to_markdown(html: str) -> str:
    """Convert a single HTML <table> block to Markdown table."""
    parser = _HTMLTableParser()
    parser.feed(html)
    return parser.to_markdown()


# Regex to match HTML tables (including nested tags)
# Matches <table...>...</table> with possible whitespace
_HTML_TABLE_RE = re.compile(
    r"<table\b[^>]*>.*?</table>",
    re.DOTALL | re.IGNORECASE,
)


def convert_html_tables_to_markdown(text: str) -> str:
    """
    Replace all HTML <table> blocks in text with Markdown tables.

    This is specifically designed for MinerU office backend output,
    which embeds raw HTML tables in Markdown files.

    If a table cannot be converted (e.g. malformed HTML), the original
    HTML is preserved.
    """
    def _replace(match: re.Match) -> str:
        html = match.group(0)
        md = _html_table_to_markdown(html)
        return md if md else html

    return _HTML_TABLE_RE.sub(_replace, text)
