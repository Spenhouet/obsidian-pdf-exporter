"""PDF embeds: ``![[file.pdf]]``, ``![[file.pdf#page=3]]``, ``![[file.pdf|300]]``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.pdf_embeds import pdf_embed_settings
from obsidian_pdf_exporter.core.pdf_embeds import render_pdf_embeds
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class PdfEmbedsStep(Step):
    """Draw the pages of embedded PDF files as images.

    The work happens in :mod:`obsidian_pdf_exporter.core.pdf_embeds`.
    """

    name = "pdf_embeds"
    description = "Render ![[file.pdf]] embeds as images of their pages"
    priority = 38
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.build_dir is None or "![[" not in content:
            return content
        return render_pdf_embeds(
            content,
            context.page_folder,
            context.page_index,
            context.build_dir,
            pdf_embed_settings(context.options),
            context.vault_index,
            context.vault_root,
            warn=lambda message: context.warn(f"{message} in {context.where}"),
            outside=context.outside_link,
        )
