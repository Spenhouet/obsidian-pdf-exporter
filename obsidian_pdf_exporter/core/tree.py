"""Build a hierarchical page tree from a folder layout.

Folder-to-note resolution is plugin-driven: the tree builder asks every
active :class:`~obsidian_pdf_exporter.plugins.ObsidianPlugin` (in
priority order) which markdown file represents a given folder. The
default Obsidian convention (``Folder/Folder.md``) is provided by
:mod:`obsidian_pdf_exporter.plugins.folder_notes`. Other conventions
(``README.md``, ``index.md``, …) belong in their own plugin packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.util import slugify

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex
    from obsidian_pdf_exporter.plugins import ObsidianPlugin


def _is_page_folder(folder: Path, vault_index: VaultIndex | None) -> bool:
    """Skip dotfiles and (when an index is available) folders without markdown."""
    if folder.name.startswith("."):
        return False
    if vault_index is None:
        return True
    return vault_index.folder_has_markdown(folder)


@dataclass
class PageNode:
    """A folder + its folder note + its child folders."""

    folder: Path
    name: str
    depth: int = 0
    md_file: Path | None = None
    children: list[PageNode] = field(default_factory=list)
    anchor: str = ""

    def __post_init__(self) -> None:
        if not self.anchor:
            self.anchor = slugify(self.name)


def resolve_folder_note(folder: Path, plugins: list[ObsidianPlugin] | None = None) -> Path | None:
    """Ask each plugin in turn which markdown file represents ``folder``.

    Returns the first non-None result. ``plugins`` is expected to be
    pre-sorted by priority — the helper does no sorting itself so the
    caller controls precedence.
    """
    for plugin in plugins or ():
        note = plugin.find_folder_note(folder)
        if note is not None:
            return note
    return None


def build_tree(
    folder: Path,
    depth: int = 0,
    *,
    plugins: list[ObsidianPlugin] | None = None,
    vault_index: VaultIndex | None = None,
) -> PageNode | None:
    """Recursively build a :class:`PageNode` tree rooted at ``folder``."""
    if not folder.is_dir():
        return None

    node = PageNode(folder=folder, name=folder.name, depth=depth)
    node.md_file = resolve_folder_note(folder, plugins)

    child_folders = sorted(
        (f for f in folder.iterdir() if f.is_dir() and _is_page_folder(f, vault_index)),
        key=lambda f: f.name.lower(),
    )

    for child_folder in child_folders:
        child = build_tree(child_folder, depth + 1, plugins=plugins, vault_index=vault_index)
        if child is not None:
            node.children.append(child)

    return node


def build_space_tree(
    space_folder: Path,
    *,
    plugins: list[ObsidianPlugin] | None = None,
    vault_index: VaultIndex | None = None,
) -> PageNode | None:
    """Build a tree for a documentation space.

    Three layouts are supported:

    1. Plugins map a markdown file onto ``space_folder`` itself — that
       file becomes the space root note.
    2. Plugins map a file onto ``space_folder/space_folder.name`` (the
       Obsidian "vault root" convention) — the inner folder is treated as
       the root and its sibling folders become its children.
    3. Neither — an anonymous root with the immediate child folders.
    """
    space_name = space_folder.name
    space_note = resolve_folder_note(space_folder, plugins)

    if space_note:
        node = PageNode(folder=space_folder, name=space_name, depth=0)
        node.md_file = space_note
        node.children = _direct_children(space_folder, plugins=plugins, vault_index=vault_index)
        return node

    inner = space_folder / space_name
    if inner.exists() and inner.is_dir():
        inner_note = resolve_folder_note(inner, plugins)
        if inner_note:
            node = PageNode(folder=inner, name=space_name, depth=0)
            node.md_file = inner_note
            node.children = _direct_children(
                space_folder,
                exclude={space_name},
                plugins=plugins,
                vault_index=vault_index,
            )
            return node

    node = PageNode(folder=space_folder, name=space_name, depth=0)
    node.children = _direct_children(space_folder, plugins=plugins, vault_index=vault_index)
    return node


def _direct_children(
    folder: Path,
    *,
    exclude: frozenset[str] | set[str] | None = None,
    plugins: list[ObsidianPlugin] | None = None,
    vault_index: VaultIndex | None = None,
) -> list[PageNode]:
    excluded = set(exclude or ())
    out: list[PageNode] = []
    child_folders = sorted(
        (
            f
            for f in folder.iterdir()
            if f.is_dir() and f.name not in excluded and _is_page_folder(f, vault_index)
        ),
        key=lambda f: f.name.lower(),
    )
    for child_folder in child_folders:
        child = build_tree(child_folder, 1, plugins=plugins, vault_index=vault_index)
        if child is not None:
            out.append(child)
    return out


def collect_page_index(node: PageNode, index: dict | None = None) -> dict:
    """Build a name → ``[{anchor, node}, ...]`` map for wiki link resolution.

    A vault may contain several folders with the same name; each
    candidate is appended in tree order so callers can pick the one
    closest to the referencing page (see :func:`lookup_page`).
    """
    if index is None:
        index = {}
    index.setdefault(node.name, []).append({"anchor": node.anchor, "node": node})
    for child in node.children:
        collect_page_index(child, index)
    return index


def lookup_page(page_index: dict, name: str, from_folder: Path | None = None) -> dict | None:
    """Return the page entry whose folder is closest to ``from_folder``.

    With no ``from_folder`` (or only one candidate) returns the first
    entry. Falls back to None when ``name`` is unindexed.
    """
    entries = page_index.get(name)
    if not entries:
        return None
    if from_folder is None or len(entries) == 1:
        return entries[0]
    from_parts = from_folder.resolve().parts
    return min(entries, key=lambda e: _entry_distance(e["node"].folder, from_parts))


def _entry_distance(folder: Path, from_parts: tuple[str, ...]) -> tuple[int, int]:
    folder_parts = folder.resolve().parts
    common = 0
    for a, b in zip(folder_parts, from_parts, strict=False):
        if a != b:
            break
        common += 1
    distance = (len(folder_parts) - common) + (len(from_parts) - common)
    return (distance, len(folder_parts))
