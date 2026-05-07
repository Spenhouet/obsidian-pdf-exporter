"""Assemble a tree of pages into a single markdown document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_html_comments
from obsidian_pdf_exporter.core.headings import offset_headings
from obsidian_pdf_exporter.core.headings import strip_title_heading
from obsidian_pdf_exporter.core.wiki_links import convert_wiki_links
from obsidian_pdf_exporter.core.wiki_links import normalize_bracket_links
from obsidian_pdf_exporter.core.wiki_links import promote_image_captions
from obsidian_pdf_exporter.plugins import PluginContext

if TYPE_CHECKING:
    from pathlib import Path

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
) -> str:
    """Read and pre-process a single page's markdown content.

    Obsidian-plugin support modules (Dataview, Meta Bind, …) run between
    frontmatter parsing and the rest of the markdown transforms; the
    pipeline calls ``process_markdown`` on every plugin in priority order.
    """
    if node.md_file is None or not node.md_file.exists():
        return ""

    content = node.md_file.read_text(encoding="utf-8", errors="replace")

    fm = parse_frontmatter(content)
    content = strip_frontmatter(content)

    if plugins:
        ctx = PluginContext(
            vault_root=vault_root,
            page_folder=node.md_file.parent,
            frontmatter=fm,
            options=dict(plugin_options or {}),
            vault_index=vault_index,
        )
        for plugin in plugins:
            content = plugin.process_markdown(content, ctx)

    content = strip_html_comments(content)
    content = convert_callouts(content)
    content = convert_wiki_links(
        content, node.md_file.parent, page_index, build_dir, vault_index
    )
    content = normalize_bracket_links(content)
    content = promote_image_captions(content)
    content = strip_title_heading(content, node.name)

    heading_offset = max(node.depth - 1, 0)
    content = offset_headings(content, heading_offset)

    return content.strip()


def assemble_document(
    root: PageNode,
    page_index: dict,
    build_dir: Path,
    vault_root: Path | None = None,
    *,
    plugins: list[ObsidianPlugin] | None = None,
    plugin_options: dict[str, str] | None = None,
    vault_index: VaultIndex | None = None,
) -> str:
    """Recursively concatenate every page into one markdown blob."""
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
        )
        if child_content:
            parts.append(child_content)

    return "\n\n".join(parts)
