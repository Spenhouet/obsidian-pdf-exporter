"""Tests for the VaultIndex closest-match lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.vault_index import VaultIndex

if TYPE_CHECKING:
    from pathlib import Path


def _touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_find_closest_prefers_local_attachment_over_top_level(temp_dir: Path) -> None:
    _touch(temp_dir / "logo.png", "global")
    _touch(temp_dir / "Chapter A" / "Chapter A.md", "# A")
    _touch(temp_dir / "Chapter A" / "logo.png", "local")
    _touch(temp_dir / "Chapter B" / "Chapter B.md", "# B")

    index = VaultIndex(temp_dir)

    found = index.find_closest("logo.png", temp_dir / "Chapter A")
    assert found is not None
    assert found.read_text() == "local"

    # From a chapter without a local copy, fall back to the top-level file.
    found_b = index.find_closest("logo.png", temp_dir / "Chapter B")
    assert found_b is not None
    assert found_b.read_text() == "global"


def test_find_closest_ignores_dot_dirs(temp_dir: Path) -> None:
    _touch(temp_dir / ".obsidian" / "logo.png", "obsidian")
    _touch(temp_dir / "img" / "logo.png", "real")
    _touch(temp_dir / "Chapter" / "Chapter.md", "# C")

    index = VaultIndex(temp_dir)

    found = index.find_closest("logo.png", temp_dir / "Chapter")
    assert found is not None
    assert found.read_text() == "real"


def test_folder_has_markdown_skips_attachment_only_dirs(temp_dir: Path) -> None:
    _touch(temp_dir / "attachments" / "img.png")
    _touch(temp_dir / "Chapter" / "Chapter.md", "# C")
    _touch(temp_dir / "Chapter" / "media" / "diagram.png")

    index = VaultIndex(temp_dir)

    assert index.folder_has_markdown(temp_dir / "Chapter") is True
    assert index.folder_has_markdown(temp_dir / "attachments") is False
    # An attachment subfolder of a chapter is not itself a page folder.
    assert index.folder_has_markdown(temp_dir / "Chapter" / "media") is False


def test_find_closest_stem_only_query(temp_dir: Path) -> None:
    _touch(temp_dir / "Page.md", "root")
    _touch(temp_dir / "Sub" / "Page.md", "sub")
    _touch(temp_dir / "Sub" / "Sub.md", "# Sub")

    index = VaultIndex(temp_dir)

    found = index.find_closest("Page", temp_dir / "Sub")
    assert found is not None
    assert found.read_text() == "sub"


def test_md_files_excludes_hidden(temp_dir: Path) -> None:
    _touch(temp_dir / "keep.md", "x")
    _touch(temp_dir / ".hidden" / "skip.md", "y")
    _touch(temp_dir / ".obsidian" / "config.md", "z")

    index = VaultIndex(temp_dir)

    names = sorted(p.name for p in index.md_files())
    assert names == ["keep.md"]
