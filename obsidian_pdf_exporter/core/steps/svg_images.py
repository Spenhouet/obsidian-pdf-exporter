"""SVG images: inline them into the HTML so WeasyPrint draws them reliably."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class SvgImagesStep(Step):
    """Replace ``<img>`` tags of SVG files with the ``<svg>`` element.

    Each plugin's ``process_svg`` hook gets every SVG on the way.
    """

    name = "svg_images"
    description = "Inline SVG images"
    priority = 190
    html_priority = 40

    def process_html(self, html: str, context: DocumentContext) -> str:
        def process_svg(svg: str) -> str:
            for plugin in context.plugins:
                hook = getattr(plugin, "process_svg", None)
                if hook is not None:
                    svg = hook(svg, context)
            return svg

        return inline_svg_images(html, context.build_dir, process_svg=process_svg)
