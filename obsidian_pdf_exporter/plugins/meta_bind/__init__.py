"""Support for the Obsidian `Meta Bind` plugin.

Meta Bind embeds reactive widgets in markdown files: ``VIEW``, ``INPUT``
and ``BUTTON``. This module evaluates ``VIEW`` widgets against the
frontmatter so they render as plain text in the PDF, and strips ``INPUT``
/ ``BUTTON`` widgets, which have no print equivalent.
"""

from obsidian_pdf_exporter.plugins.meta_bind.plugin import MetaBindPlugin

__all__ = ["MetaBindPlugin"]
