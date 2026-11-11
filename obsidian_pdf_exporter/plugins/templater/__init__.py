"""Support for the Obsidian `Templater` plugin.

Templater runs the tags of a template (``<% ... %>``, ``<%* ... %>``) when
the template is applied to a note. Reading view does not run them, so this
module removes them from the PDF instead of printing their code.
"""

from obsidian_pdf_exporter.plugins.templater.plugin import TemplaterPlugin

__all__ = ["TemplaterPlugin"]
