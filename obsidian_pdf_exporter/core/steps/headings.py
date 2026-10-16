"""Headings: drop the repeated page title and nest the rest under the page heading."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.headings import normalize_heading_levels
from obsidian_pdf_exporter.core.headings import strip_title_heading
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class TitleHeadingStep(Step):
    """Remove a first heading that repeats the page name (the assembler adds it)."""

    name = "title_heading"
    description = "Remove a first heading equal to the page name"
    priority = 120

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.node is None:
            return content
        return strip_title_heading(content, context.node.name)


class HeadingLevelsStep(Step):
    """Re-level headings so they nest under the page heading without gaps."""

    name = "heading_levels"
    description = "Nest the page's headings under the page heading"
    priority = 130

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.node is None:
            return content
        depth = context.node.depth
        return normalize_heading_levels(content, depth + 1 if depth > 0 else 1)
