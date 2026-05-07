"""Dataview plugin entry point.

The heavy lifting (parsing DQL, walking the vault, rendering tables) lives
in :mod:`obsidian_pdf_exporter.plugins.dataview.engine` so contributors who
want to extend Dataview support have an obvious place to start.
"""

from __future__ import annotations

from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.base import PluginContext
from obsidian_pdf_exporter.plugins.dataview.engine import resolve_dataview_blocks


class DataviewPlugin(ObsidianPlugin):
    """Render Dataview DQL queries as static markdown tables/lists."""

    name = "dataview"
    description = "Render Dataview DQL queries as static markdown tables/lists"
    # Run early so that any tables the queries produce flow through the
    # remaining pipeline (Meta Bind, callouts, wiki links) like normal text.
    priority = 10

    def process_markdown(self, content: str, context: PluginContext) -> str:
        index = context.vault_index
        if index is None:
            if context.vault_root is None:
                return content
            index = VaultIndex(context.vault_root)
        return resolve_dataview_blocks(content, index)
