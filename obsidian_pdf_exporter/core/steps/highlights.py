"""Highlights: ``==text==``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class HighlightsStep(Step):
    """Let pandoc read ``==text==`` as ``<mark>``."""

    name = "highlights"
    description = "Render ==text== as highlighted text"
    priority = 140

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        return ("mark",)
