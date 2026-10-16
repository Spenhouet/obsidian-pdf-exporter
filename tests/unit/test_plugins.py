"""Obsidian plugin registry + pipeline integration tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.tree import build_space_tree
from obsidian_pdf_exporter.plugins import DocumentContext
from obsidian_pdf_exporter.plugins import ObsidianPlugin
from obsidian_pdf_exporter.plugins import PluginContext
from obsidian_pdf_exporter.plugins import active_plugins
from obsidian_pdf_exporter.plugins import available_plugins
from obsidian_pdf_exporter.plugins import register_plugin
from obsidian_pdf_exporter.plugins.dataview import DataviewPlugin
from obsidian_pdf_exporter.plugins.folder_notes import FolderNotesPlugin
from obsidian_pdf_exporter.plugins.meta_bind import MetaBindPlugin


def test_builtin_plugins_discoverable() -> None:
    names = available_plugins()
    assert "folder_notes" in names
    assert "dataview" in names
    assert "meta_bind" in names


def test_active_plugins_sorted_by_priority() -> None:
    plugins = active_plugins()
    names = [p.name for p in plugins]
    # folder_notes (5) < dataview (10) < meta_bind (20)
    assert names.index("folder_notes") < names.index("dataview") < names.index("meta_bind")


def test_active_plugins_respects_disabled() -> None:
    enabled = {p.name for p in active_plugins(disabled={"dataview"})}
    assert "dataview" not in enabled
    assert "meta_bind" in enabled


def test_meta_bind_resolves_view_against_frontmatter() -> None:
    plugin = MetaBindPlugin()
    ctx = PluginContext(
        vault_root=None,
        page_folder=Path("/var/empty"),
        frontmatter={"author": "Alex"},
    )
    out = plugin.process_markdown("Hello `VIEW[{author}][text]`!", ctx)
    assert out == "Hello Alex!"


def _meta_bind(content: str, frontmatter: dict) -> str:
    ctx = PluginContext(vault_root=None, page_folder=Path("/var/empty"), frontmatter=frontmatter)
    return MetaBindPlugin().process_markdown(content, ctx)


_LIST_VALUE = "- First **item**.\n- Second [[Note|item]].\n  - Nested item.\n"


def test_meta_bind_multiline_value_in_table_stays_in_cell() -> None:
    row = "| **Items** | `VIEW[{items}][text(renderMarkdown)]` |"
    out = _meta_bind(f"| a | b |\n|---|---|\n{row}\n", {"items": _LIST_VALUE})
    lines = out.split("\n")
    assert len(lines) == 4
    assert lines[2] == (
        '| **Items** | <span class="meta-bind-ul"><span class="meta-bind-li">First **item**.'
        '</span><span class="meta-bind-li">Second [[Note|item]].'
        '<span class="meta-bind-ul"><span class="meta-bind-li">Nested item.'
        "</span></span></span></span> |"
    )


def test_meta_bind_multiline_inline_value_mixes_text_and_lists() -> None:
    value = "Intro line.\nSecond line.\n1. One\n2. Two\n- Other\nAfter."
    out = _meta_bind("Value: `VIEW[{v}][text]` end", {"v": value})
    assert out == (
        "Value: Intro line.<br>Second line."
        '<span class="meta-bind-ol"><span class="meta-bind-li">One</span>'
        '<span class="meta-bind-li">Two</span></span>'
        '<span class="meta-bind-ul"><span class="meta-bind-li">Other</span></span>'
        "After. end"
    )


def test_meta_bind_multiline_value_alone_on_line_keeps_lines() -> None:
    out = _meta_bind("Before.\n\n`VIEW[{items}][text(renderMarkdown)]`\n", {"items": _LIST_VALUE})
    assert out == f"Before.\n\n{_LIST_VALUE.strip()}\n"


def test_meta_bind_leaves_fenced_code_alone() -> None:
    content = "```\n`VIEW[{a}][text]` INPUT[text:a]\n```\n`VIEW[{a}][text]`"
    assert _meta_bind(content, {"a": "x"}) == "```\n`VIEW[{a}][text]` INPUT[text:a]\n```\nx"


def test_meta_bind_list_spans_become_html_lists(tmp_path: Path) -> None:
    html = (
        '<td><span class="meta-bind-ul"><span class="meta-bind-li">a <span class="x">b</span>'
        '<span class="meta-bind-ol"><span class="meta-bind-li">c</span></span>'
        "</span></span></td>"
    )
    out = MetaBindPlugin().process_html(html, DocumentContext(build_dir=tmp_path))
    assert out == '<td><ul><li>a <span class="x">b</span><ol><li>c</li></ol></li></ul></td>'


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_meta_bind_multiline_value_renders_as_list_in_table_cell(tmp_path: Path) -> None:
    row = "| **Items** | `VIEW[{items}][text(renderMarkdown)]` |"
    markdown = _meta_bind(f"| a | b |\n|---|---|\n{row}\n", {"items": "- One **x**\n- Two\n"})
    html = MetaBindPlugin().process_html(
        render_html(markdown, "x.css", "T", tmp_path, toc=False),
        DocumentContext(build_dir=tmp_path),
    )
    assert "<td><ul><li>One <strong>x</strong></li><li>Two</li></ul></td>" in html
    assert "meta-bind-" not in html


def test_dataview_plugin_skips_when_no_vault_root() -> None:
    plugin = DataviewPlugin()
    src = "```dataview\nLIST\nFROM #foo\n```"
    ctx = PluginContext(vault_root=None, page_folder=Path("/var/empty"), frontmatter={})
    assert plugin.process_markdown(src, ctx) == src


def test_folder_notes_finds_matching_md(tmp_path: Path) -> None:
    folder = tmp_path / "Topic"
    folder.mkdir()
    note = folder / "Topic.md"
    note.write_text("body", encoding="utf-8")

    plugin = FolderNotesPlugin()
    assert plugin.find_folder_note(folder) == note


def test_folder_notes_returns_none_when_missing(tmp_path: Path) -> None:
    folder = tmp_path / "Topic"
    folder.mkdir()
    plugin = FolderNotesPlugin()
    assert plugin.find_folder_note(folder) is None


def test_tree_uses_folder_notes_plugin(tmp_path: Path) -> None:
    space = tmp_path / "Space"
    sub = space / "Sub"
    sub.mkdir(parents=True)
    (space / "Space.md").write_text("root", encoding="utf-8")
    (sub / "Sub.md").write_text("child", encoding="utf-8")

    tree_with = build_space_tree(space, plugins=[FolderNotesPlugin()])
    assert tree_with is not None
    assert tree_with.md_file == space / "Space.md"
    assert len(tree_with.children) == 1
    assert tree_with.children[0].md_file == sub / "Sub.md"


def test_tree_without_folder_notes_plugin_has_no_md_file(tmp_path: Path) -> None:
    space = tmp_path / "Space"
    sub = space / "Sub"
    sub.mkdir(parents=True)
    (space / "Space.md").write_text("root", encoding="utf-8")
    (sub / "Sub.md").write_text("child", encoding="utf-8")

    tree_without = build_space_tree(space, plugins=[])
    assert tree_without is not None
    assert tree_without.md_file is None
    assert tree_without.children[0].md_file is None


def test_runtime_register_plugin_round_trip() -> None:
    class _MockPlugin(ObsidianPlugin):
        name = "mock-plugin-test"
        priority = 50

        def process_markdown(self, content: str, context: PluginContext) -> str:
            return content + "\n[mock]"

    register_plugin(_MockPlugin)
    plugins = active_plugins()
    names = [p.name for p in plugins]
    assert "mock-plugin-test" in names
    # Priorities: folder_notes (5), dataview (10), meta_bind (20), mock (50)
    assert names[-1] == "mock-plugin-test"


@pytest.mark.parametrize(
    ("value", "render", "expected"),
    [
        ("2026-03-05", "date(D MMMM YYYY)", "5 March 2026"),
        ("2026-03-05", "date(DD.MM.YYYY)", "05.03.2026"),
        ("2026-03-05", "DATE(D.M.YY)", "5.3.26"),
        ("2026-03-05", "date(MMM D, YYYY)", "Mar 5, 2026"),
        ("2026-11-25", "date(YYYY-MM-DD)", "2026-11-25"),
        ("2026-03-05T07:04:09", "datetime(DD.MM.YYYY HH:mm:ss)", "05.03.2026 07:04:09"),
        ("2026-03-05T07:04:09", "datetime(H:mm)", "7:04"),
        ("2026-03-05", "datetime(HH:mm)", "00:00"),
        ("not a date", "date(YYYY)", "not a date"),
    ],
)
def test_meta_bind_formats_dates(value: str, render: str, expected: str) -> None:
    assert _meta_bind(f"`VIEW[{{d}}][{render}]`", {"d": value}) == expected
