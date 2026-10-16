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

#: Text that :func:`resolve_dataview_blocks` puts in place of a query it cannot run.
_UNSUPPORTED = "not supported in PDF export."


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
        rendered = resolve_dataview_blocks(content, index)
        skipped = rendered.count(_UNSUPPORTED) - content.count(_UNSUPPORTED)
        warn = getattr(context, "warn", None)
        if skipped > 0 and warn is not None:
            where = getattr(context, "where", "the page")
            warn(f"cannot render {skipped} DataviewJS or TASK query(s) in {where}")
        return rendered
