"""Local Markdown and HTML images: ``![alt](../img/chart.png)`` and ``<img src="chart.png">``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.markdown_images import convert_markdown_images
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class MarkdownImagesStep(Step):
    """Look up local image paths from the note's folder and copy the images to the build folder.

    The work happens in :mod:`obsidian_pdf_exporter.core.markdown_images`.
    """

    name = "markdown_images"
    description = "Resolve ![alt](path) and <img src> images from the note's folder"
    priority = 85
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.build_dir is None:
            return content
        return convert_markdown_images(
            content,
            context.page_folder,
            context.build_dir,
            context.vault_root,
            context.vault_index,
            warn=lambda message: context.warn(f"{message} in {context.where}"),
        )
