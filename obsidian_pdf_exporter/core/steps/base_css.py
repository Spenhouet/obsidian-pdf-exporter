"""Default styles for the markup the steps add."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.html_postprocess import add_base_css
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class BaseCssStep(Step):
    """Insert the base CSS at the start of ``<head>``, so templates can override it."""

    name = "base_css"
    description = "Add default styles before the template CSS"
    priority = 230
    html_priority = 10

    def process_html(self, html: str, context: DocumentContext) -> str:
        return add_base_css(html)
