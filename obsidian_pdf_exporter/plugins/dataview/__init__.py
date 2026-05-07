"""Support for the Obsidian `Dataview` plugin.

This module evaluates a useful subset of the Dataview DQL language at
export time. ``TABLE``, ``LIST``, ``FROM``, ``WHERE``, ``SORT`` and
``LIMIT`` are supported; ``TASK``, ``CALENDAR`` and ``dataviewjs`` blocks
are replaced with placeholder text since they have no static rendering.
"""

from obsidian_pdf_exporter.plugins.dataview.plugin import DataviewPlugin

__all__ = ["DataviewPlugin"]
