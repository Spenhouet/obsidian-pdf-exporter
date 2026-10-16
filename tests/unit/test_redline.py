"""Tests for the redline (tracked-changes) diff."""

from __future__ import annotations

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
    return (output.parent / "_build_redline" / "redline_assembled.md").read_text(encoding="utf-8")


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
    out = diff_markdown(old, new)
    assert _blocks(out) == [
        "# Title {#title}",
        "Same.",
        "<del>Old</del><ins>New</ins> words here.",
        "Tail.",
    ]


def test_word_diff_keeps_spaces_around_markup() -> None:
    """Inserted and deleted words keep the spaces that separate them from their neighbours."""
    assert diff_markdown("a b c", "a x b c") == "a <ins>x</ins> b c"
    assert diff_markdown("a b c", "a c") == "a <del>b</del> c"


def test_inserted_and_deleted_list_items_keep_markers() -> None:
    """List markers and quote prefixes stay outside the inline markup."""
    old = "> - one\n> - two\n\n1. first\n2. second"
    new = "> - one\n> - two\n> - three\n\n1. first"
    out = diff_markdown(old, new)
    assert "> - two\n> - <ins>three</ins>" in out
    assert "1. first\n2. <del>second</del>" in out
