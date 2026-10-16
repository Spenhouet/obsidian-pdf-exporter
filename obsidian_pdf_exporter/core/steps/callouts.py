"""Callouts: ``> [!type] Title`` blockquotes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.steps.base import DocumentContext
    from obsidian_pdf_exporter.core.steps.base import PageContext


class CalloutsStep(Step):
    """Turn callouts into fenced divs with a title span."""

    name = "callouts"
    description = "Convert > [!type] callouts into styled blocks"
    priority = 70

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        return ("fenced_divs", "bracketed_spans")

    def process_markdown(self, content: str, context: PageContext) -> str:
        return convert_callouts(content)
