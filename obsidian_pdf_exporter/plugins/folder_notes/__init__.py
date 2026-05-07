"""Support for the Obsidian `Folder Notes` plugin.

The plugin lets a folder act as a note: clicking a folder in Obsidian
opens an associated markdown file. This support module reproduces the
default convention (``Folder/Folder.md``) at export time so the file is
treated as the folder's page in the assembled PDF.
"""

from obsidian_pdf_exporter.plugins.folder_notes.plugin import FolderNotesPlugin

__all__ = ["FolderNotesPlugin"]
