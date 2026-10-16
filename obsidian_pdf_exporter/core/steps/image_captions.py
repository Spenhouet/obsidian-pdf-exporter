"""Image captions: an italic line right below a captionless image."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step
from obsidian_pdf_exporter.core.wiki_links import promote_image_captions

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class ImageCaptionsStep(Step):
    """Use the italic line below an image as its figure caption."""

    name = "image_captions"
    description = "Turn an italic line below an image into its caption"
    priority = 110

    def process_markdown(self, content: str, context: PageContext) -> str:
        return promote_image_captions(content)
