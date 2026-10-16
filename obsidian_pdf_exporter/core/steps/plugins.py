"""The slot of the community plugin layer in the core pipeline.

Plugins (see :mod:`obsidian_pdf_exporter.plugins`) run here, in their own
priority order: their markdown hook right after the frontmatter is gone,
and their HTML hook after the other HTML steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext
    from obsidian_pdf_exporter.core.steps.base import PageContext


class PluginsStep(Step):
    """Run every active plugin's ``process_markdown`` and ``process_html``."""

    name = "plugins"
    description = "Run the community plugin hooks"
    priority = 20
    html_priority = 90
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        for plugin in context.plugins or ():
            content = plugin.process_markdown(content, context)
        return content

    def process_html(self, html: str, context: DocumentContext) -> str:
        for plugin in context.plugins:
            # Plugins written before the hook existed may not have it.
            hook = getattr(plugin, "process_html", None)
            if hook is not None:
                html = hook(html, context)
        return html
