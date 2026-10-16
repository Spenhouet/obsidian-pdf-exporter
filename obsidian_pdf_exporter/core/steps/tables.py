"""Tables: empty header rows, column widths and landscape pages for wide tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.html_postprocess import LANDSCAPE_MODES
from obsidian_pdf_exporter.core.html_postprocess import normalize_colgroups
from obsidian_pdf_exporter.core.html_postprocess import remove_empty_table_headers
from obsidian_pdf_exporter.core.html_postprocess import wrap_wide_tables
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from collections.abc import Callable

    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class EmptyTableHeadersStep(Step):
    """Drop the empty header row pandoc writes for tables without a header."""

    name = "empty_table_headers"
    description = "Remove empty table header rows"
    priority = 200
    html_priority = 20

    def process_html(self, html: str, context: DocumentContext) -> str:
        return remove_empty_table_headers(html)


class ColumnWidthsStep(Step):
    """Give every table column a minimum width and fix the table layout."""

    name = "column_widths"
    description = "Normalise table column widths"
    priority = 210
    html_priority = 30

    def process_html(self, html: str, context: DocumentContext) -> str:
        return normalize_colgroups(html)


def landscape_settings(options: dict[str, str], log: Callable[[str], None]) -> tuple[int, str]:
    """Read ``-O tables.landscape=auto|on|off`` and ``tables.landscape_min_cols=N``."""
    mode = options.get("tables.landscape", "auto").strip().lower() or "auto"
    if mode not in LANDSCAPE_MODES:
        log(f"  Warning: unknown tables.landscape={mode!r}, using 'auto'")
        mode = "auto"
    raw = options.get("tables.landscape_min_cols", "").strip()
    min_cols = 6
    if raw:
        if raw.isdigit() and int(raw) >= 1:
            min_cols = int(raw)
        else:
            log(f"  Warning: tables.landscape_min_cols={raw!r} is not a positive number, using 6")
    return min_cols, mode


class WideTablesStep(Step):
    """Put tables that need the width on landscape pages. Not used for redlines."""

    name = "wide_tables"
    description = "Move wide tables to landscape pages"
    priority = 220
    html_priority = 80

    def process_html(self, html: str, context: DocumentContext) -> str:
        if context.redline:
            return html
        html, has_wide = wrap_wide_tables(html, *landscape_settings(context.options, context.log))
        if has_wide:
            context.log("  Wide tables detected — landscape orientation applied for those pages")
        return html
