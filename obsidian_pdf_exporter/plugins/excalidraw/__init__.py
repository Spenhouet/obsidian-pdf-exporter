"""Support for drawings of the Obsidian `Excalidraw` plugin.

Embeds such as ``![[Drawing.excalidraw]]`` become images: the plugin's
auto-export SVG or PNG when it exists, otherwise an SVG drawn from the
scene stored in the drawing.
"""

from obsidian_pdf_exporter.plugins.excalidraw.plugin import ExcalidrawPlugin

__all__ = ["ExcalidrawPlugin"]
