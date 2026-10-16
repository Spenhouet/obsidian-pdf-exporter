"""The :class:`Step` interface and the per-page context of the core syntax layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.plugins.base import DocumentContext
from obsidian_pdf_exporter.plugins.base import PluginContext

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.tree import PageNode
    from obsidian_pdf_exporter.plugins.base import ObsidianPlugin

__all__ = ["DocumentContext", "PageContext", "Step"]

_log = logging.getLogger(__name__)


@dataclass
class PageContext(PluginContext):
    """Context for the markdown hook of a step, for one page or embedded note.

    It extends :class:`PluginContext`, so plugins get the same object.

    Attributes:
        source_file: Markdown file the content comes from.
        node: Page of the export tree. ``None`` for embedded notes.
        page_index: Page lookup table built from the export tree.
        build_dir: Folder that holds the intermediate files and images.
        plugins: Active plugins, in priority order.
        steps: Active steps, in priority order. Embeds run the steps
            marked :attr:`Step.embedded` on the embedded content.
        embed_stack: Notes and fragments that are being embedded right now,
            used to stop cycles.
        log: Callable that prints a progress or warning line.
    """

    vault_root: Path | None = None
    page_folder: Path = field(default_factory=Path)
    frontmatter: dict = field(default_factory=dict)
    source_file: Path | None = None
    node: PageNode | None = None
    page_index: dict = field(default_factory=dict)
    build_dir: Path | None = None
    plugins: list[ObsidianPlugin] | None = None
    steps: Sequence[Step] | None = None
    embed_stack: tuple[tuple[Path, str], ...] = ()
    log: Callable[[str], None] | None = None

    @property
    def where(self) -> str:
        """The source file as a vault path, for messages."""
        if self.source_file is None:
            return "the page"
        if self.vault_root is not None:
            try:
                return self.source_file.resolve().relative_to(self.vault_root.resolve()).as_posix()
            except ValueError:
                pass
        return self.source_file.name

    def warn(self, message: str) -> None:
        """Report a problem through ``log`` or the module logger."""
        if self.log is not None:
            self.log(f"  Warning: {message}")
        else:
            _log.warning(message)


class Step:
    """One piece of Obsidian syntax, handled at one or more pipeline stages.

    A step overrides the hooks it needs. All of them are optional:

    - :meth:`process_markdown` runs on the markdown of every page, in
      :attr:`priority` order.
    - :meth:`process_document` runs on the assembled markdown of the whole
      document, in :attr:`priority` order, before the template hook.
    - :meth:`process_html` runs on the HTML that pandoc wrote, in
      :attr:`html_priority` order, before the template hook.
    - :meth:`reader_extensions` and :meth:`pandoc_args` add what the step
      needs to the markdown dialect (see :mod:`obsidian_pdf_exporter.core.dialect`).
    """

    #: Identifier, unique among the steps.
    name: str = "step"

    #: One-line description.
    description: str = ""

    #: Order of the markdown and document hooks. Lower runs earlier.
    priority: int = 100

    #: Order of the HTML hook. Lower runs earlier. Defaults to :attr:`priority`.
    html_priority: int | None = None

    #: True when the markdown hook also runs on the content of embedded notes.
    embedded: bool = False

    @property
    def html_order(self) -> int:
        """The order of the HTML hook."""
        return self.priority if self.html_priority is None else self.html_priority

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        """Pandoc reader extensions this step needs, like ``mark``."""
        return ()

    def pandoc_args(self, context: DocumentContext) -> Sequence[str]:
        """Extra pandoc command line arguments this step needs."""
        return ()

    def process_markdown(self, content: str, context: PageContext) -> str:
        """Transform the markdown of one page or embedded note."""
        return content

    def process_document(self, markdown: str, context: DocumentContext) -> str:
        """Transform the assembled markdown of the whole document."""
        return markdown

    def process_html(self, html: str, context: DocumentContext) -> str:
        """Transform the HTML of the whole document."""
        return html

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"
