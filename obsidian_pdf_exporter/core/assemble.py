"""Assemble a tree of pages into a single markdown document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.pipeline import run_markdown
from obsidian_pdf_exporter.core.steps import core_steps
from obsidian_pdf_exporter.core.steps.base import PageContext

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence
    from pathlib import Path

    from obsidian_pdf_exporter.core.steps.base import Step
    from obsidian_pdf_exporter.core.tree import PageNode
    from obsidian_pdf_exporter.core.vault_index import VaultIndex
    from obsidian_pdf_exporter.plugins import ObsidianPlugin


def process_page(
    node: PageNode,
    page_index: dict,
    build_dir: Path,
    vault_root: Path | None = None,
    *,
    plugins: list[ObsidianPlugin] | None = None,
    plugin_options: dict[str, str] | None = None,
    vault_index: VaultIndex | None = None,
    log: Callable[[str], None] | None = None,
    steps: Sequence[Step] | None = None,
) -> str:
    """Read a single page and run the markdown hook of every step on it.

    ``steps`` defaults to :func:`~obsidian_pdf_exporter.core.steps.core_steps`.
    Obsidian-plugin support modules (Dataview, Meta Bind, …) run inside
    the ``plugins`` step, right after the frontmatter is parsed.
    """
    if node.md_file is None or not node.md_file.exists():
        return ""

    steps = list(steps) if steps is not None else core_steps()
    content = node.md_file.read_text(encoding="utf-8", errors="replace")
    context = PageContext(
        vault_root=vault_root,
        page_folder=node.md_file.parent,
        options=dict(plugin_options or {}),
        vault_index=vault_index,
        source_file=node.md_file,
        node=node,
        page_index=page_index,
        build_dir=build_dir,
        plugins=plugins,
        steps=steps,
        log=log,
    )
    return run_markdown(content, context, steps).strip()


def assemble_document(
    root: PageNode,
    page_index: dict,
    build_dir: Path,
    vault_root: Path | None = None,
    *,
    plugins: list[ObsidianPlugin] | None = None,
    plugin_options: dict[str, str] | None = None,
    vault_index: VaultIndex | None = None,
    log: Callable[[str], None] | None = None,
    steps: Sequence[Step] | None = None,
) -> str:
    """Recursively concatenate every page into one markdown blob."""
    steps = list(steps) if steps is not None else core_steps()
    parts: list[str] = []

    if root.depth > 0:
        heading_level = min(root.depth, 6)
        marker = "#" * heading_level
        parts.append(f"{marker} {root.name} {{#{root.anchor}}}")

    content = process_page(
        root,
        page_index,
        build_dir,
        vault_root,
        plugins=plugins,
        plugin_options=plugin_options,
        vault_index=vault_index,
        log=log,
        steps=steps,
    )
    if content:
        parts.append(content)

    for child in root.children:
        child_content = assemble_document(
            child,
            page_index,
            build_dir,
            vault_root,
            plugins=plugins,
            plugin_options=plugin_options,
            vault_index=vault_index,
            log=log,
            steps=steps,
        )
        if child_content:
            parts.append(child_content)

    return "\n\n".join(parts)
