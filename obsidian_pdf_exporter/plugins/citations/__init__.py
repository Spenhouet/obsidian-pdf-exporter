"""Support for pandoc citations, as written with the Citations and Zotero plugins.

``[@key]``, ``[@key, p. 12]``, ``[@a; @b]`` and ``@key`` are rendered by
``pandoc --citeproc`` from a BibTeX, BibLaTeX or CSL bibliography, with a
reference list at the end or below a ``References`` heading.
"""

from obsidian_pdf_exporter.plugins.citations.plugin import CitationsPlugin

__all__ = ["CitationsPlugin"]
