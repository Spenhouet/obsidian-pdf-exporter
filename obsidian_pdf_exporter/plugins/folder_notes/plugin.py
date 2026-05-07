"""Folder Notes plugin: maps ``Folder/Folder.md`` onto its containing folder.

This is the default convention shipped by the Obsidian Folder Notes
plugin. Other conventions (``README.md`` inside the folder, an
``index.md`` file, a frontmatter-marked file …) can be implemented as
sibling plugins that override :meth:`find_folder_note` and pick a higher
priority value to take precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.plugins.base import ObsidianPlugin

if TYPE_CHECKING:
    from pathlib import Path


class FolderNotesPlugin(ObsidianPlugin):
    """Treat ``Folder/Folder.md`` as the folder's page during tree building."""

    name = "folder_notes"
    description = "Treat Folder/Folder.md as the folder's page"
    # Tree building runs before markdown processing; pick a small value so
    # this plugin gets first claim on a folder's note.
    priority = 5

    def find_folder_note(self, folder: Path) -> Path | None:
        candidate = folder / f"{folder.name}.md"
        return candidate if candidate.is_file() else None
