"""YAML frontmatter: parse it into the page context, then remove it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class FrontmatterStep(Step):
    """Read the frontmatter into ``context.frontmatter`` and remove it from the page."""

    name = "frontmatter"
    description = "Parse and remove the YAML frontmatter"
    priority = 10

    def process_markdown(self, content: str, context: PageContext) -> str:
        context.frontmatter = parse_frontmatter(content)
        return strip_frontmatter(content)
