"""Base class and per-page context for Obsidian plugin support modules."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex


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


class ObsidianPlugin:
    """Base class for an Obsidian-plugin support module.

    A subclass declares its identifier in :attr:`name`, and its position in
    the pipeline in :attr:`priority` (lower runs earlier). It then overrides
    one or both of:

    - :meth:`find_folder_note` — claim a markdown file as the page that
      represents a folder. Used during tree building. The Folder Notes
      plugin uses this to map ``Folder/Folder.md`` onto its containing
      folder.
    - :meth:`process_markdown` — transform the markdown content of a
      single page after frontmatter has been stripped.

    Plugins are discovered via the
    ``obsidian_pdf_exporter.obsidian_plugins`` entry point group; see
    :mod:`obsidian_pdf_exporter.plugins.registry` for details.
    """

    #: Identifier shown in ``list-plugins`` and used by ``--disable-plugin``.
    name: str = "plugin"

    #: One-line description shown by ``list-plugins``.
    description: str = ""

    #: Pipeline priority. Lower values run earlier. Built-in plugins use
    #: 5 (Folder Notes), 10 (Dataview), 20 (Meta Bind); third-party
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
