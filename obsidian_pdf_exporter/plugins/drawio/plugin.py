"""draw.io plugin implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.drawio.svg import clean_drawio_svg

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.base import DocumentContext


class DrawioPlugin(ObsidianPlugin):
    """Make draw.io SVG labels printable without ``<foreignObject>`` support."""

    name = "drawio"
    description = "Turn draw.io HTML labels in SVG images into plain SVG text"
    priority = 40

    def process_svg(self, svg: str, context: DocumentContext) -> str:
        return clean_drawio_svg(svg)
