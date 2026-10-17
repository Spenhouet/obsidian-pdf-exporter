"""WeasyPrint-driven HTML → PDF rendering."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.diagram_fit import render_fitted

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from obsidian_pdf_exporter.core.diagram_fit import FitSettings
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


def html_to_pdf(
    html: str,
    output_path: Path,
    base_url: str = "",
    fit: FitSettings | None = None,
) -> None:
    """Render ``html`` to a PDF at ``output_path`` using WeasyPrint.

    WeasyPrint converts ``<a href="#id">`` anchors to native PDF GoTo
    annotations and builds the bookmark tree from heading hierarchy with no
    extra work required. With ``fit``, Mermaid diagrams taller than their
    page are scaled or cut to fit it, see :mod:`.diagram_fit`.
    """
    from weasyprint import HTML

    with svg_current_color():
        document = render_fitted(HTML(string=html, base_url=base_url or None), fit)
        document.write_pdf(str(output_path))


_SVG_TAG = "{http://www.w3.org/2000/svg}svg"


@contextmanager
def svg_current_color() -> Iterator[None]:
    """Let ``currentColor`` in inline SVG use the color of the surrounding text.

    Browsers resolve ``currentColor`` inside an inline ``<svg>`` to the CSS
    ``color`` of the element around it. WeasyPrint draws inline SVG with its
    own SVG renderer, which only sees the attributes of the SVG and falls back
    to black. While this context is active, every inline ``<svg>`` without a
    ``color`` attribute gets the computed text color as its ``color``
    attribute, so math in a colored callout has the callout's color. If
    WeasyPrint has no such handler, nothing changes.
    """
    try:
        from weasyprint import html as weasy_html

        handlers = weasy_html.HTML_HANDLERS
        original = handlers[_SVG_TAG]
    except (ImportError, AttributeError, KeyError):
        yield
        return

    def handle_svg(element, box, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if element.get("color") is None:
            color = css_color(box.style["color"])
            if color:
                element.set("color", color)
        return original(element, box, *args, **kwargs)

    handlers[_SVG_TAG] = handle_svg
    try:
        yield
    finally:
        handlers[_SVG_TAG] = original


def css_color(color: object) -> str:
    """Return a computed WeasyPrint color as ``rgb()``, or ``""`` if unknown."""
    try:
        if hasattr(color, "to"):
            srgb = color.to("srgb")
            red, green, blue = srgb.coordinates
            alpha = srgb.alpha
        else:
            red, green, blue, alpha = color
    except (TypeError, ValueError, AttributeError):
        return ""
    return f"rgb({red * 255:.0f} {green * 255:.0f} {blue * 255:.0f} / {alpha:g})"
