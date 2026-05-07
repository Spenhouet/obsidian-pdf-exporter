"""Obsidian plugin registry + pipeline integration tests."""

from __future__ import annotations

from pathlib import Path

from obsidian_pdf_exporter.core.tree import build_space_tree
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
