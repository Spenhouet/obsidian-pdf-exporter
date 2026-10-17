"""Mermaid diagrams: ````` ```mermaid ````` code blocks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.mermaid import render_mermaid_blocks
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class MermaidStep(Step):
    """Render all Mermaid blocks of the document to images in one batch."""

    name = "mermaid"
    description = "Render Mermaid code blocks as diagrams"
    priority = 180

    def process_document(self, markdown: str, context: DocumentContext) -> str:
        template_config = {}
        if context.template is not None and context.export is not None:
            template_config = context.template.mermaid_config(context.export)
        settings = mermaid_settings(context.options, template_config)
        css = context.template.get_css() if context.template is not None else ""
        return render_mermaid_blocks(
            markdown, context.build_dir, settings, log=context.log, css=css
        )
