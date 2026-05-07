"""Whole-vault file index for cross-page lookups.

Built once per export. Replaces ad-hoc walks (image resolution,
Dataview FROM clauses, tree pruning) so every step shares the same
filtered view of the vault and lookups are O(1) by name.

Lookups pick the file *closest* to the page that referenced it: the
file whose folder shares the deepest common ancestor with the page
folder, falling back to the shorter overall path on ties. This makes
a per-chapter ``images/foo.png`` win over a top-level ``foo.png``
without any naming convention beyond "files live somewhere in the
vault".
"""

from __future__ import annotations

import os
from pathlib import Path

_SKIP_DIRS = frozenset({".git", ".obsidian", ".vscode", ".trash"})


class VaultIndex:
    """Index every non-hidden file under ``root`` by name and stem."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._by_name: dict[str, list[Path]] = {}
        self._by_stem: dict[str, list[Path]] = {}
        self._md_files: list[Path] = []
        self._md_folders: set[Path] = {self.root}
        self._build()

    def _build(self) -> None:
        for dirpath_str, dirnames, filenames in os.walk(self.root):
            dirpath = Path(dirpath_str)
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS
            )
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                full = dirpath / filename
                self._by_name.setdefault(filename.lower(), []).append(full)
                stem = full.stem.lower()
                if stem and stem != filename.lower():
                    self._by_stem.setdefault(stem, []).append(full)
                if full.suffix.lower() == ".md":
                    self._md_files.append(full)
                    cur = dirpath
                    while cur not in self._md_folders:
                        self._md_folders.add(cur)
                        if cur == self.root:
                            break
                        cur = cur.parent

    def md_files(self) -> list[Path]:
        """Return every indexed markdown file."""
        return list(self._md_files)

    def folder_has_markdown(self, folder: Path) -> bool:
        """True if ``folder`` (or any descendant) contains a markdown file."""
        return folder.resolve() in self._md_folders

    def find_closest(self, name: str, from_folder: Path) -> Path | None:
        """Return the file closest in the tree to ``from_folder``.

        ``name`` may be a full filename (``img.png``) or a bare stem
        (``Page``); both are matched case-insensitively. Returns None
        if no candidate is indexed.
        """
        key = name.lower()
        candidates: list[Path] = list(self._by_name.get(key, []))
        if "." not in name:
            for path in self._by_stem.get(key, []):
                if path not in candidates:
                    candidates.append(path)
        if not candidates:
            return None
        from_resolved = from_folder.resolve()
        return min(candidates, key=lambda p: _proximity_key(p, from_resolved))

    def find_closest_markdown(self, stem: str, from_folder: Path) -> Path | None:
        """Like :meth:`find_closest` but restricted to ``.md`` files."""
        key = stem.lower()
        candidates = list(self._by_name.get(key + ".md", []))
        for path in self._by_stem.get(key, []):
            if path.suffix.lower() == ".md" and path not in candidates:
                candidates.append(path)
        if not candidates:
            return None
        from_resolved = from_folder.resolve()
        return min(candidates, key=lambda p: _proximity_key(p, from_resolved))


def _proximity_key(file_path: Path, from_folder: Path) -> tuple[int, int, str]:
    """Sort key: tree distance from ``from_folder``, then path length, then name."""
    file_parent_parts = file_path.parent.parts
    from_parts = from_folder.parts
    common = 0
    for a, b in zip(file_parent_parts, from_parts, strict=False):
        if a != b:
            break
        common += 1
    distance = (len(file_parent_parts) - common) + (len(from_parts) - common)
    return (distance, len(file_path.parts), str(file_path).lower())
