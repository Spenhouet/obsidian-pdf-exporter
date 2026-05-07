"""WeasyPrint-driven HTML → PDF rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.templates.base import Decorations


def apply_decorations(html: str, decorations: Decorations | None) -> str:
    """Inject template-supplied ``running_html`` and ``page_css`` into the HTML."""
    if decorations is None:
        return html
    if decorations.page_css:
        html = html.replace(
            "</head>",
            f"<style>{decorations.page_css}</style>\n</head>",
            1,
        )
    if decorations.running_html:
        html = html.replace("<body>", f"<body>\n{decorations.running_html}", 1)
    return html


def html_to_pdf(html: str, output_path: Path, base_url: str = "") -> None:
    """Render ``html`` to a PDF at ``output_path`` using WeasyPrint.

    WeasyPrint converts ``<a href="#id">`` anchors to native PDF GoTo
    annotations and builds the bookmark tree from heading hierarchy with no
    extra work required.
    """
    from weasyprint import HTML

    HTML(string=html, base_url=base_url or None).write_pdf(str(output_path))
