"""Support for SVG images exported by draw.io (diagrams.net).

draw.io writes labels as HTML inside ``<foreignObject>``, which WeasyPrint
does not draw. This module replaces them with plain SVG text while the SVG
is inlined into the HTML.
"""

from obsidian_pdf_exporter.plugins.drawio.plugin import DrawioPlugin

__all__ = ["DrawioPlugin"]
