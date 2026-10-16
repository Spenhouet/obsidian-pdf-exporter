"""Tests for the warnings about content the export cannot render."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.steps.code_blocks import plugin_code_blocks
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.core.wiki_links import convert_wiki_links
from obsidian_pdf_exporter.plugins import active_plugins

if TYPE_CHECKING:
    from pathlib import Path


def _export_page(vault: Path, text: str) -> tuple[str, list[str]]:
    page = vault / "Page.md"
    page.write_text(text, encoding="utf-8")
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    node = PageNode(folder=vault, name="Page", md_file=page, depth=1)
    out = process_page(
        node,
        {},
        build,
        vault,
        plugins=active_plugins(),
        vault_index=VaultIndex(vault),
        log=messages.append,
    )
    return out, messages


def test_plugin_code_blocks_finds_plugin_languages_only() -> None:
    text = (
        "```python\nprint('tasks')\n```\n\n"
        "```tasks\nnot done\n```\n\n"
        "~~~ad-note\ntitle: x\n~~~\n\n"
        "````markdown\n```dataviewjs\ndv.list()\n```\n````\n"
    )
    assert plugin_code_blocks(text) == ["tasks", "ad-note"]


def test_plugin_code_block_is_kept_and_warned(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    out, messages = _export_page(vault, "Text.\n\n```tasks\nnot done\n```\n")
    assert "```tasks" in out
    assert messages == ["  Warning: cannot render the tasks code block in Page.md, kept as code"]


def test_ordinary_code_blocks_do_not_warn(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _, messages = _export_page(vault, "```python\nx = 1\n```\n\n```\nplain\n```\n")
    assert messages == []


def test_canvas_embed_warns_and_becomes_text(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Board.canvas").write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    out, messages = _export_page(vault, "See:\n\n![[Board.canvas]]\n")
    assert "*Board*" in out
    assert len(messages) == 1
    assert messages[0].startswith("  Warning: cannot render embed ![[Board.canvas]] (.canvas")
    assert "in Page.md" in messages[0]


def test_missing_image_warns(tmp_path: Path) -> None:
    messages: list[str] = []
    out = convert_wiki_links("![[gone.png]]", tmp_path, {}, tmp_path, warn=messages.append)
    assert out == "*[Image: gone.png]*"
    assert messages == ["could not find image ![[gone.png]]"]


def test_dataviewjs_placeholder_warns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    out, messages = _export_page(vault, "```dataviewjs\ndv.list([1])\n```\n")
    assert "not supported" in out
    assert any("DataviewJS" in m for m in messages)
