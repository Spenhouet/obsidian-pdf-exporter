"""A template that adds a confidentiality label from ``-O confidentiality=...``.

It extends the built-in default template, so it keeps all of its CSS and
its header and footer, and only adds a label at the top right of each page.

    ope export ./Notes -T confidential -O confidentiality=Internal
"""

from __future__ import annotations

from obsidian_pdf_exporter.templates import Decorations
from obsidian_pdf_exporter.templates import ExportContext
from obsidian_pdf_exporter.templates.builtin.default import DefaultTemplate


class ConfidentialTemplate(DefaultTemplate):
    """The default template plus a confidentiality label."""

    name = "confidential"
    description = "Default template with a confidentiality label"

    def decorations(self, context: ExportContext) -> Decorations | None:
        base = super().decorations(context) or Decorations()
        label = context.options.get("confidentiality", "")
        if not label:
            return base
        escaped = label.replace("&", "&amp;").replace("<", "&lt;")
        running_html = f'<span class="confidential-label">{escaped}</span>\n'
        page_css = """
.confidential-label {
    position: running(confidential);
    font-family: Arial, Helvetica, sans-serif;
    font-size: 8pt;
    font-weight: bold;
    text-transform: uppercase;
    color: #c53030;
    border: 1.5pt solid #c53030;
    padding: 2pt 6pt;
}
@page {
    @top-right { content: element(confidential); vertical-align: bottom; padding-bottom: 12pt; }
}
"""
        return Decorations(
            running_html=base.running_html + running_html,
            page_css=base.page_css + page_css,
        )


#: Picked up by scripts/render_examples.py for the docs screenshots.
TEMPLATE = ConfidentialTemplate
