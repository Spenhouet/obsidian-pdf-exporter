"""Math: ``$inline$`` and ``$$display$$`` LaTeX."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.math_render import render_math
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class MathStep(Step):
    """Have pandoc write MathML, then render each formula to SVG."""

    name = "math"
    description = "Render LaTeX math to SVG"
    priority = 170
    html_priority = 70

    def pandoc_args(self, context: DocumentContext) -> Sequence[str]:
        # MathML keeps the formula structure; math_render turns it into SVG.
        return ("--mathml",)

    def process_html(self, html: str, context: DocumentContext) -> str:
        return render_math(html, log=context.log)
