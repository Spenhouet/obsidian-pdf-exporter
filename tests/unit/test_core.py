"""Unit tests for the core conversion helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.exporter import _prepend_metadata
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.headings import offset_headings
from obsidian_pdf_exporter.core.headings import strip_title_heading
from obsidian_pdf_exporter.core.util import git_root
from obsidian_pdf_exporter.core.util import is_git_repo
from obsidian_pdf_exporter.core.util import safe_filename
from obsidian_pdf_exporter.core.util import slugify
from obsidian_pdf_exporter.core.util import vault_root

if TYPE_CHECKING:
    from pathlib import Path


def test_slugify_basic() -> None:
    assert slugify("Hello World") == "hello-world"
    # Non-ASCII characters that don't decompose to ASCII (ß) are dropped.
    assert slugify("Schöne Grüße!") == "schone-grue"
    assert slugify("  Multi   Space  ") == "multi-space"


def test_safe_filename_strips_punctuation() -> None:
    assert safe_filename("My Doc: v1.0") == "My_Doc_v10"
    assert safe_filename("") == "export"


def test_strip_frontmatter_removes_block() -> None:
    src = "---\ntitle: foo\n---\n\nbody\n"
    assert strip_frontmatter(src) == "body\n"


def test_parse_frontmatter_returns_dict() -> None:
    src = "---\ntitle: foo\ntags:\n  - a\n  - b\n---\n\nbody\n"
    fm = parse_frontmatter(src)
    assert fm["title"] == "foo"
    assert fm["tags"] == ["a", "b"]


def test_offset_headings_skips_code_blocks() -> None:
    src = "# Title\n```\n# not a heading\n```\n## Sub\n"
    out = offset_headings(src, 2)
    assert "### Title" in out
    assert "# not a heading" in out  # untouched inside fence
    assert "#### Sub" in out


def test_strip_title_heading_drops_matching_first_heading() -> None:
    src = "# Page\n\nrest\n"
    assert strip_title_heading(src, "Page") == "rest\n"


def test_convert_callouts_emits_fenced_div() -> None:
    src = "> [!note] Heads up\n> Body line.\n"
    out = convert_callouts(src)
    assert ".callout-note" in out
    assert "Heads up" in out
    assert "Body line." in out


def test_vault_root_prefers_obsidian_marker(tmp_path: Path) -> None:
    vault = tmp_path / "MyVault"
    space = vault / "Space"
    space.mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    assert vault_root(space) == vault


def test_vault_root_falls_back_to_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    space = repo / "Space"
    space.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert vault_root(space) == repo


def test_vault_root_obsidian_wins_over_git(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    vault = outer / "vault"
    space = vault / "Space"
    space.mkdir(parents=True)
    (outer / ".git").mkdir()
    (vault / ".obsidian").mkdir()
    assert vault_root(space) == vault


def test_vault_root_no_markers_returns_start(tmp_path: Path) -> None:
    space = tmp_path / "loose"
    space.mkdir()
    assert vault_root(space) == space


def test_is_git_repo_true_when_git_dir_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert is_git_repo(nested)


def test_is_git_repo_false_without_git_dir(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    folder.mkdir()
    assert not is_git_repo(folder)


def test_git_root_raises_outside_repo(tmp_path: Path) -> None:
    folder = tmp_path / "loose"
    folder.mkdir()
    try:
        git_root(folder)
    except ValueError:
        return
    msg = "git_root should raise ValueError outside a git repo"
    raise AssertionError(msg)


def test_git_root_returns_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert git_root(nested) == repo


def test_prepend_metadata_label_with_date() -> None:
    out = _prepend_metadata("body\n", "T", "", "abc1234", "2026-05-07")
    assert out.startswith("% T\n% abc1234 | 2026-05-07\n\n")


def test_prepend_metadata_label_with_subtitle_and_date() -> None:
    out = _prepend_metadata("body\n", "T", "Sub", "v1", "2026-05-07")
    assert out.startswith("% T\n% Sub\n% v1 | 2026-05-07\n\n")


def test_prepend_metadata_no_label_falls_back_to_date() -> None:
    out = _prepend_metadata("body\n", "T", "", "", "2026-05-07")
    assert out.startswith("% T\n% 2026-05-07\n\n")


def test_prepend_metadata_label_without_date() -> None:
    out = _prepend_metadata("body\n", "T", "", "abc1234", "")
    assert out.startswith("% T\n% abc1234\n\n")


def test_prepend_metadata_only_title() -> None:
    out = _prepend_metadata("body\n", "T", "", "", "")
    assert out.startswith("% T\n\n")
