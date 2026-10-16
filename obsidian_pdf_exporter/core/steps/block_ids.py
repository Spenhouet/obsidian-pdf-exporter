"""Block IDs: ``^id`` markers at the end of a block or on their own line."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.embeds import strip_block_ids
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class BlockIdsStep(Step):
    """Remove block ID markers once embeds have used them."""

    name = "block_ids"
    description = "Remove ^block-id markers"
    priority = 60

    def process_markdown(self, content: str, context: PageContext) -> str:
        return strip_block_ids(content)
