"""Links to headings on the same page: ``[[#Heading]]``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.heading_links import mark_same_page_links
from obsidian_pdf_exporter.core.heading_links import resolve_heading_links
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext
    from obsidian_pdf_exporter.core.steps.base import PageContext


class HeadingLinksStep(Step):
    """Tag ``[[#Heading]]`` links with their page, then point them at the real heading id."""

    name = "heading_links"
    description = "Resolve [[#Heading]] links within the page"
    priority = 80
    html_priority = 50

    def process_markdown(self, content: str, context: PageContext) -> str:
        node = context.node
        scope = node.anchor if node is not None and node.depth > 0 else ""
        return mark_same_page_links(content, scope)

    def process_html(self, html: str, context: DocumentContext) -> str:
        return resolve_heading_links(html)
