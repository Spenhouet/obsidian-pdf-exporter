"""Public template / plugin API.

A *template* is a small Python class (registered via the
``obsidian_pdf_exporter.templates`` entry point group) that supplies all
appearance concerns of a PDF export:

- the CSS used by pandoc + WeasyPrint,
- optional running header/footer HTML and ``@page`` rules,
- optional pre/post hooks that mutate markdown or HTML before rendering.

Everything in :mod:`obsidian_pdf_exporter.core` is brand-agnostic. All
visual identity (logos, footers, colour palette, page boxes …) lives in
templates so the project itself stays generic and additional templates can
be shipped as third-party packages or as plain CSS / directories on disk
(see :mod:`obsidian_pdf_exporter.templates.filesystem`).
"""

from obsidian_pdf_exporter.templates.base import Decorations
from obsidian_pdf_exporter.templates.base import ExportContext
from obsidian_pdf_exporter.templates.base import Template
from obsidian_pdf_exporter.templates.base import css_from_path
from obsidian_pdf_exporter.templates.filesystem import FilesystemTemplate
from obsidian_pdf_exporter.templates.filesystem import load_from_path
from obsidian_pdf_exporter.templates.registry import available_templates
from obsidian_pdf_exporter.templates.registry import load_template
from obsidian_pdf_exporter.templates.registry import register_template
from obsidian_pdf_exporter.templates.registry import resolve_template
from obsidian_pdf_exporter.templates.registry import template_sources
from obsidian_pdf_exporter.templates.registry import user_templates_dir

__all__ = [
    "Decorations",
    "ExportContext",
    "FilesystemTemplate",
    "Template",
    "available_templates",
    "css_from_path",
    "load_from_path",
    "load_template",
    "register_template",
    "resolve_template",
    "template_sources",
    "user_templates_dir",
]
