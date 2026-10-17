"""Tests for the redline (tracked-changes) diff."""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.redline import diff_markdown
from obsidian_pdf_exporter.templates import load_template

if TYPE_CHECKING:
    from pathlib import Path

OLD_NOTE = """\
# Results

## Table

Intro paragraph that stays the same.

The table lists the count of items. The comparison shows the decrease and increase of \
items. See [[#Contents]].

<!--
Note for editors: the screenshot below was taken by hand.
-->
![[table.png]]

## Contents

- Fruit
  - Apple
  - Pear
  - Plum
- Vegetables
  - Carrot

**Summary:**
This page shows the number of items and the decrease and increase per group.
"""

NEW_NOTE = """\
# Results

## Table

Intro paragraph that stays the same.

The table lists the count of items. The previous count is shown next to it. The comparison \
shows the large decrease and large increase of items. See [[#Contents]].

<!--
Note for editors: the screenshot below was taken by hand.
-->
![[table.png]]

## Contents

- Fruit
  - Apple
  - Pear
- Vegetables
  - Carrot

**Summary:**
This page shows the number of items and the large decrease and large increase per group.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv in tests
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def two_commit_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository whose child note ``Space/Note/Note.md`` changes between two commits."""
    repo = tmp_path / "vault"
    space = repo / "Space"
    space.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (space / "Space.md").write_text("Overview.\n", encoding="utf-8")
    (space / "Note").mkdir()
    note = space / "Note" / "Note.md"
    note.write_text(OLD_NOTE, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "old")
    note.write_text(NEW_NOTE, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def redline_markdown(two_commit_vault: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run the redline pipeline (minus the PDF step) and return the diffed markdown."""
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = two_commit_vault / "out" / "redline.pdf"
    output.parent.mkdir()
    export_redline(
        RedlineRequest(
            root=two_commit_vault / "Space",
            output=output,
            template=load_template("redline"),
            from_commit="HEAD~1",
            to_commit="HEAD",
            debug=True,
        ),
        log=lambda _msg: None,
    )
    return _plain(
        (output.parent / "_build_redline" / "redline_assembled.md").read_text(encoding="utf-8")
    )


def _plain(md: str) -> str:
    """Remove the block divs of the diff, keep their content."""
    return re.sub(r"::: \{\.rl-block[^}]*\}\n(.*?)\n:::", r"\1", md, flags=re.DOTALL)


def _blocks(md: str) -> list[str]:
    return [b for b in md.split("\n\n") if b.strip()]


def test_changed_paragraph_is_diffed_in_place_once(redline_markdown: str) -> None:
    """A changed paragraph after an unchanged one is shown once, in place, with inline markup."""
    blocks = _blocks(redline_markdown)
    intro = next(i for i, b in enumerate(blocks) if b.startswith("Intro paragraph"))
    changed = blocks[intro + 1]
    assert changed.startswith("The table lists the count of items.")
    assert "<ins>previous count is shown next to it. The</ins> comparison" in changed
    assert "the <ins>large</ins> decrease" in changed
    assert redline_markdown.count("The table lists the count of items.") == 1


def test_deleted_nested_list_item_stays_a_list_item(redline_markdown: str) -> None:
    """A removed nested list item is kept in place as a struck-through list item."""
    assert "  - Pear\n  - <del>Plum</del>\n- Vegetables" in redline_markdown


def test_trailing_edit_after_bold_label_line(redline_markdown: str) -> None:
    """A word edit on the second line of a hard-wrapped paragraph keeps the label line intact."""
    assert (
        "**Summary:**\nThis page shows the number of items and the <ins>large</ins> decrease "
        "and <ins>large</ins> increase per group." in redline_markdown
    )


def test_diff_markdown_keeps_alignment_after_heading_anchor() -> None:
    """Heading anchors must not merge the heading with the next block during the diff."""
    old = "# Title {#title}\n\nSame.\n\nOld words here.\n\nTail."
    new = "# Title {#title}\n\nSame.\n\nNew words here.\n\nTail."
    out = _plain(diff_markdown(old, new))
    assert _blocks(out) == [
        "# Title {#title}",
        "Same.",
        "<del>Old</del><ins>New</ins> words here.",
        "Tail.",
    ]


def test_word_diff_keeps_spaces_around_markup() -> None:
    """Inserted and deleted words keep the spaces that separate them from their neighbours."""
    assert _plain(diff_markdown("a b c", "a x b c")) == "a <ins>x</ins> b c"
    assert _plain(diff_markdown("a b c", "a c")) == "a <del>b</del> c"


def test_inserted_and_deleted_list_items_keep_markers() -> None:
    """List markers and quote prefixes stay outside the inline markup."""
    old = "> - one\n> - two\n\n1. first\n2. second"
    new = "> - one\n> - two\n> - three\n\n1. first"
    out = _plain(diff_markdown(old, new))
    assert "> - two\n> - <ins>three</ins>" in out
    assert "1. first\n2. <del>second</del>" in out


def test_rewrapped_paragraph_is_not_a_change() -> None:
    """Only the line breaks of a paragraph changed: it passes through unmarked."""
    out = diff_markdown("one two three\nfour five", "one two\nthree four five")
    assert "<ins>" not in out
    assert "<del>" not in out
    assert "rl-block" not in out


def test_moved_paragraph_is_marked_at_both_ends() -> None:
    """A paragraph deleted in one place and inserted in another is a move."""
    para = "This paragraph is long enough to be detected as a moved block of text."
    out = diff_markdown(f"# A\n\n{para}\n\n# B\n\nStay.", f"# A\n\n# B\n\nStay.\n\n{para}")
    assert 'rl-move-from data-rl-kind="para" data-rl-move="1"' in out
    assert 'rl-move-to data-rl-kind="para" data-rl-move="1"' in out


def test_link_target_and_formatting_changes_are_named() -> None:
    """A changed link target and added bold are marked as such, not as new words."""
    out = diff_markdown(
        "See [the list](a.html) and approved.", "See [the list](b.html) and **approved**."
    )
    assert 'data-old-href="a.html"' in out
    assert 'data-rl-fmt="bold added"' in out


def test_table_rows_and_columns_keep_the_table_valid() -> None:
    """Inserted rows, deleted rows and added columns stay inside the cells."""
    old = "| A | B |\n| - | - |\n| 1 | x |\n| 2 | y |"
    new = "| A | B | C |\n| - | - | - |\n| 1 | x | n |\n| 3 | z | m |"
    out = _plain(diff_markdown(old, new))
    rows = out.split("\n")[:5]
    assert all(r.startswith("|") and r.endswith("|") for r in rows)
    assert 'rl-row-del"></span><del>2</del>' in out
    assert 'rl-col-ins"></span><ins>C</ins>' in out


def test_dissimilar_paragraph_is_deleted_and_inserted() -> None:
    """A paragraph replaced by different text is not word-diffed into a mix."""
    out = diff_markdown("Reviews by email are not accepted.", "Approval is given with a signature.")
    assert "rl-del" in out
    assert "rl-ins" in out


def test_word_diff_keeps_html_tags_whole() -> None:
    old = '| File <span class="dataview small-text">2</span> | x |'
    new = '| File <span class="dataview small-text">3</span> | x |'
    out = diff_markdown(old, new)
    assert '<span class="dataview small-text"><del>2</del><ins>3</ins></span>' in out
