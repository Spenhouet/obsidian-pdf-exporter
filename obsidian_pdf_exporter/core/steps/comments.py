"""HTML comments (``<!-- -->``) and Obsidian comments (``%% %%``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.embeds import strip_obsidian_comments
from obsidian_pdf_exporter.core.frontmatter import strip_html_comments
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class HtmlCommentsStep(Step):
    """Remove ``<!-- ... -->`` comments."""

    name = "html_comments"
    description = "Remove HTML comments"
    priority = 30
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        return strip_html_comments(content)


class ObsidianCommentsStep(Step):
    """Remove ``%% ... %%`` comments outside code blocks."""

    name = "obsidian_comments"
    description = "Remove Obsidian %% comments %%"
    priority = 50

    def process_markdown(self, content: str, context: PageContext) -> str:
        return strip_obsidian_comments(content)
