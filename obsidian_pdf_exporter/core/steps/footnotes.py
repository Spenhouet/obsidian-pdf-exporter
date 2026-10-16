"""Footnotes: ``[^label]`` references, their definitions and ``^[inline]`` notes."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.footnotes import FOOTNOTE_MODES
from obsidian_pdf_exporter.core.footnotes import notes_to_page_bottom
from obsidian_pdf_exporter.core.footnotes import scope_labels
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext
    from obsidian_pdf_exporter.core.steps.base import PageContext


def footnote_mode(options: dict[str, str], log) -> str:  # noqa: ANN001 - callable(str)
    """Read ``-O footnotes=page|end``."""
    mode = options.get("footnotes", "page").strip().lower() or "page"
    if mode not in FOOTNOTE_MODES:
        log(f"  Warning: unknown footnotes={mode!r}, using 'page'")
        mode = "page"
    return mode


class FootnotesStep(Step):
    """Keep the footnotes of each note apart and put them at the bottom of the page."""

    name = "footnotes"
    description = "Scope footnote labels per note and show notes at the page bottom"
    priority = 65
    html_priority = 85
    embedded = True

    def __init__(self) -> None:
        self._scopes = itertools.count(1)

    def process_markdown(self, content: str, context: PageContext) -> str:
        if "[^" not in content:
            return content
        return scope_labels(content, f"n{next(self._scopes)}")

    def process_html(self, html: str, context: DocumentContext) -> str:
        if footnote_mode(context.options, context.log) == "end":
            return html
        return notes_to_page_bottom(html)
