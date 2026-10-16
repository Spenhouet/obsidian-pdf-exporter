"""Landscape pages for figures marked ``landscape``, such as wide Mermaid diagrams."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.landscape import wrap_landscape_figures
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class LandscapeFiguresStep(Step):
    """Put figures marked ``landscape`` on landscape pages. Not used for redlines."""

    name = "landscape_figures"
    description = "Move wide diagrams to landscape pages"
    priority = 225
    html_priority = 82

    def process_html(self, html: str, context: DocumentContext) -> str:
        if context.redline:
            return html
        html, wrapped = wrap_landscape_figures(html)
        if wrapped:
            context.log("  Wide diagrams detected, landscape orientation applied for those pages")
        return html
