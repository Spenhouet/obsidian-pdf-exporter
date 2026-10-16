"""Support for the Obsidian `Dataview` plugin.

A port of Dataview's query language, function library, page model and views,
so ```` ```dataview ```` blocks, inline queries, inline fields and DataviewJS
give the same result in the PDF as in Obsidian's reading view. See
:mod:`obsidian_pdf_exporter.plugins.dataview.plugin`.
"""

from obsidian_pdf_exporter.plugins.dataview.plugin import DataviewPlugin

__all__ = ["DataviewPlugin"]
