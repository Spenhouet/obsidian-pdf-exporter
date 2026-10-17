"""Stray HTML tags that would hide the rest of the document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.raw_html import neutralize_unclosed_tags
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class RawHtmlStep(Step):
    """Show an unclosed ``<style>``, ``<script>``, ``<title>`` (and similar) tag as text.

    See :mod:`obsidian_pdf_exporter.core.raw_html` for the rules.
    """

    name = "raw_html"
    description = "Show unclosed <style>, <script> and similar tags as text"
    priority = 55

    def process_markdown(self, content: str, context: PageContext) -> str:
        content, found = neutralize_unclosed_tags(content)
        for tag in dict.fromkeys(found):
            context.warn(f"<{tag}> in {context.where} has no closing tag, kept as text")
        return content
