"""Loops that run the steps of the core syntax layer at each stage.

The stages, in the order an export runs them:

1. :func:`run_markdown` on every page (and embedded note).
2. :func:`run_document` on the assembled markdown.
3. pandoc, with the dialect from :func:`markdown_dialect`.
4. :func:`run_html` on the HTML pandoc wrote.

Templates get their ``process_markdown`` and ``process_html`` hooks after
stages 2 and 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.dialect import Dialect

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.steps.base import DocumentContext
    from obsidian_pdf_exporter.core.steps.base import PageContext
    from obsidian_pdf_exporter.core.steps.base import Step


def _by_priority(steps: Sequence[Step]) -> list[Step]:
    return sorted(steps, key=lambda s: s.priority)


def _by_html_order(steps: Sequence[Step]) -> list[Step]:
    return sorted(steps, key=lambda s: s.html_order)


def run_markdown(content: str, context: PageContext, steps: Sequence[Step]) -> str:
    """Run every step's ``process_markdown`` on one page, in priority order."""
    for step in _by_priority(steps):
        content = step.process_markdown(content, context)
    return content


def run_document(markdown: str, context: DocumentContext, steps: Sequence[Step]) -> str:
    """Run every step's ``process_document`` on the assembled markdown."""
    for step in _by_priority(steps):
        markdown = step.process_document(markdown, context)
    return markdown


def run_html(html: str, context: DocumentContext, steps: Sequence[Step]) -> str:
    """Run every step's ``process_html`` in HTML order."""
    for step in _by_html_order(steps):
        html = step.process_html(html, context)
    return html


def markdown_dialect(context: DocumentContext, steps: Sequence[Step]) -> Dialect:
    """Build the pandoc dialect: the base plus what each step needs."""
    dialect = Dialect()
    for step in _by_priority(steps):
        dialect = dialect.extend(step.reader_extensions(context), step.pandoc_args(context))
    return dialect
