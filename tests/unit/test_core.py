"""Unit tests for the core conversion helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.code import code_mask
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.exporter import _prepend_metadata
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.heading_links import mark_same_page_links
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


def test_slugify_keeps_letters_of_other_scripts() -> None:
    assert slugify("中文 日本語") == "中文-日本語"
    assert slugify("مستند") == "مستند"
    # Vowel signs are marks, which pandoc leaves out of heading ids too.
    assert slugify("देवनागरी") == "दवनगर"
    # Text with ASCII letters keeps the ASCII slug.
    assert slugify("Notes 笔记") == "notes"
    assert slugify("🚀") == ""


def test_page_without_slug_gets_an_anchor(tmp_path: Path) -> None:
    from obsidian_pdf_exporter.core.tree import PageNode

    assert PageNode(folder=tmp_path, name="🚀").anchor == "page"
    assert PageNode(folder=tmp_path, name="مستند").anchor == "مستند"


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


def test_code_span_pattern_finds_the_spans_of_the_lookbehind_form() -> None:
    """The pattern finds the same code spans as the form that starts with the lookbehind."""
    import itertools
    import re

    from obsidian_pdf_exporter.core.code import RE_CODE_SPAN
    from obsidian_pdf_exporter.core.code import mask_code_spans

    reference = re.compile(r"(?<![`\\])(`+)(?!`)((?:[^\n]|\n(?![ \t]*\n))+?)(?<!`)\1(?!`)")
    pieces = ["`", "``", "```", "\\`", "a", " ", "\n", "\n\n", "\n \t\n", "x`y", "\\"]
    texts = ["".join(p) for n in range(1, 6) for p in itertools.product(pieces, repeat=n)]
    texts.append("".join(texts[::7]))
    for text in texts:
        new = [(m.span(), m.groups()) for m in RE_CODE_SPAN.finditer(text)]
        old = [(m.span(), m.groups()) for m in reference.finditer(text)]
        assert new == old, text
    masked, spans = mask_code_spans(texts[-1])
    assert spans == [m.group(0) for m in reference.finditer(texts[-1])]
    assert masked != texts[-1]


#: Code blocks that show another fenced block as an example. Every line is code.
NESTED_FENCES = [
    "````markdown\n```mermaid\n# a\n```\n````",
    "~~~~markdown\n~~~mermaid\n# a\n~~~\n~~~~",
    "`````text\n````markdown\n```mermaid\n# a\n```\n````\n`````",
    "~~~text\n```mermaid\n# a\n```\n~~~",
    "```text\n~~~mermaid\n# a\n~~~\n```",
    "```text\n```mermaid\n# a\n```",
]


@pytest.mark.parametrize("block", NESTED_FENCES)
def test_code_mask_keeps_nested_fences_inside_the_outer_block(block: str) -> None:
    lines = f"{block}\n# after".split("\n")
    assert code_mask(lines) == [True] * (len(lines) - 1) + [False]


def test_code_mask_closes_only_on_a_bare_fence_as_long_as_the_opening_one() -> None:
    lines = ["````", "```", "```` x", "~~~~", "`````  ", "# after"]
    assert code_mask(lines) == [True, True, True, True, True, False]


def test_code_mask_does_not_open_on_a_code_span() -> None:
    assert code_mask(["```a` b```", "# text"]) == [False, False]


@pytest.mark.parametrize("block", NESTED_FENCES)
def test_outside_code_leaves_nested_fences_alone(block: str) -> None:
    out = outside_code(f"{block}\n# after", lambda text: text.replace("#", "!"))
    assert out == f"{block}\n! after"


@pytest.mark.parametrize("block", NESTED_FENCES)
def test_offset_headings_skips_nested_fences(block: str) -> None:
    assert offset_headings(f"{block}\n# after", 1) == f"{block}\n## after"


def test_convert_callouts_leaves_nested_fences_alone() -> None:
    src = "````markdown\n```\n> [!note]\n> text\n```\n````\n"
    assert convert_callouts(src) == src


def test_heading_links_leave_nested_fences_alone() -> None:
    src = "````markdown\n```\n[[#Intro]]\n```\n````"
    assert mark_same_page_links(src, "") == src
