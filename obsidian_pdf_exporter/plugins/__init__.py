"""Obsidian-plugin support modules.

This package implements the bridge between non-core Obsidian features
(Dataview, Meta Bind, …) and the markdown the exporter feeds to pandoc.

Each Obsidian plugin lives in its own subpackage so contributors can add
support for additional plugins (Tasks, Excalidraw, Templater, …) without
touching the rest of the codebase. See ``CONTRIBUTING.md`` for the
walkthrough on adding a new one.

The bundled subpackages are :mod:`~obsidian_pdf_exporter.plugins.folder_notes`,
:mod:`~obsidian_pdf_exporter.plugins.dataview`,
:mod:`~obsidian_pdf_exporter.plugins.meta_bind`,
:mod:`~obsidian_pdf_exporter.plugins.block_link_plus` and
:mod:`~obsidian_pdf_exporter.plugins.drawio`.
"""

from obsidian_pdf_exporter.plugins.base import DocumentContext
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.base import PluginContext
from obsidian_pdf_exporter.plugins.registry import active_plugins
from obsidian_pdf_exporter.plugins.registry import available_plugins
from obsidian_pdf_exporter.plugins.registry import register_plugin

__all__ = [
    "DocumentContext",
    "ObsidianPlugin",
    "PluginContext",
    "active_plugins",
    "available_plugins",
    "register_plugin",
]
