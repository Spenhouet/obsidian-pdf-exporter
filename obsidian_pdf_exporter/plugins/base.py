"""Base class and per-page context for Obsidian plugin support modules."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex
    from obsidian_pdf_exporter.templates.base import ExportContext
    from obsidian_pdf_exporter.templates.base import Template


@dataclass
class PluginContext:
    """Per-page context passed to every plugin's ``process_markdown`` call.

    Attributes:
        vault_root: Filesystem root used for cross-page lookups (Dataview
            indexing, etc.). May be ``None`` for ad-hoc exports outside a
            git repository.
        page_folder: Folder that contains the page's markdown file. Used by
            plugins that need to resolve relative paths (e.g. attachments).
        frontmatter: Parsed YAML frontmatter dict for the current page.
            Plugins may read but should not mutate this.
        options: Free-form ``key=value`` options forwarded from the CLI's
            repeatable ``--option`` flag.
        vault_index: Pre-built file index for the vault. Plugins should
            prefer this over ad-hoc walks; ``None`` only in unit-test
            contexts that construct a context directly.
    """

    vault_root: Path | None
    page_folder: Path
    frontmatter: dict
    options: dict[str, str] = field(default_factory=dict)
    vault_index: VaultIndex | None = None


@dataclass
class DocumentContext:
    """Context for the stages that work on the whole document.

    Passed to :meth:`ObsidianPlugin.process_html`, :meth:`ObsidianPlugin.process_svg`
    and to the document and HTML hooks of the core steps.

    Attributes:
        build_dir: Folder that holds the intermediate files and images.
        options: Free-form ``key=value`` options from ``--option``.
        root: Folder that is exported. ``None`` in unit tests.
        export: Export metadata (title, version, date, ...) shared with the template.
        template: Template of the export.
        plugins: Active plugins, in priority order.
        redline: True for a redline export.
        log: Callable that prints a progress or warning line.
    """

    build_dir: Path
    options: dict[str, str] = field(default_factory=dict)
    root: Path | None = None
    export: ExportContext | None = None
    template: Template | None = None
    plugins: list[ObsidianPlugin] = field(default_factory=list)
    redline: bool = False
    log: Callable[[str], None] = print


class ObsidianPlugin:
    """Base class for an Obsidian-plugin support module.

    A subclass declares its identifier in :attr:`name`, and its position in
    the pipeline in :attr:`priority` (lower runs earlier). It then overrides
    any of these hooks. All of them are optional:

    - :meth:`find_folder_note` — claim a markdown file as the page that
      represents a folder. Used during tree building. The Folder Notes
      plugin uses this to map ``Folder/Folder.md`` onto its containing
      folder.
    - :meth:`process_markdown` — transform the markdown content of a
      single page (or embedded note) after frontmatter has been stripped.
    - :meth:`extract_block` — resolve a block reference (``![[Note#^id]]``)
      in a way core does not know. The Block Link Plus plugin uses this
      for ``^id-id`` ranges.
    - :meth:`process_document` — transform the assembled markdown of the
      whole document. :meth:`reader_extensions` and :meth:`pandoc_args`
      add what the plugin needs to the pandoc call. The citations plugin
      uses these for ``--citeproc``.
    - :meth:`process_svg` — rewrite an SVG image while it is inlined into
      the HTML. The draw.io plugin uses this.
    - :meth:`process_html` — transform the HTML of the whole document
      after the core HTML steps and before the template.

    Plugins are discovered via the
    ``obsidian_pdf_exporter.obsidian_plugins`` entry point group; see
    :mod:`obsidian_pdf_exporter.plugins.registry` for details.
    """

    #: Identifier shown in ``list-plugins`` and used by ``--disable-plugin``.
    name: str = "plugin"

    #: One-line description shown by ``list-plugins``.
    description: str = ""

    #: Pipeline priority. Lower values run earlier. Built-in plugins use
    #: 5 (Folder Notes), 10 (Dataview), 15 (Excalidraw), 20 (Meta Bind), 30
    #: (Block Link Plus), 40 (draw.io) and 50 (citations); third-party
    #: plugins should leave room around them.
    priority: int = 100

    def find_folder_note(self, folder: Path) -> Path | None:
        """Return the markdown file representing this folder, or None.

        Tree building consults every active plugin in priority order until
        one returns a path. Plugins that do not deal with folder-level
        notes can leave the default no-op implementation in place.
        """
        return None

    def process_markdown(self, content: str, context: PluginContext) -> str:
        """Transform a page's markdown source. Default implementation is a no-op."""
        return content

    def extract_block(self, body: str, block_id: str) -> str | None:
        """Return the text that ``![[Note#^block_id]]`` selects in ``body``, or None.

        Plugins are asked in priority order. The first answer that is not
        None wins. When every plugin returns None, core looks for a block
        that carries ``^block_id``.
        """
        return None

    def process_document(self, markdown: str, context: DocumentContext) -> str:
        """Transform the assembled markdown of the whole document. Default is a no-op.

        Runs after the markdown hook has run on every page, before pandoc.
        """
        return markdown

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        """Pandoc reader extensions this plugin needs. Asked after :meth:`process_document`."""
        return ()

    def pandoc_args(self, context: DocumentContext) -> Sequence[str]:
        """Extra pandoc arguments, like ``--citeproc``. Asked after :meth:`process_document`."""
        return ()

    def process_svg(self, svg: str, context: DocumentContext) -> str:
        """Rewrite an SVG image while it is inlined into the HTML. Default is a no-op."""
        return svg

    def process_html(self, html: str, context: DocumentContext) -> str:
        """Transform the HTML of the whole document. Default implementation is a no-op."""
        return html
