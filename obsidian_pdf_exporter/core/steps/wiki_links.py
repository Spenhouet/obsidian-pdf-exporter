"""Wiki links (``[[Note]]``), image embeds (``![[image.png|300]]``) and ``[[X] text](url)``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step
from obsidian_pdf_exporter.core.wiki_links import convert_wiki_links
from obsidian_pdf_exporter.core.wiki_links import normalize_bracket_links

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext


class WikiLinksStep(Step):
    """Resolve wiki links to page anchors and copy embedded images to the build folder."""

    name = "wiki_links"
    description = "Convert [[links]] and ![[image]] embeds"
    priority = 90
    embedded = True

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.build_dir is None:
            return content
        return convert_wiki_links(
            content,
            context.page_folder,
            context.page_index,
            context.build_dir,
            context.vault_index,
            warn=lambda message: context.warn(f"{message} in {context.where}"),
        )


class BracketLinksStep(Step):
    """Keep pandoc from reading ``[[X] text](url)`` as a reference link."""

    name = "bracket_links"
    description = "Protect [[X] text](url) links from pandoc"
    priority = 100

    def process_markdown(self, content: str, context: PageContext) -> str:
        return normalize_bracket_links(content)
