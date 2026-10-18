"""WeasyPrint-driven HTML → PDF rendering."""

from __future__ import annotations

import base64
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.core.diagram_fit import render_fitted
from obsidian_pdf_exporter.core.html_postprocess import RE_EMBEDDED_IMAGE

if TYPE_CHECKING:
    import re
    from collections.abc import Iterator

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

    with tempfile.TemporaryDirectory(prefix="ope-images-") as folder:
        html = images_to_files(html, Path(folder))
        cache = image_cache(Path(folder) / "cache")
        with svg_current_color():
            document = render_fitted(HTML(string=html, base_url=base_url or None), fit, cache)
            document.write_pdf(str(output_path))


def image_cache(folder: Path) -> Any:  # noqa: ANN401 - a WeasyPrint cache
    """Return a WeasyPrint image cache that keeps image bytes in ``folder``.

    WeasyPrint keeps the data of every image stream it builds in its image
    cache until the PDF is written. With a dict, all of it stays in memory,
    which on a document with many screenshots is a large part of the peak.
    WeasyPrint's ``DiskCache`` writes the bytes to files and reads
    them back when the PDF is written, so the PDF is the same. If this
    WeasyPrint has no ``DiskCache``, a dict is used.
    """
    try:
        from weasyprint.document import DiskCache
    except ImportError:
        return {}
    return DiskCache(folder)


def images_to_files(html: str, folder: Path) -> str:
    """Move the raster images that pandoc embedded as ``data:`` URLs into files.

    ``pandoc --embed-resources`` writes every image into the HTML as base64.
    WeasyPrint's HTML parser is written in Python, so a document with many
    screenshots takes long to parse and keeps the text in memory. Each image
    is written once to ``folder`` and its ``src`` points at the file; the same
    image data gets the same file. WeasyPrint reads the same bytes, so the PDF
    looks the same.
    """
    files: dict[str, str] = {}

    def replace(m: re.Match[str]) -> str:
        data = m.group("data")
        url = files.get(data)
        if url is None:
            try:
                raw = base64.b64decode(data, validate=True)
            except ValueError:
                return m.group(0)
            path = folder / f"image-{len(files)}.{m.group('type')}"
            path.write_bytes(raw)
            url = files[data] = path.as_uri()
        return f'src="{url}"'

    return RE_EMBEDDED_IMAGE.sub(replace, html)


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
