"""The slot of the community plugin layer in the core pipeline.

Plugins (see :mod:`obsidian_pdf_exporter.plugins`) run here, in their own
priority order: their markdown hook right after the frontmatter is gone,
their document hook with the other document hooks, their pandoc reader
extensions and arguments with those of the steps, and their HTML hook
after the other HTML steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from collections.abc import Sequence

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

    def process_document(self, markdown: str, context: DocumentContext) -> str:
        for plugin in context.plugins:
            hook = getattr(plugin, "process_document", None)
            if hook is not None:
                markdown = hook(markdown, context)
        return markdown

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        return [e for p in context.plugins for e in _ask(p, "reader_extensions", context)]

    def pandoc_args(self, context: DocumentContext) -> Sequence[str]:
        return [a for p in context.plugins for a in _ask(p, "pandoc_args", context)]

    def process_html(self, html: str, context: DocumentContext) -> str:
        for plugin in context.plugins:
            # Plugins written before the hook existed may not have it.
            hook = getattr(plugin, "process_html", None)
            if hook is not None:
                html = hook(html, context)
        return html


def _ask(plugin: object, hook: str, context: DocumentContext) -> Sequence[str]:
    # Plugins written before the hook existed may not have it.
    method = getattr(plugin, hook, None)
    return tuple(method(context)) if method is not None else ()
