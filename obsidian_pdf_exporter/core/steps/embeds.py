"""Note, heading and block embeds: ``![[Note]]``, ``![[Note#Heading]]``, ``![[Note#^id]]``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.embeds import expand_note_embeds
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class EmbedsStep(Step):
    """Replace note embeds with the embedded content.

    The work happens in :mod:`obsidian_pdf_exporter.core.embeds`.
    """

    name = "embeds"
    description = "Expand ![[Note]], ![[Note#Heading]] and ![[Note#^id]] embeds"
    priority = 40
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.source_file is None:
            return content
        return expand_note_embeds(content, context.source_file, context)
